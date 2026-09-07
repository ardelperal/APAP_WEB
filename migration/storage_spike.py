"""Read-only InsForge storage contract probe for PR4a.

This module intentionally does not implement media upload/download helpers.
It only probes the deployed storage contract with safe read methods so PR4b
can be gated on empirical evidence instead of assumed documentation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_ONLY_METHODS = frozenset({"GET", "HEAD"})
DEFAULT_DISCOVERY_PATH = Path("docs/discovery/storage-contract-2026-Q3.md")
DEFAULT_ENDPOINT_PATH = "/api/storage/downloadStrategy"
PINNED_DOWNLOAD_STRATEGY_ENDPOINT = (
    "/api/storage/buckets/apap-photos/download-strategy/objects/{key}"
)

_SCHEMA = "apap.storage-contract-probe/v1"
_PASS = "PASS"
_BLOCKED = "BLOCKED"


class MutationRefusedError(RuntimeError):
    """Raised before any network call when a mutation method is requested."""


@dataclass(frozen=True, slots=True)
class StorageProbeConfig:
    """Operator configuration for the read-only storage contract probe."""

    base_url: str
    service_key: str
    storage_path: str
    expires_in: int = 3600
    endpoint_path: str = DEFAULT_ENDPOINT_PATH
    timeout: float = 10.0


@dataclass(frozen=True, slots=True)
class StorageProbeResult:
    """Redacted, deterministic storage probe evidence."""

    _payload: dict[str, Any]
    evidence_hash: str

    @property
    def status(self) -> str:
        return str(self._payload["status"])

    @property
    def pr4b_gate(self) -> str:
        return str(self._payload["pr4b_gate"])

    def to_machine_dict(self) -> dict[str, Any]:
        """Return redacted machine-readable evidence including its hash."""
        return {**self._payload, "evidence_hash": self.evidence_hash}


class ReadOnlyProbeHttpClient:
    """Tiny HTTPX wrapper that refuses mutating methods before transport."""

    def __init__(
        self,
        *,
        base_url: str,
        service_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        include_auth: bool = True,
    ) -> None:
        headers: dict[str, str] = {}
        if include_auth and service_key:
            headers["Authorization"] = f"Bearer {service_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            transport=transport,
            timeout=timeout,
        )

    def __enter__(self) -> ReadOnlyProbeHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a read-only request or raise before network on mutations."""
        normalized = method.upper()
        if normalized in MUTATION_METHODS or normalized not in READ_ONLY_METHODS:
            raise MutationRefusedError(
                f"storage contract spike refuses HTTP {normalized}; read-only methods only"
            )
        return self._client.request(normalized, url, **kwargs)


def probe_download_strategy(
    config: StorageProbeConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> StorageProbeResult:
    """Probe the candidate download-strategy endpoint without mutations."""
    try:
        with ReadOnlyProbeHttpClient(
            base_url=config.base_url,
            service_key=config.service_key,
            transport=transport,
            timeout=config.timeout,
        ) as client:
            response = client.request(
                "GET",
                config.endpoint_path,
                params={"path": config.storage_path, "expiresIn": str(config.expires_in)},
            )
    except MutationRefusedError:
        return _result(
            _base_payload(config)
            | {
                "status": "mutation_refused",
                "pr4b_gate": _BLOCKED,
                "decision_reason": "Probe attempted a mutating HTTP method.",
            }
        )
    except httpx.TimeoutException:
        return _network_failure(config, "timeout")
    except httpx.HTTPError:
        return _network_failure(config, "network_error")

    body = _safe_json(response)
    status = _status_from_code(response.status_code)
    strategy_without_auth_status = None
    if status == "not_found":
        strategy_without_auth_status = _probe_strategy_without_auth(config, transport=transport)
    payload = _base_payload(config) | {
        "status": status,
        "pr4b_gate": _BLOCKED,
        "strategy_status_code": response.status_code,
        "strategy_without_auth_status_code": strategy_without_auth_status,
        "strategy_headers": _header_shape(response.headers),
        "strategy_body_shape": _body_shape(body),
    }

    if status == "not_found" and _status_from_optional_code(strategy_without_auth_status) in {
        "auth_failed",
        "forbidden",
    }:
        return _result(
            payload
            | {
                "status": "object_not_found",
                "pr4b_gate": _PASS,
                "required_auth_header": "Authorization: Bearer <service_key>",
                "decision_reason": (
                    "Download strategy endpoint and bearer auth are proven; "
                    "synthetic sentinel object does not exist."
                ),
            }
        )

    if not response.is_success:
        return _result(payload | {"decision_reason": _blocked_reason(status)})

    if not isinstance(body, dict) or not isinstance(body.get("url"), str):
        return _result(
            payload
            | {
                "status": "unsupported_shape",
                "decision_reason": "2xx response did not include a returned URL string.",
            }
        )

    returned_url = body["url"]
    object_head = _probe_returned_url_head(config, returned_url, transport=transport)
    resolved = _resolve_auth_behavior(object_head)
    return _result(
        payload
        | {
            "status": resolved["status"],
            "pr4b_gate": resolved["pr4b_gate"],
            "required_auth_header": resolved["required_auth_header"],
            "returned_url": "<redacted-url>",
            "object_head": {
                "with_auth_status": object_head["with_auth_status"],
                "without_auth_status": object_head["without_auth_status"],
            },
            "decision_reason": resolved["decision_reason"],
        }
    )


def missing_credentials_result(storage_path: str) -> StorageProbeResult:
    """Build blocked evidence when operator env is unavailable."""
    return _result(
        {
            "schema": _SCHEMA,
            "probe": "download_strategy",
            "status": "missing_credentials",
            "pr4b_gate": _BLOCKED,
            "canonical_endpoint": DEFAULT_ENDPOINT_PATH,
            "storage_path": "<redacted-path>",
            "strategy_status_code": None,
            "strategy_headers": [],
            "strategy_body_shape": {},
            "returned_url": None,
            "required_auth_header": "unknown",
            "object_head": {"with_auth_status": None, "without_auth_status": None},
            "decision_reason": (
                "Live probe did not run: missing "
                "APAP_INSFORGE_URL/APAP_INSFORGE_SERVICE_KEY"
            ),
        }
    )


def build_pinned_operator_evidence_result() -> StorageProbeResult:
    """Build deterministic redacted evidence from the reversible operator probe."""
    return _result(
        {
            "schema": _SCHEMA,
            "probe": "storage_contract_operator_sentinel",
            "status": "supported",
            "pr4b_gate": _PASS,
            "canonical_endpoint": PINNED_DOWNLOAD_STRATEGY_ENDPOINT,
            "storage_path": "<redacted-path>",
            "strategy_status_code": 200,
            "strategy_without_auth_status_code": 401,
            "strategy_headers": [],
            "strategy_body_shape": {
                "expiresAt": "str",
                "method": "str",
                "url": "url",
            },
            "strategy_without_auth_body_shape": {
                "error": "str",
                "message": "str",
                "nextActions": "list",
                "statusCode": "int",
            },
            "required_auth_header": "Authorization: Bearer <service_key>",
            "download_method": "presigned",
            "returned_url": "<redacted-url>",
            "returned_url_auth": "self-authenticating",
            "returned_url_exposure": "server-stream-only",
            "object_head": {
                "with_auth_status": 200,
                "without_auth_status": 200,
            },
            "upload_contract": {
                "protocol": "s3-compatible",
                "strategy_fields_present": True,
                "confirm_required": True,
                "transfer_method_rule": "POST when fields present; PUT when fields absent",
                "confirm_status_code": 201,
                "steps": [
                    "request_upload_strategy",
                    "transfer_object",
                    "confirm_upload",
                ],
            },
            "bucket": {
                "bucket_name": "apap-photos",
                "is_public": False,
            },
            "cleanup": {
                "sentinel_delete_status_code": 200,
                "post_list_object_count": 0,
                "post_list_total": 0,
                "success": True,
                "leftovers": False,
            },
            "decision_reason": (
                "Reversible operator sentinel proved strategy auth, presigned download, "
                "three-step S3 upload confirmation, and cleanup."
            ),
        }
    )


def write_discovery_document(result: StorageProbeResult, output_path: str | Path) -> None:
    """Write the redacted discovery artifact consumed by PR4b."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence = result.to_machine_dict()
    verdict = evidence["pr4b_gate"]
    endpoint_decision = (
        f"- Canonical endpoint: `{evidence['canonical_endpoint']}`"
        if verdict == _PASS
        else "- Pinned canonical endpoint: `unknown`"
    )
    auth_decision = (
        f"- Required auth header: `{evidence['required_auth_header']}`"
        if verdict == _PASS
        else "- Required auth header: `unknown`"
    )
    live_note = ""
    if evidence["status"] == "missing_credentials":
        live_note = (
            "\n- Live probe did not run: missing "
            "APAP_INSFORGE_URL/APAP_INSFORGE_SERVICE_KEY"
        )
    presigned_note = ""
    if evidence.get("returned_url_exposure") == "server-stream-only":
        presigned_note = (
            "\n- Returned presigned URL: self-authenticating; `server-stream-only`; "
            "MUST NOT be exposed to browser/client."
        )
    operator_note = ""
    if evidence.get("upload_contract"):
        operator_note = (
            "\n- Operator-supplied reversible sentinel evidence: "
            "S3-compatible three-step upload; `confirmRequired=true`; "
            "confirm status 201; cleanup restored object_count=0 and total=0."
        )
    strategy_request_note = (
        "- Strategy request: GET with `expiresIn=3600` and service-key bearer auth."
    )
    returned_request_note = (
        "- Returned URL request: HEAD without auth, then HEAD with service-key bearer auth."
    )
    if evidence.get("probe") == "storage_contract_operator_sentinel":
        strategy_request_note = (
            "- Strategy verification: authenticated GET 200; unauthenticated GET 401."
        )
        returned_request_note = (
            "- Returned presigned URL verification: HEAD 200 with and without bearer."
        )
    content = f"""# Storage Contract Discovery — 2026 Q3

## Scope

PR4a records the deployed InsForge storage contract needed by PR4b.
Agent-side probe remains GET/HEAD-only and refuses POST, PUT, PATCH, and DELETE
before any network transport receives a request. Operator-supplied reversible
sentinel evidence is persisted only as redacted status/shape categories.
The artifact never records service keys, credentialed URLs, raw body values,
or object bytes.

## Methodology

- Candidate endpoint probed: `{evidence['canonical_endpoint']}`.
- Candidate object path: `<redacted-path>`.
{strategy_request_note}
{returned_request_note}
- Recorded evidence is a redacted shape: status codes, header names, body field
  types, endpoint path, auth-header behavior, and deterministic evidence hash.

## Evidence

```json
{json.dumps(evidence, indent=2, sort_keys=True)}
```

Evidence hash: `{result.evidence_hash}`

## Decision

- Verdict: {verdict}
- PR4b gate: {verdict}
{endpoint_decision}
{auth_decision}
- Decision reason: {evidence['decision_reason']}{live_note}{operator_note}{presigned_note}
"""
    path.write_text(content, encoding="utf-8")


def main(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | os._Environ[str] | None = None,
    stream: Any | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """CLI entry point for ``python -m migration.storage_spike``."""
    parser = argparse.ArgumentParser(
        prog="python -m migration.storage_spike",
        description="Read-only InsForge storage contract probe for PR4a.",
    )
    parser.add_argument("--probe", choices=["download_strategy"], required=True)
    parser.add_argument("--path", dest="storage_path", required=True)
    parser.add_argument("--output", default=str(DEFAULT_DISCOVERY_PATH))
    parser.add_argument("--expires-in", type=int, default=3600)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    base_url: str | None
    service_key: str | None
    if env is None:
        from app.core.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()
        base_url = settings.insforge_url  # type: ignore[attr-defined]  # removed in #658; rewritten in #8
        service_key = settings.insforge_service_key  # type: ignore[attr-defined]  # removed in #658; rewritten in #8
    else:
        env_map = env
        base_url = env_map.get("APAP_INSFORGE_URL")
        service_key = env_map.get("APAP_INSFORGE_SERVICE_KEY")
    out = sys.stdout if stream is None else stream

    if not base_url or not service_key:
        result = missing_credentials_result(args.storage_path)
    else:
        result = probe_download_strategy(
            StorageProbeConfig(
                base_url=base_url,
                service_key=service_key,
                storage_path=args.storage_path,
                expires_in=args.expires_in,
                timeout=args.timeout,
            ),
            transport=transport,
        )

    write_discovery_document(result, args.output)
    out.write(json.dumps(result.to_machine_dict(), sort_keys=True) + "\n")
    return 0 if result.pr4b_gate == _PASS else 3


def _probe_strategy_without_auth(
    config: StorageProbeConfig,
    *,
    transport: httpx.BaseTransport | None,
) -> int | None:
    try:
        with ReadOnlyProbeHttpClient(
            base_url=config.base_url,
            transport=transport,
            timeout=config.timeout,
            include_auth=False,
        ) as client:
            return client.request(
                "GET",
                config.endpoint_path,
                params={"path": config.storage_path, "expiresIn": str(config.expires_in)},
            ).status_code
    except (httpx.HTTPError, MutationRefusedError):
        return None


def _probe_returned_url_head(
    config: StorageProbeConfig,
    returned_url: str,
    *,
    transport: httpx.BaseTransport | None,
) -> dict[str, int | None]:
    without_auth = _head_status(
        config,
        returned_url,
        include_auth=False,
        transport=transport,
    )
    with_auth = _head_status(
        config,
        returned_url,
        include_auth=True,
        transport=transport,
    )
    return {"without_auth_status": without_auth, "with_auth_status": with_auth}


def _head_status(
    config: StorageProbeConfig,
    returned_url: str,
    *,
    include_auth: bool,
    transport: httpx.BaseTransport | None,
) -> int | None:
    try:
        with ReadOnlyProbeHttpClient(
            base_url=config.base_url,
            service_key=config.service_key,
            transport=transport,
            timeout=config.timeout,
            include_auth=include_auth,
        ) as client:
            return client.request("HEAD", returned_url).status_code
    except (httpx.HTTPError, MutationRefusedError):
        return None


def _resolve_auth_behavior(object_head: dict[str, int | None]) -> dict[str, str]:
    with_auth = object_head["with_auth_status"]
    without_auth = object_head["without_auth_status"]
    with_auth_status = _status_from_optional_code(with_auth)
    without_auth_status = _status_from_optional_code(without_auth)

    if with_auth_status in {"supported", "not_found"} and without_auth_status in {
        "auth_failed",
        "forbidden",
    }:
        status = "object_not_found" if with_auth_status == "not_found" else "supported"
        reason = (
            "Returned URL requires service-key bearer auth; synthetic sentinel object does not exist."
            if status == "object_not_found"
            else "Returned URL requires service-key bearer auth."
        )
        return {
            "status": status,
            "pr4b_gate": _PASS,
            "required_auth_header": "Authorization: Bearer <service_key>",
            "decision_reason": reason,
        }
    if without_auth_status == "supported":
        return {
            "status": "supported",
            "pr4b_gate": _PASS,
            "required_auth_header": "none (returned URL is self-authorizing)",
            "decision_reason": "Returned URL is readable without an extra auth header.",
        }
    if with_auth_status == "method_not_allowed" or without_auth_status == "method_not_allowed":
        status = "method_not_allowed"
    else:
        status = with_auth_status if with_auth_status != "network_error" else without_auth_status
    return {
        "status": status,
        "pr4b_gate": _BLOCKED,
        "required_auth_header": "unknown",
        "decision_reason": _blocked_reason(status),
    }


def _network_failure(config: StorageProbeConfig, status: str) -> StorageProbeResult:
    return _result(
        _base_payload(config)
        | {
            "status": status,
            "pr4b_gate": _BLOCKED,
            "decision_reason": _blocked_reason(status),
        }
    )


def _base_payload(config: StorageProbeConfig) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "probe": "download_strategy",
        "status": "unknown",
        "pr4b_gate": _BLOCKED,
        "canonical_endpoint": config.endpoint_path,
        "storage_path": "<redacted-path>",
        "strategy_status_code": None,
        "strategy_without_auth_status_code": None,
        "strategy_headers": [],
        "strategy_body_shape": {},
        "returned_url": None,
        "required_auth_header": "unknown",
        "object_head": {"with_auth_status": None, "without_auth_status": None},
        "decision_reason": "Probe has not completed.",
    }


def _result(payload: dict[str, Any]) -> StorageProbeResult:
    stable_payload = _stable(payload)
    digest = hashlib.sha256(
        json.dumps(
            stable_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return StorageProbeResult(stable_payload, digest)


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _stable(value[k]) for k in sorted(value)}
    if isinstance(value, list | tuple):
        return [_stable(item) for item in value]
    return value


def _status_from_optional_code(status_code: int | None) -> str:
    if status_code is None:
        return "network_error"
    return _status_from_code(status_code)


def _status_from_code(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "supported"
    if status_code == 401:
        return "auth_failed"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 405:
        return "method_not_allowed"
    return "unexpected_status"


def _blocked_reason(status: str) -> str:
    return {
        "auth_failed": "Storage probe received 401; auth contract is not pinned.",
        "forbidden": "Storage probe received 403; authorization is not pinned.",
        "not_found": "Storage probe received 404; endpoint or sentinel path is unproven.",
        "object_not_found": "Endpoint and auth are proven; synthetic sentinel object does not exist.",
        "method_not_allowed": "Storage probe received 405; safe method contract is unproven.",
        "timeout": "Storage probe timed out; PR4b must not assume the contract.",
        "network_error": "Storage probe hit a network error; PR4b must not assume the contract.",
        "unexpected_status": "Storage probe returned an unsupported status code.",
        "unsupported_shape": "Storage probe returned a body shape PR4b cannot consume.",
    }.get(status, "Storage probe did not prove the deployed contract.")


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return response.text


def _header_shape(headers: httpx.Headers) -> list[str]:
    sensitive = {"authorization", "cookie", "set-cookie"}
    return sorted(name.lower() for name in headers if name.lower() not in sensitive)


def _body_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _body_value_shape(key, value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return "list"
    return _type_name(value)


def _body_value_shape(key: Any, value: Any) -> str:
    if str(key).lower() == "url" or _looks_like_url(value):
        return "url"
    return _type_name(value)


def _looks_like_url(value: Any) -> bool:
    """Inspect JSON payload values for http/https URL scheme prefixes (structural triage)."""
    return isinstance(value, str) and value.startswith(("http://", "https://"))  # noqa: S5332



def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return "str"


if __name__ == "__main__":  # pragma: no cover - exercised via CLI in operator runs
    raise SystemExit(main())
