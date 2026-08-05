"""Lifecycle event helpers for the reverse applier.

The reverse applier emits :class:`LifecycleEvent` records with
``event_type="LIFECYCLE_REVERSED"`` when a derived column on the web
side was overridden manually between forward and reverse apply.
The derivation engine is NEVER called on this path — the event is
observational only (the legacy write already committed).

Module attribute lookup is used for ``semantic_events_mod`` so
tests that monkeypatch ``migration.semantic_events.record_lifecycle_reversed``
(or ``persist_lifecycle_reversed``) see their patched callable.
This mirrors the ``logging_mod.log_safe`` discipline PR6
established in the orchestrator.
"""

from __future__ import annotations

from typing import Any

from migration import semantic_events as semantic_events_mod
from migration.reverse_apply.io_helpers import _case_insensitive_get
from migration.reverse_apply.types import _InsForgeLike


def _emit_reversed_lifecycle_events_for_changed_derived(
    *,
    client: _InsForgeLike,
    mapping: Any,
    existing_legacy_row: dict[str, Any],
    web_row: dict[str, Any],
    legacy_pk: str,
) -> None:
    """Emit ``LIFECYCLE_REVERSED`` events for changed derived columns.

    Iterates ``mapping.columns``; for each column with
    ``web_only_strategy == "derived"`` AND whose web-side value
    differs from the legacy-side value, construct a
    :class:`LifecycleEvent` via
    :func:`migration.semantic_events.record_lifecycle_reversed` and
    ``logging_mod.log_safe("lifecycle.reversed", ...)`` so the operator CLI /
    audit dashboards can render the transition. The derivation
    engine is NEVER called on this path — the event is observational
    only (the legacy write already committed).
    """
    from app.core import logging as logging_mod
    from migration.apply import _safe_table

    legacy_pk_id: int | None = None
    try:
        legacy_pk_id = int(legacy_pk)
    except (TypeError, ValueError):
        legacy_pk_id = None

    for col in mapping.columns:
        strategy = getattr(col, "web_only_strategy", None)
        if strategy != "derived":
            continue
        pre_state = existing_legacy_row.get(col.legacy_column or col.web_column)
        post_state = web_row.get(col.web_column)
        if pre_state == post_state:
            continue
        event = semantic_events_mod.record_lifecycle_reversed(
            pre_state=str(pre_state) if pre_state is not None else None,
            post_state=str(post_state) if post_state is not None else None,
            legacy_source_table=mapping.legacy_table,
            legacy_source_id=legacy_pk_id,
        )
        animal_id = _case_insensitive_get(web_row, "id")
        if animal_id is None:
            # noqa S608: ambos identificadores pasan por ``_safe_table()``,
            # que lanza si no casan ``^[A-Za-z_][A-Za-z0-9_]*$``;
            # ``legacy_pk`` va como bind param ``$1``. Sin operandos de
            # request. Issue #387.
            rows = client.execute_sql(
                f"SELECT id FROM {_safe_table(mapping.web_table)} "  # noqa: S608
                f"WHERE {_safe_table(mapping.key_field)} = $1",
                [legacy_pk],
            )
            animal_id = rows[0].get("id") if rows else None
        if animal_id is None:
            raise ValueError(
                f"Cannot resolve animal_id for reversed lifecycle event {legacy_pk!r}"
            )
        semantic_events_mod.persist_lifecycle_reversed(
            web_client=client,
            event=event,
            animal_id=str(animal_id),
            source_entity_id=str(animal_id),
        )
        logging_mod.log_safe(
            "lifecycle.reversed",
            table=mapping.web_table,
            pk=legacy_pk,
            legacy_source_table=event.legacy_source_table,
            legacy_source_id=event.legacy_source_id,
            pre_state=event.metadata.get("pre_state") if event.metadata else None,
            post_state=event.metadata.get("post_state") if event.metadata else None,
            source_direction=(
                event.metadata.get("source_direction") if event.metadata else None
            ),
            actor="apply_reverse",
        )


__all__ = [
    "_emit_reversed_lifecycle_events_for_changed_derived",
]
