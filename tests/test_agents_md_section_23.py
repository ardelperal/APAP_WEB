"""Pin the QA-through-UI contract (rule 23) after the AGENTS.md slim refactor.

Rule 23 was relocated from AGENTS.md §90 to
``docs/codebase/quality-gates.md`` as part of #554. The contract is
unchanged; only its home moved.

Issue #1096: the contract now points new UI flows at the **CI gate**
(``tests/e2e_ci/``) instead of the historical ``tests/e2e/``, which no job
executes. The pin asserts the destination, not just the wording, because
pointing contributors at a directory CI ignores is what let that suite rot.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "docs" / "codebase" / "quality-gates.md"


def _rule_23() -> str:
    rules = RULES_PATH.read_text(encoding="utf-8")
    start = rules.index("## Regla 23")
    end = rules.index("\n## Regla 24", start)
    return rules[start:end]


def test_rule_23_requires_qa_through_ui_only() -> None:
    section = _rule_23()

    assert "QA-through-UI solamente" in section
    assert "Playwright E2E del gate, bajo `tests/e2e_ci/`" in section, (
        "rule 23 must send new UI flows to the CI gate directory; the historical "
        "`tests/e2e/` destination was a directory no job executes (issue #1096)"
    )
    assert "bajo `tests/e2e/`" not in section, (
        "rule 23 must not send new flows to `tests/e2e/`, which holds only the "
        "production release gate (issue #1096)"
    )
    assert "shell de Python, inspección directa de DB o `curl`" in section
    assert "no es sustituto" in section


def test_rule_23_preserves_backend_only_exemption() -> None:
    section = _rule_23()

    assert (
        "Los slices solo-backend (services, migration, scripts) están exentos."
        in section
    )
