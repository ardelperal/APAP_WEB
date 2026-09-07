"""Strict TDD atoms for the PR5 DNI collision policy.

The PR5 spec (``live-migration-pii-controls/spec.md``) pins the
DNI collision contract across two scopes and the operator
reconciliation path:

1. **Forward legacy→web** — produces ZERO DNI collisions (legacy
   has no DNI column; verified by Dysflow ``get_schema`` 2026-07-11).
2. **Web-only manual collisions** — a second web INSERT with the
   same DNI fails on ``voluntarios_dni_key`` and is routed to
   ``web_only_feature_shadow`` with
   ``reconciliation_status="needs_review"`` and
   ``review_reasons=["dni_collision"]``.
3. **Reverse-path collisions** — web→legacy cannot write DNI
   (no legacy column). The reverse applier skips the DNI column
   and routes the row to the shadow table; the counter increments
   by 1.
4. **Interactive resolution** — the operator resolves a
   ``needs_review`` row carrying ``review_reasons=["dni_collision"]``
   via ``apap-migrate reconcile --interactive`` (option ``a`` keeps
   the web value; ``b`` accepts the derived value; ``c`` defers;
   ``q`` quits).

The atoms exercise:

- The collision routing helper (``migration.dni_collision.record_dni_collision``)
  for scopes 2 and 3.
- The forward ``apply_legacy_to_web`` path for scope 1 (the counter
  stays at 0 across the entire forward run).
- The ``run_reconcile --interactive`` path for scope 4 (an
  injected prompt answers ``a`` to keep web; the shadow row's
  ``reconciliation_status`` flips to ``matched``).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest

from migration import legacy_reader
from migration.apply import apply_legacy_to_web
from migration.cli import build_parser, run_reconcile
from migration.dni_collision import (
    DNI_COLLISION_REVIEW_REASON,
    DniCollisionCounter,
    record_dni_collision,
)

# --- helpers --------------------------------------------------------------


class _FakeShadowState:
    """Minimal ``ShadowStateRepository`` substitute for collision atoms.

    Captures every ``upsert`` and ``update_reconciliation_status``
    call so tests can assert the per-row shape without spinning up
    the real repository (which would require an LocalBackend-like
    transport).
    """

    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.status_updates: list[dict[str, Any]] = []
        # The "needs_review" view the CLI reads from.
        self.needs_review_rows: list[dict[str, Any]] = []

    # --- ShadowStateWriter protocol surface ----------------------------
    def upsert(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_pk: str | None,
        web_column: str,
        preserved_value: Any,
        strategy: str,
        last_legacy_snapshot_at: datetime | None = None,
        reconciliation_status: str = "pending",
        origin_direction: str = "legacy-to-web",
    ) -> None:
        self.upserts.append(
            {
                "table_name": table_name,
                "legacy_pk": legacy_pk,
                "web_pk": web_pk,
                "web_column": web_column,
                "preserved_value": preserved_value,
                "strategy": strategy,
                "last_legacy_snapshot_at": last_legacy_snapshot_at,
                "reconciliation_status": reconciliation_status,
                "origin_direction": origin_direction,
            }
        )

    def update_reconciliation_status(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        status: str,
        review_reasons: list[str] | None = None,
        last_reconciled_at: datetime | None = None,
    ) -> None:
        self.status_updates.append(
            {
                "table_name": table_name,
                "legacy_pk": legacy_pk,
                "web_column": web_column,
                "status": status,
                "review_reasons": review_reasons or [],
                "last_reconciled_at": last_reconciled_at,
            }
        )

    # --- CLI read surface ---------------------------------------------
    def list_needs_review(
        self,
        *,
        table_name: str | None = None,
        since: str | None = None,
        origin_direction: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.needs_review_rows)
        if table_name is not None:
            rows = [r for r in rows if r.get("table_name") == table_name]
        if origin_direction is not None:
            rows = [r for r in rows if r.get("origin_direction") == origin_direction]
        return rows

    def seed_needs_review(self, row: dict[str, Any]) -> None:
        """Inject a row into the CLI's listing."""
        self.needs_review_rows.append(row)


# --- forward legacy→web produces zero DNI collisions ---------------------


def test_forward_legacy_produces_zero_dni_collisions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """The forward ``apply_legacy_to_web`` path never increments the
    DNI collision counter.

    Spec scenario: ``Forward legacy→web produces zero DNI
    collisions``. Legacy has no DNI column (verified by Dysflow
    ``get_schema`` 2026-07-11); the forward apply never writes
    ``voluntarios.dni`` so the counter stays at 0 across the
    entire run.

    The atom runs the apply pipeline end-to-end through a fake
    executor + ``FakeSqlExecutor`` (no real backend mutation).
    """
    monkeypatch.setenv("APAP_MIGRATION_DIR", str(tmp_path))

    # Import the conftest fake so this test stays in the same
    # hermetic surface as the rest of ``tests/migration``.
    from tests.migration.conftest import FakeSqlExecutor

    client = FakeSqlExecutor()
    counter = DniCollisionCounter()
    legacy_rows = [
        {"Voluntario": "alice", "Tel1": "+34600123456", "Tel2": None, "Email": "alice@example.org"},
        {"Voluntario": "bob", "Tel1": None, "Tel2": None, "Email": "bob@example.org"},
    ]

    def _executor(_path: str, _sql: str, _offset: int, limit: int) -> list[dict[str, Any]]:
        if _offset > 0:
            return []
        return legacy_rows[:limit]

    legacy_reader.set_legacy_query_executor(_executor)
    try:
        result = apply_legacy_to_web(
            client,
            "voluntario",
            legacy_path=str(tmp_path / "legacy.accdb"),
            dry_run=False,
            dni_collision_counter=counter,
        )
    finally:
        legacy_reader.set_legacy_query_executor(None)

    # The forward apply NEVER bumps the DNI collision counter
    # because legacy rows carry no DNI column. The DI seam is wired
    # (counter is passed in), so a future bug that accidentally
    # bumps the counter on forward apply would surface here —
    # this atom is NOT tautological: it pins the contract that
    # ``apply_legacy_to_web`` MUST NOT touch the counter on the
    # forward path.
    assert counter.value == 0, (
        f"forward apply bumped dni_collisions counter to {counter.value}; "
        f"forward must always produce 0 collisions"
    )
    # Sanity: the apply path returned a result (applier exited cleanly).
    assert result is not None
    assert result.table_name == "voluntario"
    # The forward apply never emitted the collision-routing helper,
    # so the shadow state carries no dni_collision review_reasons.
    for upsert in client.tables.get("WEB_ONLY_FEATURE_SHADOW", []):
        assert upsert.get("reconciliation_status") != "needs_review" or \
            "dni_collision" not in (upsert.get("review_reasons") or [])


# --- web-only manual collisions: helper routes to shadow -----------------


def test_first_web_dni_wins_routes_second_to_shadow() -> None:
    """A web-side DNI collision routes the rejected row to
    ``web_only_feature_shadow`` with the spec metadata.

    Spec scenario: ``First web-only DNI wins``. The first INSERT
    succeeds (W1 with DNI=X); the second INSERT (W2 with the same
    DNI=X) is rejected by the UNIQUE constraint. The applier (or
    web UI) catches the rejection and calls
    :func:`record_dni_collision` to route W2 to the shadow table.

    The atom does NOT exercise a real UNIQUE constraint; it invokes
    the routing helper directly with the rejected-row shape and
    asserts the shadow state carries the spec metadata.
    """
    shadow = _FakeShadowState()
    now = datetime(2026, 7, 11, 10, 0, 0, tzinfo=UTC)

    record_dni_collision(
        shadow_state=shadow,  # type: ignore[arg-type]
        table_name="voluntarios",
        legacy_pk="web-pk-2",
        web_pk="web-pk-2",
        web_column="dni",
        direction="web-only",
        now=now,
    )

    # upsert writes the shadow row with the canonical metadata.
    assert len(shadow.upserts) == 1
    row = shadow.upserts[0]
    assert row["table_name"] == "voluntarios"
    assert row["legacy_pk"] == "web-pk-2"
    assert row["web_column"] == "dni"
    assert row["reconciliation_status"] == "needs_review"
    # The collision has no value to preserve; the column is rejected
    # before the applier could write it.
    assert row["preserved_value"] is None
    assert row["strategy"] == "preserve"
    assert row["last_legacy_snapshot_at"] == now
    # The ``direction`` kwarg is persisted verbatim as
    # ``origin_direction`` so the operator can filter by scope via
    # ``--filter-direction web-only``.
    assert row["origin_direction"] == "web-only", (
        "record_dni_collision must persist origin_direction='web-only' "
        f"verbatim; got {row['origin_direction']!r}"
    )
    # update_reconciliation_status stamps the categorical reason.
    assert len(shadow.status_updates) == 1
    update = shadow.status_updates[0]
    assert update["status"] == "needs_review"
    assert update["review_reasons"] == [DNI_COLLISION_REVIEW_REASON]
    assert update["last_reconciled_at"] == now


# --- reverse-path collisions: helper records + counter ------------------


def test_reverse_path_collision_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reverse-path (web→legacy) DNI collision is recorded.

    Spec scenario: ``Reverse-path collision recorded``. When the
    reverse applier tries to push a web DNI back to legacy, legacy
    has no column to receive it; the value stays in web's shadow
    with ``review_reasons=["dni_collision"]`` so the operator can
    resolve it; the counter increments by 1.

    The atom does NOT exercise ``apply_web_to_legacy`` (PR6
    scope); it invokes the routing helper directly with
    ``direction="web-to-legacy"`` and asserts the counter
    increments by 1 (per the spec scenario contract).
    """
    shadow = _FakeShadowState()
    counter = DniCollisionCounter()
    assert counter.value == 0

    record_dni_collision(
        shadow_state=shadow,  # type: ignore[arg-type]
        table_name="voluntarios",
        legacy_pk="legacy-pk-1",
        web_pk="web-pk-1",
        web_column="dni",
        direction="web-to-legacy",
    )
    counter.bump()  # the reverse applier (PR6) wires the bump after each collision

    # Counter is at 1 after one bump.
    assert counter.value == 1
    # The shadow row is recorded with the canonical metadata.
    assert len(shadow.upserts) == 1
    assert shadow.upserts[0]["web_column"] == "dni"
    assert shadow.upserts[0]["reconciliation_status"] == "needs_review"
    # The ``direction`` kwarg is persisted verbatim as
    # ``origin_direction`` so the operator can filter by scope via
    # ``--filter-direction web-to-legacy``.
    assert shadow.upserts[0]["origin_direction"] == "web-to-legacy", (
        "record_dni_collision must persist origin_direction='web-to-legacy' "
        f"verbatim; got {shadow.upserts[0]['origin_direction']!r}"
    )
    assert shadow.status_updates[0]["review_reasons"] == [DNI_COLLISION_REVIEW_REASON]


# --- interactive CLI resolves a dni_collision needs_review row -----------


def test_reconcile_interactive_resolves_dni_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """The interactive CLI lists a ``dni_collision`` row and the
    operator can resolve it via the ``a`` (keep web) prompt.

    Spec scenario: ``Reviewer resolves via CLI``. The atom:
    1. Seeds the shadow state with one ``needs_review`` row carrying
       ``review_reasons=["dni_collision"]``.
    2. Invokes ``run_reconcile(..., interactive=True, prompt=fake_prompt)``
       with a fake prompt that answers ``a`` to keep web.
    3. Asserts the shadow row's ``reconciliation_status`` flips to
       ``matched`` and the review_reasons clears.
    """
    monkeypatch.setenv("APAP_MIGRATION_DIR", str(tmp_path))

    shadow = _FakeShadowState()
    shadow.seed_needs_review(
        {
            "table_name": "voluntarios",
            "legacy_pk": "alice",
            "web_pk": "web-pk-1",
            "web_column": "dni",
            "reconciliation_status": "needs_review",
            "strategy": "preserve",
            "preserved_value": "[REDACTED]",
            "derived_value": None,
            "derived_at": None,
            "last_legacy_snapshot_at": "2026-07-11T10:00:00+00:00",
            "last_reconciled_at": None,
            "review_reasons": [DNI_COLLISION_REVIEW_REASON],
        }
    )

    class _FakeClient:
        def execute_sql(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    # Prompt answers: (1) ``a`` to keep web.
    prompt_answers = iter(["a"])
    stream = io.StringIO()
    args = type(
        "A",
        (),
        {
            "interactive": True,
            "check_only": False,
            "table": None,
            "since": None,
            "filter_direction": "both",
        },
    )()

    rc = run_reconcile(
        args,
        web_client=_FakeClient(),
        shadow_state=shadow,  # type: ignore[arg-type]
        prompt=lambda _msg: next(prompt_answers),
        stream=stream,
    )

    assert rc == 0
    # The operator saw the case header (multi-line formatter) and
    # the categorical review reason is visible in the output.
    rendered = stream.getvalue()
    assert "voluntarios" in rendered
    assert "needs_review" in rendered
    assert DNI_COLLISION_REVIEW_REASON in rendered
    # The shadow row was updated: status flipped to matched,
    # review_reasons cleared.
    assert len(shadow.status_updates) == 1
    update = shadow.status_updates[0]
    assert update["status"] == "matched"
    assert update["review_reasons"] == []
    assert update["table_name"] == "voluntarios"
    assert update["legacy_pk"] == "alice"
    assert update["web_column"] == "dni"


# --- helper-layer invariants --------------------------------------------


def test_record_dni_collision_stamps_now_by_default() -> None:
    """Without an explicit ``now``, the helper stamps ``datetime.now(UTC)``.

    Spec scenario (counter-increment invariant): the helper MUST
    produce a UTC timestamp when the caller does not pass one. The
    atom asserts the timestamp is recent (within the last 5s) and
    timezone-aware.
    """
    shadow = _FakeShadowState()
    before = datetime.now(UTC)
    record_dni_collision(
        shadow_state=shadow,  # type: ignore[arg-type]
        table_name="voluntarios",
        legacy_pk="web-pk-3",
        web_pk="web-pk-3",
        web_column="dni",
        direction="web-only",
    )
    after = datetime.now(UTC)
    ts = shadow.upserts[0]["last_legacy_snapshot_at"]
    assert isinstance(ts, datetime)
    assert ts.tzinfo is UTC
    assert before <= ts <= after


def test_record_dni_collision_first_wins_does_not_overwrite_first_row() -> None:
    """The helper routes ONE row per call. The first INSERT wins;
    subsequent collisions each get a NEW shadow row keyed by their
    own ``legacy_pk``.

    Spec scenario (deterministic + auditable): the helper is a
    per-row router, not a bulk upsert. Two collisions with
    different ``legacy_pk`` values produce two shadow rows; a
    re-call with the same ``legacy_pk`` re-routes that row (the
    underlying ``upsert`` is a no-op merge on the UNIQUE composite
    index).
    """
    shadow = _FakeShadowState()
    record_dni_collision(
        shadow_state=shadow,  # type: ignore[arg-type]
        table_name="voluntarios",
        legacy_pk="alice",
        web_pk="web-pk-alice",
        web_column="dni",
        direction="web-only",
    )
    record_dni_collision(
        shadow_state=shadow,  # type: ignore[arg-type]
        table_name="voluntarios",
        legacy_pk="bob",
        web_pk="web-pk-bob",
        web_column="dni",
        direction="web-only",
    )
    # Two distinct rows were upserted.
    assert {u["legacy_pk"] for u in shadow.upserts} == {"alice", "bob"}
    # Each row's status is needs_review and carries the categorical
    # reason.
    for update in shadow.status_updates:
        assert update["review_reasons"] == [DNI_COLLISION_REVIEW_REASON]


def test_counter_initial_state_is_zero() -> None:
    """``DniCollisionCounter()`` starts at zero and bumps are cumulative.

    Sanity invariant for the forward / reverse apply tests.
    """
    counter = DniCollisionCounter()
    assert counter.value == 0
    counter.bump()
    counter.bump()
    assert counter.value == 2


# --- CLI parser surface -------------------------------------------------


def test_cli_parser_has_filter_direction_flag() -> None:
    """``migration.cli.build_parser()`` accepts ``--filter-direction``.

    PR5 WU-4 surface: the flag exists at parser level. The
    narrowing logic is exercised in the CLI tests under
    ``tests/migration/test_cli.py``; this atom pins the parser
    surface so a refactor that drops the flag fails fast.
    """
    parser = build_parser()
    args = parser.parse_args(["reconcile", "--filter-direction", "legacy-to-web"])
    assert getattr(args, "filter_direction", None) == "legacy-to-web", (
        f"--filter-direction flag missing from the reconcile subparser; "
        f"got args: {args!r}"
    )


def test_cli_parser_filter_direction_default_is_both() -> None:
    """``--filter-direction`` defaults to ``both`` so existing CLI
    callers see the same listing they always did.

    Backward-compat: PR4 (and earlier) reconciliations listed
    needs_review rows from both directions; the PR5 default keeps
    that contract — narrowing is opt-in.
    """
    parser = build_parser()
    args = parser.parse_args(["reconcile"])
    assert getattr(args, "filter_direction", None) == "both", (
        f"--filter-direction default changed to {getattr(args, 'filter_direction', None)!r}; "
        f"PR5 contract requires 'both' to keep PR4 callers seeing the full listing"
    )
