[← Back to codebase guide](CODEBASE-GUIDE.md)

# Canonical trace — header + log JSON correlation

This page is the operator-visible contract that ties an inbound HTTP request to the JSON log line(s) it produced. The implementation lives in [`app/core/request_context.py`](../app/core/request_context.py) (issue #334) and [`app/core/logging.py`](../app/core/logging.py). The contract here pins the observable behaviour, not the implementation, so it survives refactors of the middleware or the formatter.

## Two sides of the same id

Every request that reaches the FastAPI app carries a **request id** that moves through two channels in parallel:

| Channel | Surface | Constant | Source |
|---|---|---|---|
| HTTP | Response header `X-Request-ID` | [`X_REQUEST_ID_HEADER`](../app/core/request_context.py) | `CorrelationIdMiddleware` in [`app/main.py`](../app/main.py) |
| JSON log | Field `"request_id"` on every line emitted via `log_safe` | `request_id` allowlist in `JsonFormatter` | Read from `correlation_id_var` ContextVar |

Given one id, an operator can move from the client's HTTP response header to any log line in the same request without grep heuristics.

## Inbound-to-outbound lifecycle

The middleware honours an upstream `X-Request-ID` header when present, and generates a fresh 16-char UUID4 hex string otherwise. The id is then:

1. Stored on `request.state.correlation_id` for downstream code that needs it.
2. Set on a `ContextVar` (`correlation_id_var`) so `log_safe` reads it without threading arguments.
3. Echoed on the response as `X-Request-ID`.
4. Reset in a `finally` block so the `ContextVar` does not leak between concurrent requests.

The middleware is `app/core/request_context.py::CorrelationIdMiddleware`. The wiring is in `app/main.py::create_app` — the middleware must be added **first** (so it sits innermost) — see `app/main.py` for the pinned order and the regression test `tests/test_middleware_order.py`.

## JSON log shape

Every line emitted by `log_safe(event, **fields)` is a single-line JSON object with `request_id` populated when a request context is active, otherwise `""`. The `JsonFormatter` allowlist in `app/core/logging.py` controls which keys survive — adding a new key requires updating the allowlist and the PII-redaction list together. See [`docs/codebase/logging-conventions.md`](codebase/logging-conventions.md) for the wrapper's own contract (single entry point, PII redaction, no `logger.*` in `app/`).

Example log line emitted during a request:

```json
{"timestamp":"2026-09-12T08:15:30.123Z","level":"INFO","logger":"app.modules.animals","message":"","event":"animal.create","animal_id":"...","actor_user_id":"...","request_id":"a1b2c3d4e5f6a7b8"}
```

When `log_safe` is called outside a request context (lifespan startup, CLI scripts, scheduled jobs), `request_id` is the empty string — that is the expected marker, not a bug.

## Canonical events

These events are the minimum set an operator can rely on to diagnose an incident from a single `request_id`. Each event declares its event name and required fields; custom slices may add more.

| Event name | Trigger | Required fields |
|---|---|---|
| `auth.login.success` | OAuth callback sets the session cookie | `user_id`, `actor_email` |
| `auth.login.denied` | `usuarios_autorizados` rejects an email | `actor_email`, `reason` |
| `auth.logout` | `/logout` clears the session cookie | `user_id` |
| `validation.failed` | Route-level 422 on a form POST | `endpoint`, `errors_count` |
| `mutation.success` | Any successful POST/PATCH/DELETE | `endpoint`, `resource_id` |
| `backend.unhandled_error` | Global `BackendError` → 502 handler | (none — translated by port) |
| `server.unhandled_error` | Generic `Exception` → 502 handler | `exc_type` |

Slices may add more events; the convention is `domain.action.outcome` and required fields named in the slice's discovery doc. New canonical events require an update to this table.

## What this contract does not promise

- **No trace aggregation.** The contract is single-process. A request that fans out to N workers carries N ids, one per process. Cross-process tracing (OpenTelemetry, W3C trace context) is out of scope for this contract.
- **No client-side surfacing.** The header is for operators, not users. UI pages must not echo it back; no front-end code reads it.
- **No PII.** The id is a UUID hex; it carries no user data. If a downstream service stores it, store the same form — never hash it into a longer id, or the look-up table collapses.

## Core invariants

- **One middleware, one direction.** `CorrelationIdMiddleware` is the only component that reads inbound `X-Request-ID` and the only one that writes the outbound header.
- **One ContextVar.** `correlation_id_var` from `app/core/request_context.py` is the only place `log_safe` reads the id from. Do not add another source.
- **Allowlist, not denylist.** `JsonFormatter._ALLOWLIST` controls what appears in the JSON log. Adding a field requires both the allowlist and the PII list (`app/core/logging.py`).
- **Reset on the way out.** The `ContextVar` is reset in the middleware `finally` block. If the reset is removed, ids leak across requests in the same async task and the round-trip lookup breaks.

## Contributor checklist

- [ ] Any new log line goes through `log_safe` per [`docs/codebase/logging-conventions.md`](codebase/logging-conventions.md).
- [ ] New custom fields go through the `JsonFormatter._ALLOWLIST` and the PII-redaction list together — neither alone.
- [ ] New canonical events declare `event name + required fields` and are added to this table.
- [ ] Tests that assert log shape read via `caplog`/JSON capture, not via `print`.

## Tests pinning this contract

- `tests/integration/test_canonical_logs.py` — `log_safe` emits `request_id` matching the `ContextVar`.
- `tests/e2e/test_correlation_id_e2e.py` — `/healthz` response carries `X-Request-ID`; inbound header is honoured.

## Navigation

Previous: [logging-conventions.md](codebase/logging-conventions.md) | Next: [csrf-defense.md](codebase/csrf-defense.md)
