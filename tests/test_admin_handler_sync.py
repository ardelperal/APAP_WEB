"""Pins the async/sync consistency of the admin handlers.

``admin_add_user`` was historically ``async def`` and called
``await request.form()`` even though it then called the SYNC
``LocalPostgresExecutor``. In FastAPI, ``async def`` handlers run on the
event loop; calling a sync HTTP client (the InsForge ``Client``) from
the loop blocks it for the duration of the call (no threadpool
offload — the handler is async, so FastAPI doesn't move it to a
worker thread).

The rest of the admin handlers (``admin_list_users``,
``admin_deactivate_user``) are ``def`` — FastAPI runs them in a
threadpool, so the sync InsForge client is fine.

This module pins the contract that ``admin_add_user`` MUST be ``def``
(not ``async def``) so the inconsistency cannot regress.
"""

from __future__ import annotations

import inspect

from app.main import app


def _get_admin_add_user():
    """Resolve the ``admin_add_user`` route function via the app router."""
    for route in app.routes:
        if getattr(route, "name", None) == "admin_add_user":
            return route.endpoint
    raise AssertionError("admin_add_user route not found in app")


def test_admin_add_user_is_sync_def_not_async() -> None:
    """``admin_add_user`` MUST be ``def`` (sync), not ``async def``.

    Async handler + sync InsForge client = blocks the event loop.
    Other admin handlers are sync (they run in the threadpool where
    the sync client is fine). The new contract: all admin handlers
    use the same async/sync style.
    """
    func = _get_admin_add_user()
    assert not inspect.iscoroutinefunction(func), (
        "admin_add_user is async def but calls the sync LocalPostgresExecutor; "
        "this blocks the FastAPI event loop for the duration of the SQL "
        "call. Convert to `def` so FastAPI runs it in the threadpool "
        "where the sync client is fine (same as admin_deactivate_user)."
    )


def _form_param_names(func) -> list[str]:
    """Return the names of parameters declared as ``Form(...)`` inputs.

    Recognises both the legacy ``x: str = Form(...)`` pattern and the
    modern ``x: Annotated[str, Form()] = ...`` pattern.
    """
    import ast as _ast

    source = inspect.getsource(func)
    # Drop the ``@app.post(...)`` decorator line so the source parses
    # as a bare function definition (the function lives inside
    # ``create_app`` so every line is indented; the AST parser only
    # cares about the function name and arg shapes).
    lines = [
        line for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("@")
    ]
    # Determine the common leading-indent of the function body lines
    # so we can dedent uniformly and let the parser see the docstring
    # as part of the function.
    non_empty = [line for line in lines if line.strip()]
    indent = min(
        len(line) - len(line.lstrip())
        for line in non_empty
    )
    dedented = "\n".join(line[indent:] if len(line) >= indent else line for line in lines)
    tree = _ast.parse(dedented)
    for node in _ast.walk(tree):
        if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        if node.name != func.__name__:
            continue
        # Python puts the LAST N defaults in ``args.defaults``; the first
        # args don't carry defaults even when they appear in the
        # signature without ``= ...``. Pad with ``None`` so every arg
        # is visited.
        defaults = [None] * (
            len(node.args.args) - len(node.args.defaults or [])
        ) + list(node.args.defaults or [])
        form_names: list[str] = []
        for arg, default in zip(node.args.args, defaults, strict=False):
            if _annotation_uses_form(_ast, arg.annotation):
                form_names.append(arg.arg)
                continue
            if (
                isinstance(default, _ast.Call)
                and isinstance(default.func, _ast.Name)
                and default.func.id == "Form"
            ):
                form_names.append(arg.arg)
        return form_names
    return []


def _annotation_uses_form(_ast, annotation) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, _ast.Call):
        return (
            isinstance(annotation.func, _ast.Name)
            and annotation.func.id == "Form"
        )
    if isinstance(annotation, _ast.Subscript):
        return _annotation_uses_form(_ast, annotation.slice)
    if isinstance(annotation, _ast.Tuple):
        return any(_annotation_uses_form(_ast, elt) for elt in annotation.elts)
    return False


def test_admin_add_user_signature_uses_form_params_not_request_form() -> None:
    """``admin_add_user`` MUST read the form via ``Form(...)`` parameters.

    Async-style ``await request.form()`` couples the handler to the
    async event loop. ``Form(...)`` parameters work in both sync and
    async handlers; using them in a sync ``def`` makes the contract
    obvious and matches the rest of the codebase.
    """
    func = _get_admin_add_user()
    form_param_names = _form_param_names(func)
    # At least the two form fields the handler reads (email + rol)
    # must be declared as Form() parameters, not pulled out of
    # ``await request.form()``.
    assert "email" in form_param_names, (
        f"admin_add_user must declare `email: str = Form(...)`, not pull "
        f"it from `await request.form()`; current Form params: "
        f"{form_param_names!r}"
    )
    assert "rol" in form_param_names, (
        f"admin_add_user must declare `rol: str = Form(...)`, not pull "
        f"it from `await request.form()`; current Form params: "
        f"{form_param_names!r}"
    )


def test_admin_handlers_all_use_the_same_async_style() -> None:
    """All admin handlers MUST use the same async style.

    Mixing async and sync in the same route module is a footgun:
    every new handler has to re-derive the right choice. Pin the
    rule: ALL admin handlers are ``def`` (sync), so the sync
    InsForge client is always safe.
    """
    for route in app.routes:
        if not getattr(route, "name", "").startswith("admin_"):
            continue
        endpoint = route.endpoint
        assert not inspect.iscoroutinefunction(endpoint), (
            f"admin handler {route.name!r} is async def; all admin "
            f"handlers must be sync (def) so the sync LocalPostgresExecutor "
            f"can run in the FastAPI threadpool without blocking the "
            f"event loop. Convert this handler to def."
        )
