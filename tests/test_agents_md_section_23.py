"""Pin the QA-through-UI contract in AGENTS.md section 23."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = REPO_ROOT / "AGENTS.md"


def _section_23() -> str:
    agents = AGENTS_PATH.read_text(encoding="utf-8")
    start = agents.index("### 23. E2E expectation")
    end = agents.index("\n### 24.", start)
    return agents[start:end]


def test_section_23_requires_qa_through_ui_only() -> None:
    section = _section_23()

    assert "QA-through-UI only" in section
    assert "Playwright E2E suite under `tests/e2e/`" in section
    assert "Python shell, direct DB inspection, or `curl`" in section
    assert "NOT a substitute" in section


def test_section_23_preserves_backend_only_exemption() -> None:
    section = _section_23()

    assert "Backend-only slices (services, migration, scripts) are exempt." in section
