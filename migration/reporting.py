"""Reporting dataclasses para el módulo de migración (LIFECYCLE-03 / migration-01).

``Diff`` y ``Conflict`` son las unidades atómicas de cambio/desacuerdo que el
diff engine produce. ``MigrationReport`` es el registro inmutable de una
corrida de migración: el operador lo lee después del run para entender qué
se aplicó, qué se skipeó y qué se abortó.

``MigrationReport`` es ``frozen=True`` a propósito: el audit trail debe ser
tamper-evident. Si el operador quiere anotar algo post-run, crea un nuevo
``MigrationReport`` con los datos extendidos; nunca muta el original.

Los métodos ``to_json`` y ``to_markdown`` son la única salida pública del
reporte: el CLI los usa para pipe a ``jq`` / ``less`` o para archivar el
reporte como evidencia de la corrida.

``MigrationReport.reconciliation_summary`` (PR 4/6 of
``web-only-feature-preservation``): el applier de MIGRATION-01 PR 5/6 lo
popula con el ``ReconciliationSummary`` que devuelve el hook
``post_apply_diff`` (definido en ``migration.reconcile``). El
campo es opcional (``None`` por default) para mantener
backward-compat con los reportes de MIGRATION-01 PR 1–3, donde el
hook todavía no corría. Una vez que el applier wire-up se activa en
MIGRATION-01 PR 5/6, el reporte siempre lleva el bundle poblado.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    # Importación solo para anotaciones — evita el ciclo
    # ``reporting`` → ``reconcile`` → ``derivation`` → ``reporting``
    # en import-time (los tests usan imports absolutos cuando los
    # necesitan en runtime).
    from migration.reconcile import ReconciliationSummary

# --- Diff -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Diff:
    """Una diferencia atómica detectada por el diff engine.

    ``op`` indica la operación que el applier debe ejecutar; ``key`` es el
    identificador estable de la fila (puede ser el natural key legacy, el
    UUID web o una concatenación que el mapping YAML defina);
    ``legacy_row`` y ``web_row`` son snapshots opcionales del estado en cada
    lado (útiles para el markdown report); ``changed_fields`` lista las
    columnas que difieren (solo relevante para ``op="UPDATE"``).

    **Campos extendidos en PR 4/6 (T5 — diff engine)**:

    - ``table``: nombre de la tabla web (``"animales"``, ``"entradas"``…)
      sobre la que aplica la diff. Permite al applier rutear
      ``INSERT``/``UPDATE``/``DELETE`` sincrónicamente y al reporte
      agrupar por tabla.
    - ``legacy_pk``: PK legacy (``int`` o ``str``) — ``None`` para INSERTs
      que nacen del web (inverse direction) y para NOOPs donde el PK
      no es relevante.
    - ``web_pk``: UUID v4 web — ``None`` para INSERTs que aún no se
      aplicaron (la web generará el UUID al insertar) y para DELETEs
      del legacy (no hay contraparte web).
    - ``conflict``: ``True`` cuando AMBAS partes se modificaron desde
      ``last_sync_at`` (regla #13475 v2 — active-passive estricto). El
      applier NO aplica diffs con ``conflict=True`` sin resolución
      explícita del operador (``--conflict web|legacy|abort``).
    - ``reason``: clasificación humana del diff (ej:
      ``"modified_both_sides"``, ``"legacy_new"``, ``"web_orphaned"``).
      Sirve para diagnóstico y para tests parametrizados.

    Los campos ``legacy_row`` / ``web_row`` / ``changed_fields`` /
    ``key`` se preservan para backward-compat con PR 1-3 (tests del
    skeleton). El diff engine los puebla a partir de los snapshots y
    la spec del mapping.
    """

    op: Literal["INSERT", "UPDATE", "DELETE", "NOOP"]
    key: str
    table: str = ""
    legacy_pk: int | str | None = None
    web_pk: str | None = None
    legacy_row: dict[str, Any] | None = None
    web_row: dict[str, Any] | None = None
    changed_fields: tuple[str, ...] = ()
    conflict: bool = False
    reason: str = ""


# --- Conflict -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Conflict:
    """Un desacuerdo detectado por el diff engine que requiere decisión del operador.

    Los conflictos siguen la regla active-passive (#13475): una fila no puede
    haber sido modificada en ambas apps desde el último sync sin que el
    operador elija manualmente qué versión gana (``--conflict web|legacy|abort``).
    """

    table: str
    key: str
    reason: Literal[
        "modified_both_sides", "deleted_both_sides", "fk_violation", "duplicate_natural_key"
    ]
    legacy_state: dict[str, Any] | None = None
    web_state: dict[str, Any] | None = None
    last_sync_at: datetime | None = None


# --- MigrationReport ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """Registro inmutable de una corrida de migración.

    ``direction`` indica el sentido (``legacy-to-web`` o ``web-to-legacy``);
    ``mode`` indica si fue full / incremental / dry-run / status;
    ``dry_run=True`` significa que se calcularon los diffs pero NO se aplicó
    ninguno (``applied=False`` siempre que ``dry_run=True``);
    ``backup_path`` solo se popula en corridas web→legacy que efectivamente
    crearon un backup pre-flight.

    PR3/M1 extensions (design D11) — backward-compatible default
    factories; pre-PR3 reports stay valid:

    - ``counts``: per-table row counts, shaped as
      ``{table_name: {"count_legacy": N, "count_web": M}}``.
    - ``source_hashes``: per-table SHA-256 hex strings of the legacy
      source at apply time (``{table_name: "<sha256 hex>"}``). The
      ``.accdb`` and photos-directory hashes live in the
      ``migration.lock_snapshot.json`` file; this field tracks the
      per-table fingerprint for fast operator review without opening
      the snapshot file.
    - ``collisions``: per-table counters — counts only, no values.
      Typical keys: ``preserve_advances`` (renamed from ``dni_collisions`` in issue #217), ``row_divergences``. The
      operator-facing detail (which PKs collided) lives in
      ``web_only_feature_shadow`` and the ``conflicts`` list, NOT
      here. This invariant keeps the JSON serialization free of
      raw PII and PK strings.
    """

    direction: Literal["legacy-to-web", "web-to-legacy", "both"]
    mode: Literal["full", "incremental", "dry-run", "status"]
    dry_run: bool
    applied: bool
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    diffs: tuple[Diff, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    backup_path: str | None = None
    error: str | None = None
    # PR 4/6 (web-only-feature-preservation, T4.6): the applier wires
    # ``post_apply_diff`` (see ``migration.reconcile``) and
    # attaches its ``ReconciliationSummary`` here. ``None`` keeps the
    # pre-PR-4 reports valid (MIGRATION-01 PR 1–3 never run the hook).
    reconciliation_summary: ReconciliationSummary | None = None
    # PR3/M1 source-identity fields (design D11). Default factories
    # preserve backward-compat for every pre-PR3 caller.
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    source_hashes: dict[str, str] = field(default_factory=dict)
    collisions: dict[str, dict[str, int]] = field(default_factory=dict)

    # --- serializers ---------------------------------------------------

    def to_json(self) -> str:
        """Serializa el reporte a JSON UTF-8 indentado.

        ``asdict()`` aplana el dataclass (incluyendo ``Diff``/``Conflict``
        anidados) a ``dict``/``list``; ``datetime`` se serializa como
        ISO-8601 vía el ``default``; ``tuple`` se serializa como ``list``
        automáticamente. Cualquier tipo no soportado levanta ``TypeError``
        explícito para que un bug en el reporte no pase silencioso.
        """
        return json.dumps(
            asdict(self),
            default=_json_default,
            indent=2,
            ensure_ascii=False,
        )

    def to_markdown(self) -> str:
        """Renderiza el reporte como markdown legible para el operador.

        Estructura:

        - Header con ``direction`` / ``mode`` / ``dry_run`` / ``applied``.
        - Bloque de métricas (totales de INSERTs/UPDATEs/DELETEs/NOOPs +
          conflicts).
        - Tabla de conflicts (si hay).
        - Sección ``## Source Identity`` (PR3/M1) si alguno de los
          campos ``counts`` / ``source_hashes`` / ``collisions`` está
          poblado. Vacío por default para preservar el shape de los
          reportes pre-PR3.
        - Footer con timestamps y duración.
        """
        sections = [
            self._md_header(),
            self._md_metrics(),
            self._md_conflicts(),
            self._md_reconciliation(),
            self._md_source_identity(),
            self._md_timing(),
        ]
        return "".join(sections)

    def _md_header(self) -> str:
        """Header con direction/mode/dry_run/applied."""
        lines = [
            "# Migration Report",
            "",
            f"- **Direction**: `{self.direction}`",
            f"- **Mode**: `{self.mode}`",
            f"- **Dry run**: `{self.dry_run}`",
            f"- **Applied**: `{self.applied}`",
            "",
        ]
        return "\n".join(lines)

    def _md_metrics(self) -> str:
        """Metrics table: INSERTs/UPDATEs/DELETEs/NOOPs + conflicts."""
        return self._md_metrics_table(self._md_metric_counts())

    def _md_metric_counts(self) -> dict[str, int]:
        """Per-op counters plus conflicts and total.

        Returns ``{"INSERT": N, "UPDATE": N, "DELETE": N, "NOOP": N,
        "Conflict": N, "Total": N}``. ``Total`` excludes conflicts to keep
        the count focused on diff rows.
        """
        counts: dict[str, int] = {
            "INSERT": 0,
            "UPDATE": 0,
            "DELETE": 0,
            "NOOP": 0,
        }
        for d in self.diffs:
            if d.op in counts:
                counts[d.op] += 1
        counts["Conflict"] = len(self.conflicts)
        counts["Total"] = (
            counts["INSERT"] + counts["UPDATE"] + counts["DELETE"] + counts["NOOP"]
        )
        return counts

    def _md_metrics_table(self, counts: dict[str, int]) -> str:
        """Render the metrics table given a counts dict from :meth:`_md_metric_counts`."""
        lines = [
            "## Metrics",
            "",
            "| Op | Count |",
            "|---|---|",
            f"| INSERT | {counts['INSERT']} |",
            f"| UPDATE | {counts['UPDATE']} |",
            f"| DELETE | {counts['DELETE']} |",
            f"| NOOP | {counts['NOOP']} |",
            f"| Conflict | {counts['Conflict']} |",
            f"| Total | {counts['Total']} |",
            "",
        ]
        return "\n".join(lines)

    def _md_conflicts(self) -> str:
        """Conflicts table — empty string when there are no conflicts."""
        if not self.conflicts:
            return ""
        lines = [
            "## Conflicts",
            "",
            "| Table | Key | Reason |",
            "|---|---|---|",
        ]
        for c in self.conflicts:
            lines.append(f"| {c.table} | {c.key} | {c.reason} |")
        lines.append("")
        return "\n".join(lines)

    def _md_reconciliation(self) -> str:
        """Reconciliation summary — empty string when not attached by applier."""
        if self.reconciliation_summary is None:
            return ""
        rs = self.reconciliation_summary
        lines = [
            "## Reconciliation",
            "",
            "| Status | Count |",
            "|---|---|",
            f"| Matched | {rs.matched} |",
            f"| Divergent | {rs.divergent} |",
            f"| Needs review | {rs.needs_review} |",
            "",
        ]
        return "\n".join(lines)

    def _md_source_identity(self) -> str:
        """Source identity tables — empty string when none of the fields are populated.

        The three sub-tables are emitted by :meth:`_md_counts_table`,
        :meth:`_md_source_hashes_table` and :meth:`_md_collisions_table`;
        this method only concatenates them under a single ``## Source
        Identity`` header so each sub-table can be tested independently.
        Keeps the pre-PR3 markdown shape unchanged for callers that don't
        set the new fields (backward-compat).
        """
        sections = (
            self._md_counts_table(),
            self._md_source_hashes_table(),
            self._md_collisions_table(),
        )
        body = "\n".join(s for s in sections if s)
        if not body:
            return ""
        return "## Source Identity\n\n" + body

    def _md_counts_table(self) -> str:
        if not self.counts:
            return ""
        body = "\n".join(
            f"| {t} | {c.get('count_legacy', '')} | {c.get('count_web', '')} |"
            for t, c in self.counts.items()
        )
        return (
            f"### Counts\n\n| Table | count_legacy | count_web |\n"
            f"|---|---|---|\n{body}\n"
        )

    def _md_source_hashes_table(self) -> str:
        if not self.source_hashes:
            return ""
        body = "\n".join(
            f"| {t} | `{sha}` |" for t, sha in self.source_hashes.items()
        )
        return (
            f"### Source hashes\n\n| Table | sha256 |\n"
            f"|---|---|\n{body}\n"
        )

    def _md_collisions_table(self) -> str:
        if not self.collisions:
            return ""
        body = "\n".join(
            f"| {t} | {k} | {v} |"
            for t, counters in self.collisions.items()
            for k, v in counters.items()
        )
        return (
            f"### Collisions\n\n| Table | key | count |\n"
            f"|---|---|---|\n{body}\n"
        )

    def _md_timing(self) -> str:
        """Footer with timestamps, duration, and optional backup/error."""
        lines = [
            "## Timing",
            "",
            f"- **Started at**: `{self.started_at.isoformat()}`",
            f"- **Finished at**: `{self.finished_at.isoformat()}`",
            f"- **Duration**: `{self.duration_seconds:.3f}s`",
        ]
        if self.backup_path:
            lines.append(f"- **Backup**: `{self.backup_path}`")
        if self.error:
            lines.append(f"- **Error**: `{self.error}`")
        return "\n".join(lines)


# --- helpers --------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """Default encoder para tipos no estándar de JSON.

    - ``datetime`` → ISO-8601 (con offset si tiene tz).
    - ``set`` / ``frozenset`` → ``sorted(list(...))`` para reproducibilidad.
    - Cualquier otro tipo levanta ``TypeError`` explícito: un bug en el
      reporte no debe pasar como ``null`` silencioso en el JSON.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set | frozenset):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
