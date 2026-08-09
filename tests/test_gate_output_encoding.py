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
#: `check_migration_boundaries.py` is exempt for a different and worse reason: at 699 lines it
#: sits one line under the 700-line module cap, so the 8-line pin cannot fit. It is the same
#: shape as issue #203 (`app/main.py` at 699/700) — a module with no headroom cannot receive a
#: fix. Split it, then delete this exemption; until then that one gate still crashes on a
#: non-UTF-8 console.
EXEMPT = frozenset({"dev_server_no_lifespan.py", "check_migration_boundaries.py"})


def _printing_scripts() -> list[Path]:
    scripts = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name in EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        if "print(" in source and "def main(" in source:
            scripts.append(path)
    return scripts


def _pins_output_encoding(source: str) -> bool:
    """True when the module defines the pin and ``main()`` calls it.

    The pin lives in a helper rather than inline in ``main()`` on purpose: an inline ``if`` adds
    a branch to every entry point, and doing that to 22 gates pushed one of them past the
    PLR0912 branch ceiling that ``scripts/check_ruff_ratchet.py`` tracks. The ratchet was right.
    """
    tree = ast.parse(source)
    helper = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_pin_output_encoding"
        ),
        None,
    )
    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        ),
        None,
    )
    if helper is None or main is None:
        return False
    reconfigured = {
        node.func.value.attr
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reconfigure"
        and isinstance(node.func.value, ast.Attribute)
    }
    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_pin_output_encoding"
        for node in ast.walk(main)
    )
    return called and {"stdout", "stderr"} <= reconfigured


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
