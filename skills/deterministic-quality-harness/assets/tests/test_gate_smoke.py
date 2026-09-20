# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_gate_smoke.py
"""Smoke tests: every gate is observed exiting 1 on a real violation (Execution Step 5).

A gate that has never been seen failing is a false guarantee. Each test here feeds a known
violation to a gate and asserts the failure, then feeds clean input and asserts the pass. When a
refactor silently breaks a detector, these go red before the detector's absence does damage.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
POLICY_DATE = "2026-08-12"


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    policy_scripts = {
        "check_complexity.py", "check_crap.py", "check_dry.py", "check_layers.py",
        "check_mutation.py", "check_mutation_sites.py", "quality_report.py",
    }
    resolved_args = list(args)
    if script == "check_mutation.py" and "--root" not in resolved_args and resolved_args:
        resolved_args += ["--root", str(Path(resolved_args[0]).resolve().parent)]
    if script in policy_scripts and "--policy-date" not in resolved_args:
        resolved_args += ["--policy-date", POLICY_DATE]
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *resolved_args],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )


def _load(script: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    name = script.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before executing: dataclasses resolve their annotations through sys.modules, so
    # a module that is not registered cannot define a dataclass with a union annotation.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------------------------
# check_layers
# ---------------------------------------------------------------------------------------------


def test_layers_gate_fails_on_a_violation() -> None:
    result = _run("check_layers.py", "--root", str(FIXTURES / "layers_violation"))
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize(
    "expected_key",
    ["purity:domain", "direction:domain->adapters", "slice:lanzadera->expedientes"],
)
def test_layers_gate_names_each_violation_class(expected_key: str) -> None:
    result = _run("check_layers.py", "--root", str(FIXTURES / "layers_violation"))
    assert expected_key in result.stdout, result.stdout


def test_layers_gate_passes_on_clean_code() -> None:
    result = _run("check_layers.py", "--root", str(FIXTURES / "layers_clean"))
    assert result.returncode == 0, result.stdout


def test_layers_gate_fails_on_files_it_could_not_classify() -> None:
    """Hard Rule 18, applied to this gate's own coverage.

    A file the gate cannot place into a (module, layer) pair is a file the gate did not check.
    Skipping it silently is how a layout mismatch hides a whole codebase behind a green tick —
    measured on a real repository: 118 of 178 files invisible, gate reporting clean.
    """
    result = _run("check_layers.py", "--root", str(FIXTURES / "layers_unclassified"))
    assert result.returncode == 1, result.stdout
    assert "unclassified" in result.stdout
    assert "loose_helper.py" in result.stdout


def test_layers_gate_publishes_how_much_it_actually_checked() -> None:
    envelope = json.loads(
        _run("check_layers.py", "--root", str(FIXTURES / "layers_unclassified"), "--json").stdout
    )
    assert envelope["indicators"]["files_unclassified"] == 1
    assert envelope["indicators"]["files_checked"] == 1


def test_layers_gate_fails_when_the_package_is_missing() -> None:
    """Fail closed: an empty walk must never report success."""
    result = _run("check_layers.py", "--root", str(FIXTURES))
    assert result.returncode == 1


def test_layers_ratchet_rejects_same_count_finding_substitution() -> None:
    module = _load("check_layers.py")
    today = module.date(2026, 8, 12)
    old = module.Violation(
        key="purity:domain",
        detail="domain imports framework sqlalchemy",
        file="app/orders/domain/model.py",
        line=4,
        subject="sqlalchemy",
    )
    replacement = module.Violation(
        key="purity:domain",
        detail="domain imports framework fastapi",
        file="app/billing/domain/model.py",
        line=9,
        subject="fastapi",
    )
    module.BASELINE = {
        old.identity: module.BaselineEntry(count=1, target=0, target_date="2026-12-31")
    }

    exit_code, lines = module.evaluate([replacement], today)

    assert exit_code == 1
    assert replacement.identity in "\n".join(lines)


def test_layers_baseline_migration_emits_stable_identities() -> None:
    module = _load("check_layers.py")
    violation = module.Violation(
        key="direction:domain->adapters",
        detail="domain may not import adapters",
        file="app/orders/domain/model.py",
        line=12,
        subject="app.orders.adapters.db",
    )

    rendered = module.render_baseline([violation], module.date(2026, 8, 12))

    assert violation.identity in rendered
    assert '"direction:domain->adapters"' not in rendered


def test_layers_legacy_aggregate_baseline_requires_explicit_migration() -> None:
    module = _load("check_layers.py")
    module.BASELINE = {
        "purity:domain": module.BaselineEntry(
            count=1, target=0, target_date="2026-12-31"
        )
    }

    exit_code, lines = module.evaluate([], module.date(2026, 8, 12))

    assert exit_code == 1
    assert "regenerate it with --emit-baseline" in "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# check_complexity
# ---------------------------------------------------------------------------------------------


def test_complexity_gate_fails_above_the_ceiling() -> None:
    result = _run("check_complexity.py", "--root", str(FIXTURES / "complexity_violation"))
    assert result.returncode == 1, result.stdout


def test_complexity_gate_passes_below_the_ceiling() -> None:
    result = _run("check_complexity.py", "--root", str(FIXTURES / "complexity_clean"))
    assert result.returncode == 0, result.stdout


def test_analysis_is_byte_stable_for_a_fixed_policy_date() -> None:
    args = ("--root", str(FIXTURES / "complexity_clean"), "--policy-date", POLICY_DATE, "--json")
    first = _run("check_complexity.py", *args)
    second = _run("check_complexity.py", *args)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["policy_date"] == POLICY_DATE


def test_gate_rejects_an_implicit_policy_date() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_complexity.py"), "--root", str(FIXTURES / "complexity_clean")],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )
    assert result.returncode != 0
    assert "--policy-date" in result.stderr


def test_expiry_is_still_enforced_at_the_explicit_policy_date() -> None:
    module = _load("check_complexity.py")
    offender = module.Measurement(
        key="app/x.py::legacy", name="legacy", file="app/x.py", line=1, complexity=16
    )
    module.BASELINE = {
        offender.key: module.BaselineEntry(complexity=16, target=15, target_date="2026-08-11")
    }
    exit_code, lines = module.evaluate([offender], module.date.fromisoformat(POLICY_DATE))
    assert exit_code == 1
    assert any("BASELINE expired" in line for line in lines)


def test_complexity_ceiling_is_absolute_not_top_n() -> None:
    """Hard Rule 12: the verdict on a function must not depend on its neighbours.

    The violation fixture holds one offender next to many trivial functions. A ``top-N`` gate
    would rank the offender out of view; an absolute ceiling still reports it.
    """
    result = _run("check_complexity.py", "--root", str(FIXTURES / "complexity_violation"))
    assert "too_many_branches" in result.stdout, result.stdout


# ---------------------------------------------------------------------------------------------
# check_branch_name
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("branch", ["feat/42-lanzadera-auth", "fix/7-crlf-count", "main"])
def test_branch_name_gate_accepts_valid_names(branch: str) -> None:
    assert _run("check_branch_name.py", "--branch", branch).returncode == 0


@pytest.mark.parametrize(
    "branch",
    ["lanzadera-auth", "feat/lanzadera-auth", "feat/42_lanzadera_auth", "FEAT/42-auth", "develop"],
)
def test_branch_name_gate_rejects_invalid_names(branch: str) -> None:
    assert _run("check_branch_name.py", "--branch", branch).returncode == 1


# ---------------------------------------------------------------------------------------------
# check_pr_size
#
# The diff path needs a git repository, so it is covered by the workflow itself rather than here.
# The override policy is pure logic and is covered directly: an override with no stated reason
# must not count as an override.
# ---------------------------------------------------------------------------------------------


def test_pr_size_override_requires_a_reason() -> None:
    module = _load("check_pr_size.py")
    assert module.override_reason("size:exception") is None
    assert module.override_reason("") is None
    assert (
        module.override_reason("size:exception\nsize-exception-reason: generated migration")
        == "generated migration"
    )


# ---------------------------------------------------------------------------------------------
# check_crap
# ---------------------------------------------------------------------------------------------


def test_crap_gate_fails_on_untested_complexity() -> None:
    result = _run("check_crap.py", "--root", str(FIXTURES / "crap_violation"))
    assert result.returncode == 1, result.stdout


def test_crap_gate_catches_what_the_complexity_ceiling_lets_through() -> None:
    """The whole argument for CRAP, pinned as a test.

    The offender sits at complexity 4 — far under the complexity ceiling of 15, so that gate
    passes it. With no tests behind it, CRAP scores it 20. If these two ever agree, the CRAP
    gate has stopped adding information.
    """
    complexity = _run("check_complexity.py", "--root", str(FIXTURES / "crap_violation"))
    crap = _run("check_crap.py", "--root", str(FIXTURES / "crap_violation"))
    assert complexity.returncode == 0, complexity.stdout
    assert crap.returncode == 1, crap.stdout
    assert "CRAP 20.0" in crap.stdout


def test_crap_gate_passes_on_small_covered_functions() -> None:
    result = _run("check_crap.py", "--root", str(FIXTURES / "crap_clean"))
    assert result.returncode == 0, result.stdout


def test_crap_gate_fails_closed_without_coverage_data(tmp_path) -> None:
    """No coverage data means no verdict, and no verdict must never read as success."""
    package = tmp_path / "app" / "lanzadera" / "domain"
    package.mkdir(parents=True)
    (package / "model.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    result = _run("check_crap.py", "--root", str(tmp_path))
    assert result.returncode == 1
    assert "coverage" in (result.stderr + result.stdout).lower()


# ---------------------------------------------------------------------------------------------
# check_dry
# ---------------------------------------------------------------------------------------------


def test_dry_gate_fails_on_a_renamed_copy_paste() -> None:
    result = _run("check_dry.py", "--root", str(FIXTURES / "dry_violation"))
    assert result.returncode == 1, result.stdout
    assert "alpha.py" in result.stdout and "beta.py" in result.stdout


def test_dry_gate_passes_on_distinct_code() -> None:
    result = _run("check_dry.py", "--root", str(FIXTURES / "dry_clean"))
    assert result.returncode == 0, result.stdout


def test_dry_baseline_key_survives_the_clone_spreading_to_another_file() -> None:
    """A ratchet whose key moves with the thing it ratchets is not a ratchet.

    The key used to be the joined file list, so copying the same block into one more file
    changed the key, the BASELINE entry stopped matching, and a grown clone read as a brand-new
    one. The key is the clone's own digest now: same duplication, same key, higher count.
    """
    module = _load("check_dry.py")
    two = module.collect_groups(FIXTURES / "dry_violation")
    three = module.collect_groups(FIXTURES / "dry_three_copies")
    assert two and three
    assert {group.key for group in two} == {group.key for group in three}
    assert len(three[0].occurrences) == 3, "the third copy must raise the count"


def test_dry_reports_a_long_clone_region_once() -> None:
    """A sliding window over one duplicated region produced one finding per offset.

    On a real codebase that turned 37 genuine clones into 333 findings — the exact noise level
    at which a team switches the gate off. The fixture's duplicated body is 6 statements, so a
    5-statement window slides over it twice; both offsets describe the same duplication and
    only one survives. A region long enough to hold two DISJOINT windows still reports two,
    which is correct: that really is two separate blocks of duplicated code.
    """
    module = _load("check_dry.py")
    groups = module.collect_groups(FIXTURES / "dry_long_region")
    assert len(groups) == 1, [group.key for group in groups]
    assert len(groups[0].occurrences) == 2


def test_dry_detection_is_stable_across_processes() -> None:
    """Determinism pin: the digest must not depend on PYTHONHASHSEED.

    An earlier draft keyed clone groups on the builtin ``hash()``, which is salted per process.
    The gate then reported different groups on identical code from one run to the next.
    """
    first = _run("check_dry.py", "--root", str(FIXTURES / "dry_violation"), "--json")
    second = _run("check_dry.py", "--root", str(FIXTURES / "dry_violation"), "--json")
    assert first.stdout == second.stdout


# ---------------------------------------------------------------------------------------------
# check_mutation_sites
# ---------------------------------------------------------------------------------------------


def test_mutation_sites_gate_fails_on_a_large_surface() -> None:
    result = _run("check_mutation_sites.py", "--root", str(FIXTURES / "mutation_sites_violation"))
    assert result.returncode == 1, result.stdout


def test_mutation_sites_catches_what_complexity_and_crap_cannot() -> None:
    """Surface is a property of the file, not of any one function.

    The fixture is all trivial functions and literals: complexity passes it, and CRAP would too.
    Only the site count says that changing anything in there is expensive.
    """
    root = FIXTURES / "mutation_sites_violation"
    assert _run("check_complexity.py", "--root", str(root)).returncode == 0
    assert _run("check_mutation_sites.py", "--root", str(root)).returncode == 1


def test_mutation_sites_gate_passes_on_a_small_surface() -> None:
    result = _run("check_mutation_sites.py", "--root", str(FIXTURES / "mutation_sites_clean"))
    assert result.returncode == 0, result.stdout


def test_mutation_sites_emits_a_baseline_with_target_and_date() -> None:
    """A ratchet you have to hand-write is a ratchet nobody adopts — and every emitted entry
    must already carry its exit plan, so an expiry-less baseline cannot be produced by accident.
    """
    result = _run(
        "check_mutation_sites.py",
        "--root",
        str(FIXTURES / "mutation_sites_violation"),
        "--emit-baseline",
    )
    assert result.returncode == 0
    assert "BaselineEntry(sites=" in result.stdout
    assert "target=" in result.stdout and "target_date=" in result.stdout


# ---------------------------------------------------------------------------------------------
# check_mutation
# ---------------------------------------------------------------------------------------------


def _make_session(
    path: Path,
    rows: list[
        tuple[str, str | None] | tuple[str, str | None, str, int]
    ],
) -> Path:
    """Build a minimal cosmic-ray session so these tests run without the mutation runner."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE work_items (job_id TEXT PRIMARY KEY);
        CREATE TABLE mutation_specs (
            job_id TEXT, module_path TEXT, operator_name TEXT, occurrence INTEGER
        );
        CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, worker_outcome TEXT);
        """
    )
    for index, row in enumerate(rows):
        module, outcome = row[:2]
        subject = path.parent / module
        subject.parent.mkdir(parents=True, exist_ok=True)
        if not subject.exists():
            subject.write_text("VALUE = 1\n", encoding="utf-8")
        operator, occurrence = row[2:] if len(row) == 4 else (f"operator-{index}", 0)
        job = f"job-{index}"
        connection.execute("INSERT INTO work_items VALUES (?)", (job,))
        connection.execute(
            "INSERT INTO mutation_specs VALUES (?, ?, ?, ?)",
            (job, module, operator, occurrence),
        )
        if outcome is not None:
            connection.execute(
                "INSERT INTO work_results VALUES (?, ?, ?)", (job, outcome, "normal")
            )
    connection.commit()
    connection.close()
    return path


def test_mutation_gate_passes_a_healthy_run(tmp_path) -> None:
    session = _make_session(tmp_path / "s.sqlite", [("app/a.py", "killed")] * 10)
    result = _run("check_mutation.py", str(session))
    assert result.returncode == 0, result.stdout + result.stderr


def test_mutation_gate_rejects_a_run_that_measured_nothing(tmp_path) -> None:
    """Hard Rule 18, pinned.

    Every mutant came back INCOMPETENT: the runner never executed. A plain survival-rate
    threshold reports this as a flawless run, which is the failure mode this gate exists for.
    """
    session = _make_session(tmp_path / "s.sqlite", [("app/a.py", "incompetent")] * 10)
    result = _run("check_mutation.py", str(session))
    assert result.returncode == 1
    assert "degenerate" in result.stdout.lower()


def test_mutation_gate_rejects_an_incomplete_run(tmp_path) -> None:
    rows = [("app/a.py", "killed")] * 5 + [("app/a.py", None)] * 5
    session = _make_session(tmp_path / "s.sqlite", rows)
    result = _run("check_mutation.py", str(session))
    assert result.returncode == 1
    assert "incomplete" in result.stdout.lower()


def test_mutation_gate_fails_on_an_unrecorded_survivor(tmp_path) -> None:
    rows = [("app/a.py", "killed")] * 9 + [("app/a.py", "survived")]
    session = _make_session(tmp_path / "s.sqlite", rows)
    result = _run("check_mutation.py", str(session))
    assert result.returncode == 1
    assert "not in BASELINE" in result.stdout


def test_mutation_ratchet_rejects_same_count_survivor_substitution(tmp_path) -> None:
    module = _load("check_mutation.py")
    old_session = _make_session(
        tmp_path / "old.sqlite",
        [("app/a.py", "survived", "core/replace_add", 0)],
    )
    new_session = _make_session(
        tmp_path / "new.sqlite",
        [("app/a.py", "survived", "core/replace_subtract", 0)],
    )
    old_rows, old_errors = module.read_session(old_session)
    new_rows, new_errors = module.read_session(new_session)
    assert old_errors == new_errors == []
    old_survivors = module.measure_survivors(old_rows)
    new_survivors = module.measure_survivors(new_rows)
    old_identity = next(iter(old_survivors))
    new_identity = next(iter(new_survivors))
    module.BASELINE = {
        old_identity: module.BaselineEntry(
            survivors=1, target=0, target_date="2026-12-31"
        )
    }

    violations, _ = module.check_ratchet(new_survivors, module.date(2026, 8, 12))

    assert old_identity != new_identity
    assert any(new_identity in violation for violation in violations)


def test_mutation_baseline_migration_emits_stable_identities(tmp_path) -> None:
    module = _load("check_mutation.py")
    session = _make_session(
        tmp_path / "s.sqlite",
        [("app/a.py", "survived", "core/replace_add", 3)],
    )
    rows, errors = module.read_session(session)
    assert errors == []
    survivors = module.measure_survivors(rows)

    rendered = module.render_baseline(survivors, module.date(2026, 8, 12))

    identity = next(iter(survivors))
    assert identity in rendered
    assert '"app/a.py": BaselineEntry' not in rendered


@pytest.mark.parametrize(
    ("rows", "expected_error"),
    [
        ([], "no mutation jobs"),
        ([("app/a.py", None)], "incomplete"),
        ([("app/a.py", "unknown")], "unknown"),
        (
            [("app/a.py", "incompetent")] * 3 + [("app/a.py", "killed")] * 7,
            "INCOMPETENT",
        ),
    ],
)
def test_mutation_baseline_emission_rejects_unhealthy_sessions_without_writing(
    tmp_path, rows, expected_error
) -> None:
    session = _make_session(tmp_path / "s.sqlite", rows)
    output = tmp_path / "baseline.py"
    output.write_text("keep-existing-baseline\n", encoding="utf-8")

    result = _run(
        "check_mutation.py",
        str(session),
        "--emit-baseline",
        "--baseline-output",
        str(output),
    )

    assert result.returncode == 1
    assert expected_error.lower() in result.stderr.lower()
    assert result.stdout == ""
    assert output.read_text(encoding="utf-8") == "keep-existing-baseline\n"

    absent_output = tmp_path / "absent-baseline.py"
    absent_result = _run(
        "check_mutation.py",
        str(session),
        "--emit-baseline",
        "--baseline-output",
        str(absent_output),
    )
    assert absent_result.returncode == 1
    assert not absent_output.exists()


def test_mutation_baseline_emission_is_deterministic_and_atomic(tmp_path) -> None:
    session = _make_session(
        tmp_path / "s.sqlite",
        [
            ("app/b.py", "survived", "core/replace_subtract", 2),
            ("app/a.py", "killed", "core/replace_add", 0),
            ("app/a.py", "survived", "core/replace_add", 1),
        ],
    )
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"

    first_result = _run(
        "check_mutation.py",
        str(session),
        "--emit-baseline",
        "--baseline-output",
        str(first),
    )
    second_result = _run(
        "check_mutation.py",
        str(session),
        "--emit-baseline",
        "--baseline-output",
        str(second),
    )

    assert first_result.returncode == second_result.returncode == 0
    assert first_result.stdout == second_result.stdout == ""
    assert first.read_bytes() == second.read_bytes()
    assert not first.with_suffix(".py.tmp").exists()
    assert first.read_text(encoding="utf-8").endswith("\n")


def test_mutation_gate_fails_closed_on_a_missing_session(tmp_path) -> None:
    result = _run("check_mutation.py", str(tmp_path / "absent.sqlite"))
    assert result.returncode == 1


def test_mutation_gate_reports_score_and_incompetent_ratio(tmp_path) -> None:
    rows = [("app/a.py", "killed")] * 8 + [("app/a.py", "incompetent")]
    session = _make_session(tmp_path / "s.sqlite", rows)
    envelope = json.loads(
        _run("check_mutation.py", str(session), "--root", str(tmp_path), "--json").stdout
    )
    assert envelope["indicators"]["mutation_score_pct"] == 100.0
    assert envelope["indicators"]["incompetent_ratio_pct"] > 0


def test_mutation_gate_rejects_a_session_outside_the_policy_manifest(tmp_path) -> None:
    session = _make_session(
        tmp_path / "s.sqlite",
        [("app/a.py", "killed")] * 3 + [("src/outside.py", "killed")],
    )

    result = _run("check_mutation.py", str(session), "--json")

    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "fail"
    assert envelope["subjects"]["unclassified"] == ["src/outside.py"]
    assert "outside quality policy" in envelope["findings"][-1]["detail"]


def test_acquisition_marker_cannot_become_permanent() -> None:
    """A module 'we have not measured yet' must stop being acceptable after the grace period."""
    module = _load("check_mutation.py")
    today = module.date(2026, 8, 8)
    module.BASELINE = {"app/fresh.py": module.AwaitingAcquisition(since="2026-08-05")}
    assert module.check_pending_overdue(today) == []
    module.BASELINE = {"app/stale.py": module.AwaitingAcquisition(since="2026-06-01")}
    assert module.check_pending_overdue(today), "an overdue acquisition marker must fail the gate"


# ---------------------------------------------------------------------------------------------
# quality_report — the indicator layer
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gate_script",
    [
        "check_layers.py",
        "check_complexity.py",
        "check_crap.py",
        "check_dry.py",
        "check_mutation_sites.py",
        "check_branch_name.py",
    ],
)
def test_every_gate_emits_a_well_formed_envelope(gate_script: str) -> None:
    root = FIXTURES / "crap_clean"
    args = ["--branch", "main"] if gate_script == "check_branch_name.py" else ["--root", str(root)]
    result = _run(gate_script, *args, "--json")
    envelope = json.loads(result.stdout)
    assert envelope["gate"]
    assert envelope["status"] in {"pass", "fail", "error"}
    assert isinstance(envelope["indicators"], dict)
    assert isinstance(envelope["findings"], list)
    if gate_script != "check_branch_name.py":
        assert envelope["candidate"]["tree"]
        assert envelope["scope_identity"].startswith("sha256:")
        assert envelope["subject_manifest"]
        assert envelope["owner"]
        assert envelope["non_ownership"]
        assert set(envelope["subjects"]) == {"checked", "skipped", "unclassified"}


def test_quality_report_aggregates_indicators(tmp_path) -> None:
    out = tmp_path / "quality-report.json"
    result = _run(
        "quality_report.py", "--root", str(FIXTURES / "crap_clean"), "--out", str(out)
    )
    assert result.returncode == 0, result.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["candidate"]["tree"]
    assert report["scope_identity"].startswith("sha256:")
    assert report["subject_manifest"]
    for indicator in ("layers.violations", "complexity.max_complexity", "crap.max_crap"):
        assert indicator in report["indicators"], report["indicators"].keys()
    assert report["indicators"]["crap.max_crap"]["ceiling"] == 6.0


def test_quality_report_names_the_failing_gate(tmp_path) -> None:
    out = tmp_path / "quality-report.json"
    result = _run(
        "quality_report.py", "--root", str(FIXTURES / "crap_violation"), "--out", str(out)
    )
    assert result.returncode == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["failed_gates"] == ["crap"]


def test_quality_report_is_byte_identical_for_the_same_commit(tmp_path) -> None:
    """Determinism pin: no wall-clock timestamp may leak into the report."""
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    _run("quality_report.py", "--root", str(FIXTURES / "crap_clean"), "--out", str(first))
    _run("quality_report.py", "--root", str(FIXTURES / "crap_clean"), "--out", str(second))
    assert first.read_bytes() == second.read_bytes()
