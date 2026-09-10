"""Every gate pins its output encoding (issue #488).

Python takes the stdout encoding from the platform locale. On the CI runner that is UTF-8; on a
Windows workstation it is cp1252, and a message carrying `§`, `—`, `→` or `∈` raised
UnicodeEncodeError from inside `print` — so the gate crashed with a traceback instead of
reporting the violation, on the one code path that only runs when something is already wrong.

Scrubbing the characters would be the wrong fix: this is a Spanish-domain application and
`scripts/check_spec_drift.py` legitimately carries `Añadir` in its intent-verb list. The defect
is the inherited encoding, not the alphabet.
"""

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

#: Scripts with no output to pin.
#:
#: `check_migration_boundaries.py` was exempt here until #490: at 699 lines against the 700-line
#: cap it had no room for the 8-line pin. Splitting its policy tables out took it to 543 and the
#: exemption is gone, so every printing gate is covered again.
EXEMPT = frozenset({"dev_server_no_lifespan.py"})


def _printing_scripts() -> list[Path]:
    scripts = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name in EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        if "print(" in source and "def main(" in source:
            scripts.append(path)
    return scripts


PIN = "_pin_output_encoding"


def _declared_helper(tree: ast.Module) -> ast.FunctionDef | None:
    """The module's own pin helper, if it declares one."""
    return next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == PIN),
        None,
    )


def _reconfigured_streams(helper: ast.FunctionDef) -> set[str]:
    """The streams ``helper`` calls ``.reconfigure()`` on."""
    return {
        node.func.value.attr
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reconfigure"
        and isinstance(node.func.value, ast.Attribute)
    }


def _pins_output_encoding(source: str) -> bool:
    """True when the pin reaches ``main()`` and really reconfigures both streams.

    The pin lives in a helper rather than inline in ``main()`` on purpose: an inline ``if`` adds
    a branch to every entry point, and doing that to 22 gates pushed one of them past the
    PLR0912 branch ceiling that ``scripts/check_ruff_ratchet.py`` tracks. The ratchet was right.
    """
    tree = ast.parse(source)
    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        ),
        None,
    )
    if main is None:
        return False
    called = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == PIN
        for node in ast.walk(main)
    )
    if not called:
        return False
    helper = _declared_helper(tree)
    if helper is None:
        return False
    return {"stdout", "stderr"} <= _reconfigured_streams(helper)


def test_every_printing_gate_pins_its_output_encoding():
    """Regression pin: a new gate cannot reintroduce the locale-dependent output."""
    unpinned = [
        path.name
        for path in _printing_scripts()
        if not _pins_output_encoding(path.read_text(encoding="utf-8"))
    ]
    assert not unpinned, f"gates not pinning stdout/stderr to UTF-8: {unpinned}"


def test_at_least_one_gate_is_covered():
    """Guard the guard: an empty scan must never read as a pass."""
    assert len(_printing_scripts()) >= 15


def test_calling_a_pin_that_is_neither_declared_nor_imported_is_rejected():
    """A bare call proves nothing — the helper has to exist somewhere this test can read."""
    source = "def main():\n    _pin_output_encoding()\n    print('x')\n"

    assert not _pins_output_encoding(source)


def test_pin_imported_from_outside_scripts_is_rejected():
    """Resolution stops at ``scripts/``: an unreadable origin is not a vouched-for pin."""
    source = (
        "from somewhere_else import _pin_output_encoding\n"
        "def main():\n"
        "    _pin_output_encoding()\n"
        "    print('x')\n"
    )

    assert not _pins_output_encoding(source)


def test_helper_that_pins_only_stdout_is_rejected():
    """Both streams or neither: a violation printed to stderr crashes just as hard."""
    source = (
        "import sys\n"
        "def _pin_output_encoding():\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "def main():\n"
        "    _pin_output_encoding()\n"
        "    print('x')\n"
    )

    assert not _pins_output_encoding(source)


def test_branch_name_gate_reports_instead_of_crashing_under_a_narrow_locale():
    """The original reproducer from issue #488.

    The failure message carries `§` and `∈`. Forcing cp1252 reproduces the Windows console; the
    gate must still print its reason and exit 1.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_branch_name.py"), "not-a-valid-branch"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**dict(__import__("os").environ), "PYTHONIOENCODING": "cp1252"},
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert "UnicodeEncodeError" not in result.stderr, result.stderr
    assert "FAIL" in result.stdout
