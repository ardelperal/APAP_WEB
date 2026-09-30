"""Tests for the extended-ruff shrink-only ratchet.

Issue #380: the extended rulesets are not in ``[tool.ruff.lint] select``
because 802 pre-existing violations would fail ``ruff check .``. The ratchet
freezes the per-rule counts so they may only shrink. These tests cover:

1. Behavioural: ``compare()`` fails on an increase and on an unknown rule.
2. Behavioural: ``compare()`` reports an improvement without failing.
3. Integration: the ratchet passes against the real tree.
4. Wiring: the CI ``lint`` job runs the gate.
5. Lock-in: ``update_baseline()`` (``--update-baseline``) lowers the BASELINE
   to the measured counts, refuses to raise anything, and never mutates the
   committed script when it refuses (issue #1120).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_ruff_ratchet import (  # noqa: E402
    BASELINE,
    SCOPE,
    SELECT,
    UpdateRefusedError,
    compare,
    load_baseline,
    main,
    run_ruff,
    update_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_baseline_is_non_empty_and_positive() -> None:
    """Every baseline entry must be a positive count.

    A zero entry is meaningless: a rule with no violations should simply be
    absent, so that any future violation trips the unknown-rule branch.
    """
    assert BASELINE, "BASELINE must not be empty"
    zero_or_negative = {code: n for code, n in BASELINE.items() if n <= 0}
    assert not zero_or_negative, (
        f"BASELINE entries must be positive; remove these instead: {zero_or_negative}"
    )


def test_compare_is_clean_when_counts_match_baseline() -> None:
    """Measuring exactly the baseline is the steady state — no output."""
    violations, notices = compare(Counter(BASELINE))
    assert violations == []
    assert notices == []


def test_compare_fails_when_a_count_increases() -> None:
    """One extra violation of a tracked rule must fail the ratchet."""
    counts = Counter(BASELINE)
    counts["ARG001"] += 1

    violations, _ = compare(counts)

    assert len(violations) == 1
    assert "ARG001" in violations[0]
    assert "may only decrease" in violations[0]


def test_compare_fails_on_a_rule_absent_from_baseline() -> None:
    """A rule with no baseline entry must report zero, not creep in silently."""
    counts = Counter(BASELINE)
    counts["S602"] = 1

    violations, _ = compare(counts)

    assert len(violations) == 1
    assert "S602" in violations[0]
    assert "not in BASELINE" in violations[0]


def test_compare_notices_an_improvement_without_failing() -> None:
    """Dropping below baseline is a NOTE, so the win can be locked in."""
    counts = Counter(BASELINE)
    counts["ARG001"] -= 10

    violations, notices = compare(counts)

    assert violations == []
    assert len(notices) == 1
    assert "below baseline" in notices[0]
    assert "lock in the improvement" in notices[0]


def test_compare_treats_a_rule_dropping_to_zero_as_an_improvement() -> None:
    """A tracked rule reaching zero is an improvement, not an error.

    ERA001 was retired in PR resolving issue #390 (4 -> 0 offenders).
    The test now exercises the same scenario with ARG001, the largest
    remaining baseline, so the behaviour stays under test.
    """
    counts = Counter(BASELINE)
    del counts["ARG001"]

    violations, notices = compare(counts)

    assert violations == []
    assert any("ARG001" in n for n in notices)


def test_run_ruff_reports_an_error_for_a_missing_scope() -> None:
    """A root with no scope directories is an error, not a silent zero.

    Without this branch a mis-invoked ratchet would report "OK, 0 findings"
    and pass CI while checking nothing.
    """
    counts, error = run_ruff(REPO_ROOT / "does-not-exist", scope=SCOPE)

    assert counts == Counter()
    assert error is not None
    assert "no scope directories" in error


def test_ratchet_passes_against_the_real_tree() -> None:
    """The committed BASELINE must match the tree it was measured against."""
    assert main([str(REPO_ROOT)]) == 0


def test_select_covers_the_documented_rulesets() -> None:
    """The select string is the contract with issue #380 — pin it."""
    for ruleset in ("S", "ERA", "ARG", "FAST", "N", "C901", "PLR", "SIM", "RET", "TRY", "PTH"):
        assert ruleset in SELECT.split(","), f"{ruleset} missing from SELECT"


def test_existing_ruff_gate_still_passes() -> None:
    """``ruff check .`` must stay green — this issue adds a gate, not noise.

    The extended rulesets deliberately live in the ratchet rather than in
    ``select``, so the pre-existing lint step is unaffected.
    """
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"ruff check . regressed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(not WORKFLOW_PATH.exists(), reason="ci.yml not present")
def test_ci_workflow_lint_job_runs_ruff_ratchet_gate() -> None:
    """The CI ``lint`` job must gate on ``scripts/check_ruff_ratchet.py``.

    Issue #380: removing this step from ci.yml is a blocked change.
    The ratchet is only real if CI runs it.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  typecheck:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_ruff_ratchet.py" in executable, (
        "The lint job must run the extended-ruff ratchet "
        "(python scripts/check_ruff_ratchet.py) so the rulesets are "
        "enforced in CI, not just at PR review time."
    )


def test_ruff_version_matches_the_measured_baseline() -> None:
    """BASELINE is only meaningful against the ruff it was measured with.

    Issue #380: the first CI run failed on `PLR0917`, a rule preview-gated in
    0.15.21 that had graduated in the newer ruff the runner resolved through
    the old `ruff>=0.6` floor. The floor is now an exact pin and this asserts
    it, so a bump fails with an actionable message instead of a confusing
    "new rule not in BASELINE".
    """
    from check_ruff_ratchet import RUFF_VERSION, check_ruff_version

    assert check_ruff_version() is None, (
        f"installed ruff differs from the pinned {RUFF_VERSION}"
    )


def test_pyproject_pins_ruff_exactly() -> None:
    """An open version floor is not a deterministic gate."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    from check_ruff_ratchet import RUFF_VERSION

    assert f'"ruff=={RUFF_VERSION}"' in text, (
        "pyproject must pin ruff exactly, and to the version BASELINE was measured with"
    )
    assert '"ruff>=' not in text, "ruff must not be declared with an open floor"


# ---------------------------------------------------------------------------
# Lock-in: ``--update-baseline`` (issue #1120).
#
# The tests run against tmp copies of the real script so a failing or
# refused update can never mutate the committed BASELINE.
# ---------------------------------------------------------------------------

SCRIPT_PATH = REPO_ROOT / "scripts" / "check_ruff_ratchet.py"


def _copy_script(tmp_path: Path, *, inflate_by: int = 0) -> Path:
    """Copy the real script into ``tmp_path``, optionally inflating BASELINE.

    With ``inflate_by > 0`` every tracked entry sits above its real count,
    mimicking the simulated-baseline-above-real-counts setup the issue's
    plan de validación calls for.
    """
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    if inflate_by:
        source = re.sub(
            r'"([A-Z]+\d+)": (\d+)',
            lambda m: f'"{m.group(1)}": {int(m.group(2)) + inflate_by}',
            source,
        )
    tmp_script = tmp_path / "check_ruff_ratchet.py"
    tmp_script.write_text(source, encoding="utf-8")
    return tmp_script


def test_update_baseline_lowers_each_entry_to_measured_count(tmp_path: Path) -> None:
    """A simulated baseline above real counts is lowered to exactly them.

    Issue #1120 RED: with every entry inflated by 5 and the real counts as
    ground truth, the update must persist exactly the measured counts and
    report a non-empty diff mentioning every lowered rule.
    """
    tmp_script = _copy_script(tmp_path, inflate_by=5)
    inflated = load_baseline(tmp_script)
    real_counts = Counter({code: value - 5 for code, value in inflated.items()})

    new_baseline, diff_lines = update_baseline(tmp_script, real_counts)

    assert new_baseline == dict(real_counts)
    assert diff_lines
    for code in inflated:
        assert any(code in line for line in diff_lines), code
    assert load_baseline(tmp_script) == dict(real_counts)
    # Idempotence: re-running the lock-in at the measured counts is a no-op.
    assert update_baseline(tmp_script, real_counts) == (dict(real_counts), [])


def test_update_baseline_refuses_to_raise_and_leaves_file_byte_identical(
    tmp_path: Path,
) -> None:
    """A single raise aborts the whole update atomically.

    Even when every other entry could be lowered, one raise must refuse
    the update and leave the script byte-identical: shrink-only means the
    lock-in can never raise a baseline entry.
    """
    tmp_script = _copy_script(tmp_path, inflate_by=5)
    inflated = load_baseline(tmp_script)
    counts = Counter({code: value - 5 for code, value in inflated.items()})
    counts["C901"] = inflated["C901"] + 1
    original = tmp_script.read_text(encoding="utf-8")

    with pytest.raises(UpdateRefusedError) as exc_info:
        update_baseline(tmp_script, counts)

    assert "C901" in str(exc_info.value)
    assert tmp_script.read_text(encoding="utf-8") == original


def test_update_baseline_refuses_unknown_rule(tmp_path: Path) -> None:
    """A measured rule missing from BASELINE refuses the update.

    compare() fails loud on a rule that is not in BASELINE ("a new rule
    must report zero"), so the lock-in must not silently persist a
    baseline while the gate itself would be red.
    """
    tmp_script = _copy_script(tmp_path)
    counts = Counter(load_baseline(tmp_script))
    counts["XYZ999"] = 3
    original = tmp_script.read_text(encoding="utf-8")

    with pytest.raises(UpdateRefusedError) as exc_info:
        update_baseline(tmp_script, counts)

    assert "XYZ999" in str(exc_info.value)
    assert tmp_script.read_text(encoding="utf-8") == original


def test_update_baseline_removes_zero_count_entries(tmp_path: Path) -> None:
    """A rule whose measured count reaches zero is removed from BASELINE.

    Issue #390 convention: no 0-valued entries, so a future violation
    trips the unknown-rule branch instead of consuming a 0 quota.
    """
    tmp_script = _copy_script(tmp_path)
    counts = Counter(load_baseline(tmp_script))
    counts["ARG001"] = 0

    new_baseline, diff_lines = update_baseline(tmp_script, counts)

    assert "ARG001" not in new_baseline
    assert any("ARG001" in line and "REMOVED" in line for line in diff_lines)
    persisted = load_baseline(tmp_script)
    assert "ARG001" not in persisted
    assert persisted == new_baseline


def test_update_baseline_preserves_comments_and_sibling_entries(tmp_path: Path) -> None:
    """The rewrite touches only changed entries; comments stay verbatim.

    Lowering ARG001 and removing a zero-count S603 (which shares a line
    with N806 in the committed block) must keep the retirement notes and
    every sibling entry byte-for-byte.
    """
    tmp_script = _copy_script(tmp_path)
    counts = Counter(load_baseline(tmp_script))
    counts["ARG001"] = BASELINE["ARG001"] - 3
    counts["S603"] = 0

    update_baseline(tmp_script, counts)

    new_source = tmp_script.read_text(encoding="utf-8")
    assert "# ERA001 fue retirado del baseline" in new_source
    assert "# S603 fue retirado del baseline" in new_source
    assert f'"ARG001": {BASELINE["ARG001"] - 3}' in new_source
    assert '"S603"' not in re.sub(r"#.*", "", new_source)
    # Removing S603 (which shares line 100 with N806 in the committed block)
    # must not eat the newline: N806 keeps its own line and ARG002 stays on
    # its original continuation line.
    n806_lines = [line for line in new_source.splitlines() if '"N806"' in line]
    assert len(n806_lines) == 1 and '"ARG002"' not in n806_lines[0]
    assert n806_lines[0] == '    "N806": 1,', n806_lines[0]
    arg002_lines = [line for line in new_source.splitlines() if '"ARG002"' in line]
    assert len(arg002_lines) == 1 and '"N806"' not in arg002_lines[0]


def test_main_update_baseline_flag_persists_lock_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--update-baseline`` wires the lock-in into ``main`` and exits 0."""
    tmp_script = _copy_script(tmp_path, inflate_by=5)
    inflated = load_baseline(tmp_script)
    real_counts = Counter({code: value - 5 for code, value in inflated.items()})
    monkeypatch.setattr(
        sys.modules["check_ruff_ratchet"],
        "run_ruff",
        lambda *_args, **_kwargs: (real_counts, None),
    )

    exit_code = main(
        ["--update-baseline", "--script", str(tmp_script), str(REPO_ROOT)]
    )

    assert exit_code == 0
    assert load_baseline(tmp_script) == dict(real_counts)
