"""Scheduler for the task engine rule engine (issue #7).

For the first MVC this is a manual CLI command:
  python -m app.core.tasks.scheduler

The scheduler:
  1. Runs all registered rules in TASK_RULES
  2. Deduplicates drafts against existing open tareas (same vinculo + tipo)
  3. Persists new drafts via crear_tarea

Future iterations (post-MVP):
  - Wire to a cron job or background task runner
  - Add scheduling cadence configuration per rule
  - Add dry-run flag
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Project root for python -m invocation
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def run_scheduler() -> None:
    """Run all task rules and persist new tareas.

    This is the CLI entry point for the first MVC.
    Future versions will integrate with a cron scheduler.
    """
    # lazy-import: avoids circular import with app.core.config (settings
    # is heavy and this function is CLI-only).
    from app.core.config import get_settings  # lazy-import: avoids circular
    from app.core.insforge import InsForgeClient  # lazy-import: avoids circular
    from app.core.logging import log_safe  # lazy-import: CLI-only
    from app.core.tasks.rules import TASK_RULES  # lazy-import: avoids circular
    from app.modules.tasks import service as tareas_service  # lazy-import: CLI-only

    settings = get_settings()
    client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
    try:
        # Context is empty in the first MVC — rules are driven by domain queries.
        # The scheduler would query vaccines, adoptions, animals, etc. here.
        # For now, rules are stubs that need domain context passed in.
        context: dict = {}

        nuevos = 0
        for _rule_name, rule_fn in TASK_RULES.items():
            drafts = rule_fn(context)
            for draft in drafts:
                # Deduplicate: skip if an open tarea exists for same vinculo+tipo
                existing = tareas_service.listar_tareas(
                    client=client,
                    estado="pendiente",
                    vinculo_tipo=draft.vinculo_tipo,
                    vinculo_id=draft.vinculo_id,
                    limit=1,
                )
                if not existing:
                    existing = tareas_service.listar_tareas(
                        client=client,
                        estado="en_progreso",
                        vinculo_tipo=draft.vinculo_tipo,
                        vinculo_id=draft.vinculo_id,
                        limit=1,
                    )
                if existing:
                    continue  # already exists, skip

                tareas_service.crear_tarea(
                    client=client,
                    tipo=draft.tipo,
                    origen=draft.origen,
                    prioridad=draft.prioridad,
                    vencimiento_at=draft.vencimiento_at,
                    vinculo_tipo=draft.vinculo_tipo,
                    vinculo_id=draft.vinculo_id,
                    metadata=draft.metadata,
                )
                nuevos += 1

        log_safe("scheduler.run_complete", nuevos=nuevos)
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the task-engine rule scheduler."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without persisting",
    )
    args = parser.parse_args()

    from app.core.logging import log_safe  # lazy-import: CLI-only

    if args.dry_run:
        log_safe("scheduler.dry_run_start")
        # In a future iteration, dry-run would print drafts without persisting.
        log_safe("scheduler.dry_run_not_implemented")
    else:
        run_scheduler()
