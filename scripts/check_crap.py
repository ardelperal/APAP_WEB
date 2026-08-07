"""Per-function CRAP score ratchet for APAP_WEB (REQ-QG-CRAP-1).

The gate combines Radon's cyclomatic complexity with line coverage from
``coverage.json`` and enforces grade A (CRAP < 6) for functions under ``app/``
and ``migration/``. Existing offenders live in ``BASELINE_CRAP`` and may only
improve; new offenders and baseline growth fail. This implements the
quality-gates-expansion design derived from Engram source observation #24073
and follows the shrink-only pattern in AGENTS.md rules 19, 21, 28, and 32.P3.
The CRITICAL_HELPERS 100% gate in ``scripts/pytest_plugin/coverage_gate.py`` is
independent and unchanged.

Usage::

    python scripts/check_crap.py [--emit-baseline] [root]

A missing ``coverage.json`` is an advisory local skip. CI runs this script in
the ``test`` job immediately after pytest-cov writes per-commit coverage data.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from radon.complexity import cc_visit
from radon.raw import analyze
from radon.visitors import Function

MAX_CRAP_GRADE = "A"
MAX_CRAP_SCORE = 6.0
SCAN_DIRS = ("app", "migration")
COVERAGE_OMIT = frozenset({"app/core/insforge.py"})


class CoverageDataError(ValueError):
    def __init__(self, path: Path) -> None:
        self.path = path

    def __str__(self) -> str:
        return f"{self.path.name}: cannot parse"


#: Current-tree offenders measured with ``--emit-baseline``.
#: RATCHET: values may only decrease and entries may only disappear.
#:
#: Re-baselined after the merge of PR #427 (auth-dependencies slice,
#: commit ``41fbd2a``): ``require_authorized_user`` moved from
#: ``app/core/auth_dependencies.py`` to its shim
#: ``app/core/di/auth_dependencies_di.py`` (issue #420-7). The stale
#: entry for the old location is removed; the new entry at
#: CRAP=14.05 (current measured value) replaces it.
#:
#: The ``migration/lock.py::`` entries for ``_is_process_alive_windows``
#: (38.28) and ``check_msaccess_running`` (12.89) are platform-dependent:
#: they reflect CI's Linux measurement where ``_is_process_alive_windows``
#: is only reached on the ``os.name == "nt"`` branch. Local Windows
#: measurements will be lower (the function is exercised there), which
#: shows up as improvement notices — not violations.
BASELINE_CRAP: dict[str, float] = {
    "app/core/di/auth_dependencies_di.py::require_authorized_user": 14.05,
    "app/core/auth_flow.py::register_auth_flow_routes.callback": 7.1,
    "app/core/csrf.py::CsrfMiddleware.dispatch": 13.33,
    "app/core/domain/auth/user.py::AuthorizedUser.from_row": 8.35,
    "app/core/insforge_error_translation.py::_classify_409_body": 10.54,
    "app/core/insforge_error_translation.py::translate_post_error": 6.04,
    "app/core/logging.py::JsonFormatter.format": 6.2,
    "app/core/logging.py::RedactionFilter.filter": 7.0,
    "app/core/middleware.py::install_auth_middleware.protect_user_facing_routes": 6.0,
    "app/core/rate_limit.py::InProcessRateLimitBackend.hit": 8.12,
    "app/core/rate_limit.py::_extract_identity": 7.02,
    "app/core/rate_limit_middleware.py::RateLimitMiddleware.dispatch": 15.16,
    "app/core/rbac.py::require_permission.checker": 13.15,
    "app/core/tasks/rules.py::rule_esterilizacion_pendiente": 9.73,
    "app/core/tasks/rules.py::rule_seguimiento_post_adopcion": 10.98,
    "app/core/tasks/scheduler.py::run_scheduler": 30.0,
    "app/modules/acogidas/routes.py::_acogida_to_form_data": 11.0,
    "app/modules/acogidas/routes.py::create_acogida_view": 7.01,
    "app/modules/acogidas/routes.py::update_acogida_view": 6.56,
    "app/modules/adopciones/queries.py::_optional_numeric": 6.02,
    "app/modules/adopciones/routes.py::_adopcion_to_form_data": 10.0,
    "app/modules/adopciones/routes.py::seguimiento_transition_view": 6.99,
    "app/modules/adopciones/service.py::_raise_validation_error": 9.49,
    "app/modules/adopciones/service.py::_row_to_adopcion": 12.0,
    "app/modules/adopciones/service.py::_validate_entrada_exists_if_present": 8.67,
    "app/modules/adopciones/service.py::transition_seguimiento": 9.21,
    "app/modules/adopciones/service.py::transition_seguimiento_for_route": 9.32,
    "app/modules/animals/chip_service.py::change_animal_chip": 8.0,
    "app/modules/animals/lifecycle_events.py::_validate_required_fields": 7.0,
    "app/modules/animals/lifecycle_events.py::validate_causal_pair": 12.01,
    "app/modules/animals/photo_service.py::resolve_animal_photo": 8.05,
    "app/modules/animals/photo_service.py::stream_animal_photo": 8.7,
    "app/modules/animals/queries.py::build_animal_count": 10.0,
    "app/modules/animals/queries.py::build_animal_search": 11.0,
    "app/modules/animals/routes.py::_animal_to_form_data": 25.0,
    "app/modules/animals/routes.py::animal_foto": 10.74,
    "app/modules/animals/routes.py::animal_salud_resumen": 8.3,
    "app/modules/animals/routes.py::change_chip_view": 7.0,
    "app/modules/animals/routes.py::create_animal_view": 13.61,
    "app/modules/animals/service.py::_validate_required_fields": 12.0,
    "app/modules/cesiones/service.py::create_cesion": 7.0,
    "app/modules/entradas/batch_routes.py::stage_batch_view": 18.0,
    "app/modules/entradas/batch_service.py::_check_cross_batch_uniqueness": 7.01,
    "app/modules/foster/assignment.py::evaluate_assignment": 9.0,
    "app/modules/foster/assignment_routes.py::asignar_submit": 10.01,
    "app/modules/foster/routes.py::_casa_to_form_data": 14.0,
    "app/modules/materiales/queries.py::build_material_update": 6.0,
    "app/modules/materiales/routes.py::update_material_view": 6.42,
    "app/modules/materiales/service.py::_is_unique_violation": 6.56,
    "app/modules/salud/service.py::delete_terapia": 6.01,
    "app/modules/sanidad/batch_routes.py::_do_batch_view": 7.01,
    "app/modules/sanidad/batch_routes.py::batch_actuaciones_view": 8.0,
    "app/modules/sanidad/batch_service.py::_validate_records_pre_flight": 7.14,
    "app/modules/sanidad/batch_service.py::commit_batch": 8.0,
    "app/modules/sanidad/batch_service.py::preview_batch": 7.0,
    "app/modules/sanidad/queries.py::build_batch_insert": 6.0,
    "app/modules/sanidad/routes.py::_actuacion_to_form_data": 6.0,
    "app/modules/sanidad/routes.py::list_actuaciones_view": 6.0,
    "app/modules/sanidad/routes.py::update_actuacion_view": 17.13,
    "app/modules/sanidad/service.py::_raise_validation_error": 14.51,
    "app/modules/tasks/rules.py::rule_esterilizacion_pendiente": 56.0,
    "app/modules/tasks/rules.py::rule_seguimiento_post_adopcion": 132.0,
    "app/modules/tasks/rules.py::rule_vacuna_vencimiento": 20.0,
    "app/modules/tasks/service.py::_row_to_tarea": 9.0,
    "app/modules/tasks/service.py::cerrar_tarea": 6.07,
    "app/modules/tasks/service.py::crear_tarea": 7.0,
    "app/modules/voluntarios/service.py::_validate_create_params": 6.0,
    "migration/apply.py::_apply_one_row": 8.05,
    "migration/apply.py::_insert_web_row": 6.04,
    "migration/apply.py::apply_legacy_to_web": 20.65,
    "migration/cli.py::_run_reconcile_interactive": 13.78,
    "migration/cli.py::main": 8.01,
    "migration/cli.py::run_ensure_bucket": 10.37,
    "migration/cli.py::run_reconcile": 12.08,
    "migration/cli.py::run_status": 6.35,
    "migration/cli_apply_reverse.py::run_apply": 21.15,
    "migration/cli_volunteer_dedup.py::_format_summary": 7.0,
    "migration/cli_volunteer_dedup.py::_parse_input": 12.67,
    "migration/cli_volunteer_dedup.py::run_volunteer_dedup": 10.74,
    "migration/derivation.py::_resolve_pre_death_state": 8.23,
    "migration/derivation.py::compare_derived_to_stored": 6.0,
    "migration/derivation.py::derive_estado_actual_animal": 34.03,
    "migration/diff_engine.py::_diff_snapshots": 29.08,
    "migration/diff_engine.py::_find_target_row": 9.06,
    "migration/diff_engine.py::_index_target": 7.01,
    "migration/diff_engine.py::_is_modified_both_sides": 6.01,
    "migration/diff_engine.py::_iter_comparable_pairs": 19.39,
    "migration/diff_engine.py::_parse_datetime": 16.73,
    "migration/diff_engine.py::_values_equal": 26.12,
    "migration/legacy_access_client.py::_get_pyodbc": 6.0,
    "migration/legacy_access_client.py::execute_legacy_sql": 11.38,
    "migration/legacy_access_client.py::execute_legacy_write": 10.98,
    "migration/legacy_reader.py::load_legacy_snapshot_batched": 6.01,
    "migration/lock.py::LockInfo.from_json": 7.39,
    "migration/lock.py::_is_process_alive": 20.27,
    "migration/lock.py::_is_process_alive_windows": 38.28,
    "migration/lock.py::check_msaccess_running": 12.89,
    "migration/lock_snapshot.py::Snapshot.from_json": 6.4,
    "migration/lock_snapshot.py::compute_photos_dir_hash": 8.23,
    "migration/lock_snapshot.py::write_partial_apply": 7.58,
    "migration/reconcile.py::_build_derived_inputs": 42.68,
    "migration/reconcile.py::_reconcile_column": 11.17,
    "migration/reconcile.py::_resolve_animal_id": 6.56,
    "migration/reconcile.py::post_apply_diff": 19.5,
    "migration/reporting.py::MigrationReport.to_markdown": 50.43,
    "migration/reverse_apply/io_helpers.py::_case_insensitive_get": 7.01,
    "migration/reverse_apply/lifecycle.py::_emit_reversed_lifecycle_events_for_changed_derived": 14.34,
    "migration/reverse_apply/orchestrator.py::_load_legacy_snapshot": 6.01,
    "migration/reverse_apply/orchestrator.py::_process_per_row_loop": 6.0,
    "migration/reverse_apply/orchestrator.py::_rollback_sync_state_if_dirty": 7.35,
    "migration/reverse_apply/orchestrator.py::apply_web_to_legacy": 14.0,
    "migration/reverse_apply/per_row.py::_insert_legacy_row": 7.05,
    "migration/reverse_apply/per_row.py::_reverse_apply_one_row": 11.0,
    "migration/reverse_apply/per_row.py::_update_legacy_row": 7.05,
    "migration/semantic_events.py::_read_timestamp": 9.32,
    "migration/semantic_events.py::_translate_insert": 7.08,
    "migration/shadow_state.py::ShadowStateRepository.list_needs_review": 7.01,
    "migration/storage_spike.py::_body_shape": 6.0,
    "migration/storage_spike.py::_resolve_auth_behavior": 14.18,
    "migration/storage_spike.py::_status_from_code": 6.02,
    "migration/storage_spike.py::_type_name": 10.86,
    "migration/storage_spike.py::main": 6.0,
    "migration/storage_spike.py::probe_download_strategy": 10.36,
    "migration/storage_spike.py::write_discovery_document": 7.0,
    "migration/sync_state.py::_sync_state_from_raw": 12.2,
    "migration/volunteer_dedup.py::MergedCluster.__post_init__": 13.62,
    "migration/volunteer_dedup.py::VolunteerRef.__post_init__": 16.11,
    "migration/volunteer_dedup.py::_cluster_decision": 11.0,
    "migration/volunteer_dedup.py::dedup_volunteers": 14.0,
}


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(
            path for path in base.rglob("*.py") if "__pycache__" not in path.parts
        )
    return sorted(files)


def _function_blocks(source: str) -> list[tuple[str, Function]]:
    functions: list[tuple[str, Function]] = []

    def add(block: Function, qualname: str) -> None:
        functions.append((qualname, block))
        for closure in block.closures:
            add(closure, f"{qualname}.{closure.name}")

    for block in cc_visit(source):
        if isinstance(block, Function):
            add(block, block.fullname)
    return functions


def _load_coverage(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise CoverageDataError(path) from None
    files = payload.get("files")
    if not isinstance(files, dict):
        raise CoverageDataError(path)
    return files


def _coverage_record(files: Mapping[str, Any], rel: str) -> Mapping[str, Any] | None:
    normalized_rel = rel.replace("\\", "/")
    for raw_key, value in files.items():
        normalized_key = str(raw_key).replace("\\", "/")
        if normalized_key == normalized_rel or normalized_key.endswith(
            f"/{normalized_rel}"
        ):
            return value if isinstance(value, Mapping) else None
    return None


def _crap_score(
    complexity: int,
    start_line: int,
    end_line: int,
    coverage: Mapping[str, Any] | None,
) -> float:
    if coverage is None:
        coverage_fraction = 0.0
    else:
        executed = {
            int(line)
            for line in coverage.get("executed_lines", [])
            if isinstance(line, int)
        }
        missing = {
            int(line)
            for line in coverage.get("missing_lines", [])
            if isinstance(line, int)
        }
        relevant = {
            line for line in executed | missing if start_line <= line <= end_line
        }
        coverage_fraction = (
            len(executed & relevant) / len(relevant) if relevant else 1.0
        )
    score = complexity**2 * (1.0 - coverage_fraction) ** 3 + complexity
    return round(score, 2)


def measure_tree(
    root: Path,
    *,
    coverage_path: Path | None = None,
) -> dict[str, float]:
    """Return ``file::qualname -> CRAP`` for every scanned function."""
    coverage_file = coverage_path or root / "coverage.json"
    coverage_files = _load_coverage(coverage_file)
    measured: dict[str, float] = {}

    for path in _iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in COVERAGE_OMIT:
            continue
        source = path.read_text(encoding="utf-8")
        if analyze(source).loc == 0:
            continue
        record = _coverage_record(coverage_files, rel)
        # Coverage.py omits explicitly excluded adapters from the files map.
        # Without line data CRAP is undefined, so excluded files are not
        # measured rather than being misclassified as 0% covered.
        if record is None:
            continue
        for qualname, block in _function_blocks(source):
            key = f"{rel}::{qualname}"
            measured[key] = _crap_score(
                block.complexity,
                block.lineno,
                block.endline,
                record,
            )
    return dict(sorted(measured.items()))


def _check_measured_scores(
    measured: Mapping[str, float],
    baseline: Mapping[str, float],
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    notices: list[str] = []
    for key, score in measured.items():
        if key in baseline:
            budget = baseline[key]
            if score > budget:
                violations.append(
                    f"{key}: CRAP={score:.2f}, grew beyond its baseline of "
                    f"{budget:.2f} (ratchet: CRAP may only decrease)"
                )
            elif score < budget:
                notices.append(
                    f"{key}: CRAP={score:.2f}, below its baseline of {budget:.2f} — "
                    "update BASELINE_CRAP to lock in the improvement"
                )
        elif score >= MAX_CRAP_SCORE:
            violations.append(
                f"{key}: CRAP={score:.2f}, outside grade {MAX_CRAP_GRADE} "
                f"(requires CRAP < {MAX_CRAP_SCORE:g})"
            )
    return violations, notices


def _check_stale_baseline(
    coverage_files: Mapping[str, Any],
    measured: Mapping[str, float],
    baseline: Mapping[str, float],
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    notices: list[str] = []
    for key in sorted(set(baseline) - set(measured)):
        rel = key.split("::", 1)[0]
        if _coverage_record(coverage_files, rel) is None:
            notices.append(
                f"{key}: no coverage record; CRAP baseline not evaluated"
            )
        else:
            violations.append(
                f"{key}: stale BASELINE_CRAP entry — function no longer exists"
            )
    return violations, notices


def check_tree(
    root: Path,
    *,
    baseline: Mapping[str, float] | None = None,
    coverage_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(violations, notices)`` for the scanned tree."""
    if baseline is None:
        baseline = BASELINE_CRAP
    coverage_file = coverage_path or root / "coverage.json"
    if not coverage_file.is_file():
        return [], [
            "coverage.json missing — CRAP check skipped (run pytest --cov first)"
        ]
    try:
        coverage_files = _load_coverage(coverage_file)
        measured = measure_tree(root, coverage_path=coverage_file)
    except (OSError, UnicodeDecodeError, SyntaxError, TypeError, ValueError) as exc:
        return [str(exc)], []

    violations, notices = _check_measured_scores(measured, baseline)
    stale_violations, stale_notices = _check_stale_baseline(
        coverage_files,
        measured,
        baseline,
    )
    return violations + stale_violations, notices + stale_notices


def _emit_baseline(root: Path) -> int:
    coverage_file = root / "coverage.json"
    if not coverage_file.is_file():
        print("NOTE: coverage.json missing — CRAP check skipped (run pytest --cov first)")
        return 0
    try:
        measured = measure_tree(root, coverage_path=coverage_file)
    except (OSError, UnicodeDecodeError, SyntaxError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    offenders = {
        key: score for key, score in measured.items() if score >= MAX_CRAP_SCORE
    }
    rendered = json.dumps(offenders, indent=4, sort_keys=True)
    print(f"BASELINE_CRAP: dict[str, float] = {rendered}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-baseline", action="store_true")
    parser.add_argument("root", nargs="?", type=Path)
    args = parser.parse_args(argv)
    root = (
        args.root.resolve()
        if args.root is not None
        else Path(__file__).resolve().parents[1]
    )
    if args.emit_baseline:
        return _emit_baseline(root)

    violations, notices = check_tree(root)
    for notice in notices:
        print(f"NOTE: {notice}")
    for violation in violations:
        print(f"FAIL: {violation}")
    if violations:
        print(
            f"check_crap: {len(violations)} violation(s); "
            f"required grade {MAX_CRAP_GRADE} (CRAP < {MAX_CRAP_SCORE:g})."
        )
        return 1
    if not notices:
        print("check_crap: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
