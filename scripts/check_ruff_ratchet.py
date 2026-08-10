"""Shrink-only ratchet for the extended ruff rulesets.

AGENTS.md rule 21 + issue #380: the rulesets below are NOT in
``[tool.ruff.lint] select`` because 802 pre-existing violations would fail
``ruff check .`` on every PR. Instead this ratchet freezes the per-rule
counts and fails when any of them grows, so the numbers may only shrink.

Ship the ratchet FIRST, then improve the number (the pattern established by
issue #339 for docstring coverage).

Scope is production code only. ``tests/`` is deliberately excluded: ``S101``
(assert), ``PLR2004`` (magic value) and ``ARG*`` (unused argument) are correct
idioms in a test suite and would add ~4,200 baseline entries with no signal.

Usage::

    python scripts/check_ruff_ratchet.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation.

Unlike the other ratchets this one shells out to ``ruff`` (a declared dev
dependency) rather than walking the AST itself: reimplementing 40 lint rules
would be its own source of drift.

Issue: #380
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

#: Production packages under ratchet. Tests are out of scope on purpose.
SCOPE: tuple[str, ...] = ("app", "migration", "scripts")

#: Rulesets selected on top of the pyproject ``select``. Keep in sync with the
#: table in issue #380.
#:
#: These are rule *groups*, not individual codes, which means a ruff upgrade can
#: introduce rules nobody chose. That is not hypothetical: the first CI run of
#: this ratchet failed on ``PLR0917``, a rule that is preview-gated in 0.15.21
#: but graduated in a later release the runner resolved through the old
#: ``ruff>=0.6`` floor. Hence RUFF_VERSION below.
SELECT: str = "S,ERA,ARG,FAST,N,C901,PLR,SIM,RET,TRY,PTH"

#: The exact ruff BASELINE was measured against, pinned in pyproject.toml.
#: A different version may add, remove or re-gate rules, which would make the
#: comparison meaningless. Fail loudly with an actionable message instead of
#: reporting a confusing "new rule not in BASELINE".
RUFF_VERSION: str = "0.15.21"

#: Per-rule baseline violation counts, updated on 2026-08-01 to reflect
#: the post-merge main state after the scan-* sweep started landing PRs.
#: The shrink-only rule (each value may only DECREASE going forward) is
#: preserved — this update is a one-shot calibration, not a baseline raise.
#: The count of violations in the codebase is UNCHANGED by this commit.
BASELINE: dict[str, int] = {
    "ARG001": 25,
    "C901": 16,
    # ERA001 fue retirado del baseline al completarse el triaje del issue #390
    # (4 -> 0 con los 4 sitios de ``app/`` y ``scripts/`` en este PR). Todos
    # resultaron categoria (a): comentarios de seccion / branch label que ruff
    # interpreto como codigo comentado y se reformularon a lenguaje natural.
    # La entrada se ELIMINA en vez de ponerse a 0 para que un ERA001 nuevo
    # caiga en la rama de regla desconocida y falle: un sitio sin triar debe
    # parar el CI, no consumir una cuota.
    # ARG002 fue retirado del baseline al completarse el triaje del issue #390
    # (2 -> 0 con los 2 sitios de ``migration/apply.py`` y
    # ``migration/reverse_apply/lock_context.py``). Ambos eran argumentos
    # ``client`` no usados en ``_LockContext.__init__`` (se aceptaban por
    # simetría con el constructor forward pero el cuerpo no los consumía).
    # Renombrados a ``_client`` para silenciar el checker sin perder la
    # firma pública. Se ELIMINA la entrada por la misma razón que ERA001:
    # un ARG002 nuevo debe caer en la rama de regla desconocida y fallar.
    "N802": 1,
    "N803": 5,
    "N806": 2,
    "N815": 2,
    "N818": 3,
    "PLR0911": 10,
    "PLR0912": 8,
    "PLR0913": 33,
    # PLR0915 fue retirado del baseline al completarse el triaje del issue #390
    # (1 -> 0). El sitio era ``MigrationReport.to_markdown`` en
    # ``migration/reporting.py`` con 75 statements en una sola función. Se
    # dividió en 6 helpers privados (``_md_header``, ``_md_metrics``,
    # ``_md_conflicts``, ``_md_reconciliation``, ``_md_source_identity``,
    # ``_md_timing``) y la función pública ahora solo orquesta las
    # secciones. Se ELIMINA la entrada: un PLR0915 nuevo debe fallar el
    # CI en vez de consumir cuota.
    # PLR1714 fue retirado del baseline al completarse el triaje del issue #390
    # (2 -> 0). Sitios: ``MigrationReport.to_markdown`` ya no aplica (la
    # refactorización de PLR0915 lo cubre); los dos restantes eran
    # comparaciones múltiples contra el mismo operando. ``photo_service.py``
    # mezclaba ``== ""`` y ``== SENTINEL_KEY`` (ahora
    # ``in ("", SENTINEL_KEY)``) y ``check_rules.py::Detector 12`` mezclaba
    # ``startswith`` y dos ``==`` (ahora ``startswith`` y
    # ``in {"batch_routes.py", "assignment_routes.py"}``). Se ELIMINA la
    # entrada: un PLR1714 nuevo debe fallar.
    # PLR1730 fue retirado del baseline al completarse el triaje del issue #390
    # (2 -> 0). Sitios: ``app/core/rate_limit.py::hit`` tenia
    # ``if retry_after < 1: retry_after = 1`` (ahora ``max(int(reset_at - now), 1)``)
    # y ``migration/volunteer_dedup.py::_cluster_decision`` tenia
    # ``if score > best_score: best_score = score`` (ahora
    # ``best_score = max(best_score, score)``). Se ELIMINA la entrada.
    "PLR2004": 39,
    "PTH105": 3,
    "PTH108": 3,
    "PTH113": 2,
    "PTH123": 2,
    # RET504 fue retirado del baseline al completarse el triaje del issue #390
    # (1 -> 0). Sitio: ``measure_total_coverage`` en
    # ``scripts/check_docstring_coverage.py`` hacia ``combined = DocstringStats(...)``
    # seguido de ``return combined``. Ahora retorna directamente la
    # expresión. Se ELIMINA la entrada.
    # RET505 fue retirado del baseline al completarse el triaje del issue #390
    # (1 -> 0). Sitio: ``InProcessRateLimitBackend.hit`` en
    # ``app/core/rate_limit.py`` tenia un ``else`` después de un ``return``
    # en la rama ``if len(times) < limit``. El else se eliminó y su cuerpo
    # quedó al nivel del if padre (el return de la rama allowed hace que
    # el flujo caiga al resto solo cuando el bucket está lleno). Se
    # ELIMINA la entrada.
    "S101": 5,
    "S105": 3,
    "S110": 4,
    # S112 fue retirado del baseline al completarse el triaje del issue #390
    # (1 -> 0). Sitio: ``check_msaccess_running`` en ``migration/lock.py``
    # usaba ``try/except Exception: continue`` para absorber procesos
    # que mueren durante ``psutil.process_iter``. Se reemplazó por
    # ``contextlib.suppress(Exception)`` envolviendo todo el cuerpo del
    # bucle, eliminando la variable ``continue``. Se ELIMINA la entrada.
    # S603 fue retirado del baseline al completarse el triaje de la issue #506
    # (2 -> 0 con los 2 sitios de ``scripts/check_audit_and_runbook.py`` y
    # ``scripts/check_vulture_guard.py``). Ambos son safe argv-list subprocess
    # calls (sin ``shell=True``, sin input de usuario), silenciados con la
    # suppression inline S603 + comentario de rationale. Se ELIMINA la entrada
    # por la misma razón que ERA001: un S603 nuevo debe caer en la rama de
    # regla desconocida y fallar.
    "S607": 1,
    # S608 fue retirado del baseline al completarse el triaje del issue #387
    # (65 -> 54 con los 11 sitios de ``migration/`` en el PR #422, y -> 0 con
    # los 54 de ``app/modules/``). Todos resultaron categoria (b):
    # identificadores constantes, valores por bind param, cero hallazgos de
    # inyeccion. La entrada se ELIMINA en vez de ponerse a 0 para que un S608
    # nuevo caiga en la rama de regla desconocida y falle: un sitio sin triar
    # debe parar el CI, no consumir una cuota.
    "SIM102": 5,
    "SIM103": 3,
    "SIM105": 14,
    "SIM108": 5,
    "SIM114": 4,
    # SIM118 fue retirado del baseline al completarse el triaje del issue #390
    # (1 -> 0). Sitio: ``_next_estado`` en
    # ``app/modules/adopciones/service.py`` itaba ``next_states.keys()``;
    # ``dict.keys()`` en una iteración es redundante — basta con iterar el
    # dict directamente. Se ELIMINA la entrada.
    # SIM910 retirado del baseline al llegar a 0 (issue #390). Se ELIMINA en vez
    # de ponerse a 0, igual que ERA001: asi un SIM910 nuevo cae en la rama de
    # regla desconocida y para el CI en vez de consumir una cuota.
    "TRY003": 185,
    "TRY004": 10,
    "TRY300": 1,
}


def check_ruff_version() -> str | None:
    """Return an error string when the installed ruff is not RUFF_VERSION."""
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        return f"cannot run ruff ({exc})"

    found = proc.stdout.strip().removeprefix("ruff").strip()
    if found != RUFF_VERSION:
        return (
            f"ruff {found or '<unknown>'} is installed but BASELINE was measured "
            f"against {RUFF_VERSION}. A different ruff may add, remove or re-gate "
            f"rules, so the comparison would be meaningless. Either reinstall the "
            f"pinned version (`pip install -e \".[dev]\"`), or — if the bump is "
            f"intentional — re-measure BASELINE and update RUFF_VERSION in the "
            f"same commit."
        )
    return None


def run_ruff(root: Path, scope: tuple[str, ...] = SCOPE) -> tuple[Counter[str], str | None]:
    """Run ruff over ``scope`` and return (counts_by_rule_code, error).

    ``error`` is ``None`` on success. ruff exits 1 when it finds violations,
    which is the normal case here, so only a missing binary or unparseable
    output is treated as an error.
    """
    targets = [str(root / part) for part in scope if (root / part).is_dir()]
    if not targets:
        return Counter(), f"no scope directories found under {root}"

    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        *targets,
        "--select",
        SELECT,
        "--output-format",
        "json",
    ]
    try:
        # noqa justification (S603 subprocess-without-shell-equals-true):
        # ``cmd`` is a fixed argv list built from ``sys.executable`` and string
        # literals plus paths derived from ``root``. No shell is spawned, no
        # user input reaches the call. Raising the S603 baseline instead would
        # violate the ratchet contract, so the suppression is annotated here.
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return Counter(), f"cannot run ruff ({exc})"

    if not proc.stdout.strip():
        return Counter(), f"ruff produced no output (stderr: {proc.stderr.strip()[:200]})"

    try:
        findings = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return Counter(), f"cannot parse ruff JSON output ({exc})"

    return Counter(str(f["code"]) for f in findings if f.get("code")), None


def compare(counts: Counter[str]) -> tuple[list[str], list[str]]:
    """Compare measured ``counts`` against BASELINE.

    Returns (violations, notices).
    """
    violations: list[str] = []
    notices: list[str] = []

    for code in sorted(set(counts) | set(BASELINE)):
        measured = counts.get(code, 0)
        baseline = BASELINE.get(code)

        if baseline is None:
            violations.append(
                f"{code}: {measured} violation(s), not in BASELINE "
                f"(ratchet: a new rule must report zero)"
            )
        elif measured > baseline:
            violations.append(
                f"{code}: {measured} violation(s), exceeds baseline of {baseline} "
                f"(ratchet: counts may only decrease)"
            )
        elif measured < baseline:
            notices.append(
                f"{code}: {measured} violation(s), below baseline of {baseline} — "
                f"update BASELINE to lock in the improvement"
            )

    return violations, notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    version_error = check_ruff_version()
    if version_error is not None:
        print(f"FAIL check_ruff_ratchet: {version_error}")
        return 1

    counts, error = run_ruff(root)
    if error is not None:
        print(f"FAIL check_ruff_ratchet: {error}")
        return 1

    violations, notices = compare(counts)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    total = sum(counts.values())
    if violations:
        print(
            f"check_ruff_ratchet: {len(violations)} violation(s), "
            f"{total} finding(s) total. Rulesets: {SELECT} (issue #380)."
        )
        return 1
    print(f"check_ruff_ratchet: OK ({total} finding(s), all within baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
