"""Strict TDD atom pinning the PR4b+4R atom-count headline against drift.

The PR4b PII audit doc + apply-progress.md + tasks.md each carry an
atom-count claim for the four PR4b test modules. ``pytest --collect-only``
is the ground truth; any headline that disagrees with it is a drift.

Background (2026-07-12, PR4b 4R verify WARN): the audit/runbook 4R
remediation batch shipped 11 new atoms (was 59 PR4b-shipped, became
70 after 4R), but apply-progress.md and tasks.md continued to claim
"**75 atoms**" — a 5-atom drift carried over from a draft where
some per-file counts were inadvertently double-counted. The drift
slipped past the 4R remediation's full gate (which only checked
``pytest tests/migration/test_insforge_storage_methods.py ...
tests/test_pii_audit_doc.py -v`` returned green; it never asserted the
headline count).

This atom is the guard. It runs ``pytest --collect-only`` on the four
PR4b test modules and asserts every explicit 4R-era headline claim in
the SDD artifacts agrees. Pre-4R historical evidence (e.g. the
original "All 59 atoms run under" line in the PR4b SOLID compliance
section) is intentionally NOT checked — it is a record of the
pre-4R state and per the user's "never overwrite prior evidence"
directive must remain verbatim.

The per-file numbers (15 / 18 / 30 / 7) are hard-coded as the
authoritative decomposition; pytest confirms the sum. Future drift
(a removed atom, an added atom, an incorrect count in a 4R-era
headline) trips this atom on the next CI run.

Hard rules honoured (web-tdd-philosophy):

- Rule 2 (DI): subprocess receives the python executable + cwd as
  explicit arguments; no global state.
- Rule 3 (cardinality): ``int(re.search(...).group(1))`` pins the
  exact ``"N tests collected"`` number, not absence-of-error.
- Rule 4 (no humo): the headline value is asserted as an integer
  equality with the pytest ground truth, not "is not None" or
  "is a positive integer".
- Rule 6 (refactor-safety): the assertion is about the rendered text
  shape (regex against markdown), not internal line numbers; future
  paragraph reshuffling in the artifacts still trips the same atom.
- Rule 8 (no production mutation): pure read against the repo tree
  + a sandboxed ``pytest --collect-only`` (no InsForge / no Access).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Per-file atom counts (authoritative decomposition; sum is the
# pytest --collect-only ground truth at PR4b+4R remediation close).
# Updating any of these requires updating the corresponding test file
# AND re-running pytest --collect-only to confirm the new sum.
PER_FILE_ATOM_COUNTS: dict[str, int] = {
    "tests/test_log_safe_redaction.py": 15,
    "tests/test_animals_foto_route.py": 15,  # PR-C deleted 3 redundant atoms (test_foto_streaming_route / test_photo_outcome_streaming / test_animal_photo_resolution all moved here or were absorbed)
    "tests/migration/test_insforge_storage_methods.py": 34,
    "tests/test_pii_audit_doc.py": 7,
}
EXPECTED_TOTAL: int = sum(PER_FILE_ATOM_COUNTS.values())  # 71 (PR-C: -3 atoms retired from test_animals_foto_route)

# Headline atom-count patterns for 4R-era claims. Each pattern
# matches a numeric claim that, if it disagrees with EXPECTED_TOTAL,
# is a drift. Per-file numbers (e.g. "**15 atoms**" inside the
# ``tests/test_log_safe_redaction.py`` per-bullet text) are NOT matched.
HEADLINE_REGEXES: tuple[str, ...] = (
    r"\*\*(\d+) atoms\*\* across the 4 PR4b test modules",
    r"all green \(\*\*(\d+) atoms\*\* after 4R remediation",
    r"All (\d+) atoms run under `httpx\.MockTransport`",
)

# Artifacts that carry 4R-era explicit headline claims. The audit doc
# uses per-file numbers in the Verdict bullets (which sum to the
# correct total); it does not carry a single "N atoms" 4R headline,
# so it is not in this list.
ARTIFACTS_WITH_HEADLINE: tuple[Path, ...] = (
    REPO_ROOT / "openspec" / "changes" / "live-data-migration-sandbox" / "apply-progress.md",
    REPO_ROOT / "openspec" / "changes" / "live-data-migration-sandbox" / "tasks.md",
)


def _collect_only_count() -> int:
    """Run ``pytest --collect-only`` on the four PR4b modules; return the count.

    The CLI invocation mirrors the one used by the PR4b 4.6 verification
    gate (``pytest tests/migration/test_insforge_storage_methods.py
    tests/test_log_safe_redaction.py tests/test_animals_foto_route.py
    tests/test_pii_audit_doc.py -v``). The parse extracts the trailing
    ``"N tests collected"`` line.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/migration/test_insforge_storage_methods.py",
            "tests/test_log_safe_redaction.py",
            "tests/test_animals_foto_route.py",
            "tests/test_pii_audit_doc.py",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    match = re.search(r"(\d+) tests collected", proc.stdout)
    assert match is not None, (
        "pytest --collect-only did not emit a 'N tests collected' line; "
        f"stdout was:\n{proc.stdout}"
    )
    return int(match.group(1))


def _slice_4r_era(text: str) -> str:
    """Return the 4R-era portion of an apply-progress / tasks artifact.

    The "PR4b 4R Remediation (2026-07-12)" section heading (level 2 in
    apply-progress.md, level 2 or 3 in tasks.md) marks the start of
    4R-era content. Pre-4R sections (PR4b 4.6 verification entry in
    the cumulative state, "PR4b SOLID compliance notes", "PR4b
    Verification Summary", etc.) carry HISTORICAL atom counts that
    must remain verbatim — the user's "never overwrite prior evidence"
    directive. The "Next batch" section (which summarises the current
    state) is also 4R-era and is included.

    Heuristic: return everything from the first match of
    ``"### PR4b 4R Remediation"`` OR ``"### Next batch"`` (whichever
    comes first) to end of file. If neither heading exists, fall back
    to the full file (defensive default for future renames).
    """
    candidates = [
        text.find("### PR4b 4R Remediation"),
        text.find("### Next batch"),
    ]
    candidates = [c for c in candidates if c != -1]
    if not candidates:
        return text
    return text[min(candidates):]


def test_per_file_atom_count_decomposition_matches_pytest() -> None:
    """The hard-coded per-file atom-count decomposition must match pytest ground truth.

    This pins the test data: the four PR4b test modules together
    collect to exactly EXPECTED_TOTAL atoms per pytest --collect-only.
    If this fails, the headline assertion below is meaningless (the
    per-file numbers themselves drifted from reality). The fix is to
    update PER_FILE_ATOM_COUNTS to match the new pytest count, or to
    investigate why an atom was added / removed.
    """
    actual = _collect_only_count()
    assert actual == EXPECTED_TOTAL, (
        f"Per-file atom-count decomposition drift: sum of "
        f"{PER_FILE_ATOM_COUNTS} is {EXPECTED_TOTAL} but pytest "
        f"--collect-only reports {actual}. Update PER_FILE_ATOM_COUNTS "
        f"to match the new total (and verify the per-file breakdown "
        f"with `pytest --collect-only -q <module>` per file)."
    )


def test_pr4b_artifact_headline_atom_counts_match_pytest() -> None:
    """Every 4R-era PR4b+4R atom-count headline in the SDD artifacts MUST match pytest.

    This is the drift guard. Earlier versions of apply-progress.md and
    tasks.md claimed "**75 atoms**" (drift = +5) because the draft
    author double-counted the per-chunk timeout atoms that are
    ALREADY inside the 30-atom ``tests/migration/test_insforge_storage_methods.py``
    total. The audit doc's Verdict bullets and acceptance evidence
    index use per-file numbers that the audit's own headline
    recomputes from the per-file table — there is no single
    "**75 atoms**" headline in the audit doc to drift, so the audit
    doc is not in the headline-claim list.

    The check is scoped to 4R-era sections only (``### PR4b 4R
    Remediation`` and ``### Next batch``) so pre-4R historical claims
    like the original "All 59 atoms run under" in the PR4b SOLID
    compliance section remain verbatim.
    """
    actual = _collect_only_count()

    for path in ARTIFACTS_WITH_HEADLINE:
        text = path.read_text(encoding="utf-8")
        era_text = _slice_4r_era(text)
        # The offset where the 4R era starts in the full text — used
        # to convert slice-relative match offsets to absolute line
        # numbers (operators see the actual file line, not the line
        # within the slice).
        era_offset_in_text = text.find(era_text)
        # Track every headline match so the failure message is
        # exhaustive (every drift location is named in one assertion
        # failure rather than failing one-at-a-time across CI runs).
        drifts: list[str] = []
        for regex in HEADLINE_REGEXES:
            for match in re.finditer(regex, era_text):
                absolute_offset = era_offset_in_text + match.start()
                line_no = text[:absolute_offset].count("\n") + 1
                claimed = int(match.group(1))
                if claimed != actual:
                    drifts.append(
                        f"  line {line_no}: '{match.group(0)}' (claimed {claimed})"
                    )
        assert not drifts, (
            f"{path.name}: PR4b+4R headline atom-count drift detected.\n"
            f"  pytest --collect-only ground truth: {actual} atoms "
            f"(per-file decomposition: {dict(PER_FILE_ATOM_COUNTS)}).\n"
            f"  Drift locations:\n" + "\n".join(drifts) + "\n"
            f"  Fix: amend the headline(s) to '**{actual} atoms**'."
        )
