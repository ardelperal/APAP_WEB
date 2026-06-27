"""Tests for the ruff APAP001 rule (PR-1B of hardening-2026-q2).

Exercises ``scripts.ruff_plugin.apap_rules.check_tree`` directly: ruff
0.15+ plugin entry-point registration is heavyweight and out of scope for
this change, so the rule is exercised as a plain Python AST visitor.

Spec: ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
(REQ-2).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from scripts.ruff_plugin.apap_rules import (
    APAPViolation,
    check_tree,
    discover_rule_classes,
)

from scripts.ruff_plugin import apap_rules

REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse(text: str, file_name: str = "test_input.py") -> ast.Module:
    return ast.parse(text, filename=file_name)


def _route_post_with_execute_sql() -> str:
    """Module declaring a POST handler that calls client.execute_sql."""
    return (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "client = object()\n"
        "@router.post('/x')\n"
        "def handler_create_thing(payload: dict) -> dict:\n"
        "    return client.execute_sql('SELECT 1', [])\n"
    )


def _route_get_with_execute_sql() -> str:
    """Module declaring a GET handler that calls client.execute_sql.

    Rule 1 exempts GET handlers per Detector 1 in scripts/check_rules.py
    and the APAP architecture (services are the only SQL layer; routes are
    thin wiring). See design.md Slice 1, line 84-91.
    """
    return (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "client = object()\n"
        "@router.get('/x')\n"
        "def handler_read_thing() -> dict:\n"
        "    return client.execute_sql('SELECT 1', [])\n"
    )


def _route_post_clean() -> str:
    """POST handler without client.execute_sql — must NOT flag."""
    return (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "client = object()\n"
        "@router.post('/x')\n"
        "def handler_create_thing(payload: dict) -> dict:\n"
        "    return {'ok': True}\n"
    )


# --- APAP001 -------------------------------------------------------------


def test_apap001_module_exposes_check_tree() -> None:
    """Public contract: the plugin must expose a ``check_tree`` callable."""
    assert callable(check_tree)


def test_apap001_flags_post_handler_with_execute_sql(tmp_path: Path) -> None:
    """REQ-2 Scenario 1: APAP001 fires on @router.post + client.execute_sql."""
    src = _route_post_with_execute_sql()
    file = tmp_path / "handler.py"
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap001 = [v for v in violations if v.rule_id == "APAP001"]
    assert apap001, f"APAP001 did not flag the POST handler:\n{src}"
    assert all(isinstance(v, APAPViolation) for v in apap001)
    assert all(v.file == file for v in apap001)
    # Line must point inside the handler body (execute_sql call site)
    assert apap001[0].line > 5


def test_apap001_does_not_flag_get_handler_with_execute_sql(
    tmp_path: Path,
) -> None:
    """REQ-2 mirror: GET handlers are exempt per Detector 1's contract."""
    src = _route_get_with_execute_sql()
    file = tmp_path / "handler.py"
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap001 = [v for v in violations if v.rule_id == "APAP001"]
    assert not apap001, (
        f"APAP001 wrongly flagged a GET handler: {apap001}\n{src}"
    )


def test_apap001_does_not_flag_clean_code(tmp_path: Path) -> None:
    """REQ-2 Scenario 2: clean POST handlers produce zero APAP001."""
    src = _route_post_clean()
    file = tmp_path / "handler.py"
    file.write_text(src, encoding="utf-8")
    tree = _parse(src, file_name=str(file))
    violations = check_tree(tree, file)
    apap001 = [v for v in violations if v.rule_id == "APAP001"]
    assert not apap001


def test_apap001_violation_message_mentions_execute_sql() -> None:
    """Diagnostic value: the violation message guides the developer."""
    src = _route_post_with_execute_sql()
    tree = _parse(src)
    violations = check_tree(tree, REPO_ROOT / "handler.py")
    apap001 = [v for v in violations if v.rule_id == "APAP001"]
    assert apap001
    assert "execute_sql" in apap001[0].message.lower()


# --- APAP003 stub --------------------------------------------------------


def test_apap003_rule_class_registered_and_active() -> None:
    """APAP003 must be discoverable AND must fire from ``check_tree``
    in PR-6B: Slice 6 (T-6.3) wired the visitor into the public
    entry point and added Detector 5 to ``scripts/check_rules.py``
    (the authoritative lint gate). The rule was registered in
    PR-1B (T-1B.2) but NOT fired until Slice 6 closed the
    transition window — see ``tasks.md:T-1B.2`` and
    ``design.md`` Slice 1, lines 145-156.
    """
    classes = discover_rule_classes()
    rule_ids = {cls.code for cls in classes}
    assert "APAP001" in rule_ids
    assert "APAP003" in rule_ids, (
        "APAP003 class must be discoverable for the visitor to be wired"
    )
    # APAP003 IS active now: a sample ``logger.warning(...)`` call
    # MUST be flagged by ``check_tree``.
    src = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.warning('hello')\n"
    )
    tree = _parse(src)
    violations = check_tree(tree, REPO_ROOT / "logger.py")
    apap003 = [v for v in violations if v.rule_id == "APAP003"]
    assert apap003, (
        "APAP003 must fire from check_tree in PR-6B; Slice 6 wired the "
        "visitor into the public entry point (T-6.3)."
    )
    assert apap003[0].line == 3


def test_apap_violation_dataclass_is_frozen() -> None:
    """APAPViolation must be immutable (frozen=True) to match the pattern
    of scripts/check_rules.py::Violation used by the AST linter."""
    # dataclass(frozen=True) sets __dataclass_params__.frozen
    assert getattr(APAPViolation, "__dataclass_params__", None) is not None
    assert APAPViolation.__dataclass_params__.frozen is True


# --- Plugin discoverability smoke ----------------------------------------


@pytest.mark.parametrize(
    "public_name",
    ["APAPViolation", "check_tree", "discover_rule_classes"],
)
def test_plugin_exposes_required_public_api(public_name: str) -> None:
    """Public API contract for downstream tooling and tests."""
    assert hasattr(apap_rules, public_name), (
        f"scripts.ruff_plugin.apap_rules must expose {public_name!r}"
    )
