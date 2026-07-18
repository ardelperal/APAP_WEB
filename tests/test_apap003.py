"""APAP003 detector tests (PR-6B, Slice 6 of hardening-2026-q2).

APAP003 bans raw ``logger.{info,warning,error,debug,critical,exception}(...)``
calls in ``app/`` (except ``app/core/logging.py``). The rule is
implemented in two places that MUST stay in lock-step:

1. ``scripts/check_rules.py`` Detector 5 — the authoritative AST
   linter invoked by ``make check-rules``. This is what gates CI.
2. ``scripts/ruff_plugin/apap_rules.py`` ``APAP003Visitor`` —
   exercised by these tests and the existing
   ``tests/test_ruff_apap001.py`` smoke tests. Stays in lock-step
   with Detector 5 via the shared helper ``_is_logger_call``.

The ``app/core/logging.py`` exclusion is intentional and round-2
fix PA-2 documented: the wrapper module is the ONLY legal caller of
``logging.getLogger(...)``. Future logging infrastructure lives there.

Round-2 fix SB-7: APAP003 does NOT ban ``logging.getLogger(...)``
calls that do NOT chain into ``.info/.warning/.error/.debug/.critical/
.exception`` (the ``logging.getLogger(__name__)`` assignment line in
csrf.py was a pre-Slice-6 placeholder; today it does not exist in
the codebase but the rule keeps the door open for plain logger
retrieval, mirroring the AST linter's ``_is_logger_call`` predicate).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.check_rules import find_violations
from scripts.ruff_plugin.apap_rules import (
    APAP003Visitor,
    check_tree,
    discover_rule_classes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- Ruff visitor (APAP003Visitor via check_tree) --------------------------


def _parse(text: str, file_name: str = "test_input.py") -> ast.Module:
    return ast.parse(text, filename=file_name)


def test_apap003_rule_class_is_discoverable() -> None:
    """APAP003 MUST remain discoverable so ``select = ["APAP003"]`` would
    resolve if/when ruff supports packaged plugins (round-2 fix PA-2).
    """
    classes = discover_rule_classes()
    rule_ids = {cls.code for cls in classes}
    assert "APAP003" in rule_ids
    assert "APAP001" in rule_ids


def test_apap003_flags_logger_info_call_in_app(tmp_path: Path) -> None:
    """The visitor MUST flag ``logger.info(...)`` in app/ code."""
    src = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.info('hello')\n"
    )
    file = tmp_path / "app" / "modules" / "foo" / "bar.py"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert apap003, f"APAP003 did not flag logger.info(...):\n{src}"
    assert apap003[0].file == file
    assert apap003[0].line == 3


def test_apap003_flags_logging_getlogger_then_warning(tmp_path: Path) -> None:
    """The visitor MUST flag ``logging.getLogger(...).warning(...)`` (the
    pre-PR-6A csrf.py pattern; today not used in app/ but the rule
    must continue to ban it).
    """
    src = (
        "import logging\n"
        "logging.getLogger(__name__).warning('csrf.rejected')\n"
    )
    file = tmp_path / "app" / "core" / "demo.py"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert apap003, f"APAP003 did not flag logging.getLogger(...).warning(...):\n{src}"


@pytest.mark.parametrize(
    "method", ["info", "warning", "error", "debug", "critical", "exception"]
)
def test_apap003_flags_every_forbidden_method(
    method: str, tmp_path: Path
) -> None:
    """Every forbidden method MUST be flagged (closed list, no skips)."""
    src = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        f"logger.{method}('event')\n"
    )
    file = tmp_path / "app" / "demo.py"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert apap003, (
        f"APAP003 did not flag logger.{method}(...):\n{src}"
    )


def test_apap003_does_not_flag_log_safe(tmp_path: Path) -> None:
    """The visitor MUST NOT flag calls to ``log_safe(...)`` from
    ``app.core.logging`` — the wrapper IS the only allowed entry
    point, but the call site is a normal function call (not a
    logger.{...}) and lives in the rest of app/, not in
    ``app/core/logging.py``.
    """
    src = (
        "from app.core.logging import log_safe\n"
        "log_safe('auth.login', email='x@y.com')\n"
    )
    file = tmp_path / "app" / "main.py"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert not apap003, (
        f"APAP003 wrongly flagged log_safe call: {apap003}\n{src}"
    )


def test_apap003_does_not_flag_plain_getLogger_call(tmp_path: Path) -> None:
    """``logging.getLogger(__name__)`` (no chained method call) MUST NOT
    be flagged. Round-2 fix SB-7: APAP003 only bans the chained
    method call, not the retrieval.
    """
    src = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
    )
    file = tmp_path / "app" / "demo.py"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert not apap003, (
        f"APAP003 wrongly flagged plain getLogger retrieval: {apap003}"
    )


def test_apap003_visitor_direct_excludes_logging_wrapper(
    tmp_path: Path,
) -> None:
    """Issue #200: exercise ``APAP003Visitor`` directly to pin the
    ``app/core/logging.py`` exclusion — the wrapper module is the ONLY
    legal caller of ``logging.getLogger(...)`` and must not be flagged
    even though it emits raw ``logger.*`` calls internally.
    """
    src = (
        "import logging\n"
        "logger = logging.getLogger('apap')\n"
        "logger.info('inside the wrapper')\n"
    )
    file = tmp_path / "app" / "core" / "logging.py"
    visitor = APAP003Visitor(file)
    visitor.visit(_parse(src, file_name=str(file)))
    assert not visitor.violations, (
        f"APAP003Visitor must exclude app/core/logging.py: "
        f"{visitor.violations}"
    )


def test_apap003_visitor_direct_flags_non_excluded_file(
    tmp_path: Path,
) -> None:
    """Counterpart of the exclusion test: the same source in any other
    app/ file MUST be flagged when visiting directly (not via
    ``check_tree``).
    """
    src = (
        "import logging\n"
        "logger = logging.getLogger('apap')\n"
        "logger.info('raw call')\n"
    )
    file = tmp_path / "app" / "core" / "session.py"
    visitor = APAP003Visitor(file)
    visitor.visit(_parse(src, file_name=str(file)))
    assert visitor.violations
    assert all(v.rule_id == "APAP003" for v in visitor.violations)


# --- AST linter integration (scripts/check_rules.py Detector 5) -----------


def test_check_rules_detector_finds_apap003_violation(tmp_path: Path) -> None:
    """End-to-end: ``scripts.check_rules.find_violations`` MUST emit an
    ``apap003_raw_logger_call`` Violation for a file in app/ that calls
    ``logger.warning(...)`` directly.

    The Detector 5 wire-up is the authoritative lint gate; this test
    pins the contract so the gate stays wired if Detector 5 is renamed
    or moved.
    """
    target_dir = tmp_path / "app" / "modules" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "service.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.warning('something happened')\n",
        encoding="utf-8",
    )
    violations = find_violations(tmp_path)
    apap003 = [v for v in violations if v.rule_id == "apap003_raw_logger_call"]
    assert apap003, (
        f"Detector 5 did not flag the violation. Got: "
        f"{[(v.rule_id, v.line) for v in violations]}"
    )
    assert any(v.line == 3 for v in apap003)


def test_check_rules_detector_allows_log_safe_in_app(tmp_path: Path) -> None:
    """``log_safe(...)`` is the contract for emitting structured logs
    in app/. Detector 5 MUST NOT flag it (it is not a logger.* call).
    """
    target_dir = tmp_path / "app" / "core"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.py").write_text(
        "from app.core.logging import log_safe\n"
        "log_safe('auth.login', email='x@y.com')\n",
        encoding="utf-8",
    )
    violations = find_violations(tmp_path)
    apap003 = [v for v in violations if v.rule_id == "apap003_raw_logger_call"]
    assert not apap003, (
        f"Detector 5 wrongly flagged log_safe call: "
        f"{[(v.file, v.line) for v in apap003]}"
    )


def test_apap003_violation_message_guides_the_developer(tmp_path: Path) -> None:
    """The violation message MUST mention ``log_safe`` so a developer
    hitting the rule knows the fix.
    """
    file = tmp_path / "app" / "demo.py"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.warning('hi')\n",
        encoding="utf-8",
    )
    tree = _parse(file.read_text(encoding="utf-8"), file_name=str(file))
    violations = check_tree(tree, file)
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert apap003
    assert "log_safe" in apap003[0].message
