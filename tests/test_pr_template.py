from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PR_TEMPLATE_PATH = REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"


def test_pr_template_has_real_command_evidence_section() -> None:
    """Issue #882: checkboxes alone let a contributor claim untested work.

    The template must carry a field where the actual command and its real
    output get pasted, not just a self-declaration checkbox.
    """
    template = PR_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "## Comandos ejecutados" in template, (
        "la plantilla de PR debe tener una sección 'Comandos ejecutados' "
        "para pegar evidencia real, no solo el checkbox de autodeclaración "
        "(issue #882)"
    )


def test_contributing_references_pr_template_evidence_section() -> None:
    """CONTRIBUTING.md must point at the template section instead of
    duplicating the real-evidence requirement only in prose (issue #882).
    """
    contributing = CONTRIBUTING_PATH.read_text(encoding="utf-8")

    assert "Comandos ejecutados" in contributing, (
        "CONTRIBUTING.md debe referenciar la sección 'Comandos ejecutados' "
        "de la plantilla de PR en vez de exigir evidencia real solo en "
        "prosa (issue #882)"
    )
