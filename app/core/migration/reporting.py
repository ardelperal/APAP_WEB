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
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

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
        - Footer con timestamps y duración.
        """
        lines: list[str] = []
        lines.append("# Migration Report")
        lines.append("")
        lines.append(f"- **Direction**: `{self.direction}`")
        lines.append(f"- **Mode**: `{self.mode}`")
        lines.append(f"- **Dry run**: `{self.dry_run}`")
        lines.append(f"- **Applied**: `{self.applied}`")
        lines.append("")

        # Metrics
        ins = sum(1 for d in self.diffs if d.op == "INSERT")
        upd = sum(1 for d in self.diffs if d.op == "UPDATE")
        dele = sum(1 for d in self.diffs if d.op == "DELETE")
        noop = sum(1 for d in self.diffs if d.op == "NOOP")
        total = ins + upd + dele + noop
        lines.append("## Metrics")
        lines.append("")
        lines.append("| Op | Count |")
        lines.append("|---|---|")
        lines.append(f"| INSERT | {ins} |")
        lines.append(f"| UPDATE | {upd} |")
        lines.append(f"| DELETE | {dele} |")
        lines.append(f"| NOOP | {noop} |")
        lines.append(f"| Conflict | {len(self.conflicts)} |")
        lines.append(f"| Total | {total} |")
        lines.append("")

        # Conflicts table (only if any)
        if self.conflicts:
            lines.append("## Conflicts")
            lines.append("")
            lines.append("| Table | Key | Reason |")
            lines.append("|---|---|---|")
            for c in self.conflicts:
                lines.append(f"| {c.table} | {c.key} | {c.reason} |")
            lines.append("")

        # Footer
        lines.append("## Timing")
        lines.append("")
        lines.append(f"- **Started at**: `{self.started_at.isoformat()}`")
        lines.append(f"- **Finished at**: `{self.finished_at.isoformat()}`")
        lines.append(f"- **Duration**: `{self.duration_seconds:.3f}s`")
        if self.backup_path:
            lines.append(f"- **Backup**: `{self.backup_path}`")
        if self.error:
            lines.append(f"- **Error**: `{self.error}`")

        return "\n".join(lines) + "\n"


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
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
