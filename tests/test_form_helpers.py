from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.forms import optional_value, required_text


def test_optional_text_normalizes_missing_blank_and_surrounding_whitespace() -> None:
    assert optional_value(None) is None
    assert optional_value("   ") is None
    assert optional_value("  value  ") == "value"


def test_required_text_reads_and_strips_a_present_value() -> None:
    assert required_text({"name": "  Luna  "}, "name") == "Luna"


def test_required_text_uses_the_supplied_error_template_for_blank_values() -> None:
    with pytest.raises(ValueError, match="^name es obligatorio$"):
        required_text(
            {"name": "  "},
            "name",
            error_template="{field} es obligatorio",
        )


def test_modules_do_not_redefine_shared_form_helpers() -> None:
    paths = [
        Path("app/modules/animals/routes.py"),
        Path("app/modules/entradas/routes.py"),
        Path("app/modules/foster/routes.py"),
        Path("app/modules/materiales/routes.py"),
        Path("app/modules/materiales/acogida_routes.py"),
        Path("app/modules/entradas/service.py"),
        Path("app/modules/foster/service.py"),
    ]
    forbidden = {"_opt", "_required_text", "_optional_text"}
    definitions: list[str] = []

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        definitions.extend(
            f"{path}:{node.lineno}:{node.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in forbidden
        )

    assert definitions == []
