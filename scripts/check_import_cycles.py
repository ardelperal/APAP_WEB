"""Import-cycle detector (issue #443, AGENTS.md §26).

Tarjan SCC over the app/ import graph. Cycles within app/ are reported;
imports from outside app/ are ignored. The shrink-only BASELINE freezes
today's cycles; new cycles fail.

The relevant helpers (``_file_module``, ``_resolve_relative``,
``extract_imports``) are duplicated from ``scripts/check_layers.py``
rather than imported, because ``check_layers.py`` is already at the
AGENTS.md §21 700-line cap (B1 refactor locked-in).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

SCAN_DIRS = ("app",)
INTERNAL_PREFIX = "app."

# Frozen 2026-08-07 against main @c0db19d. Each key is the canonical
# sorted-tuple of module paths in the cycle. Re-run with
# ``--emit-baseline`` to refresh as cycles are broken.
#
# Reason is a one-line label that explains why this cycle is in the
# baseline (e.g., "legacy lazy-import pending #420 slice").
#
# Most entries below are the same shape: a module imports a sibling
# (e.g. ``queries``) via the package root (``from app.modules.X import
# queries``), which forces Python to load ``__init__.py`` first, which
# in turn re-exports from ``service`` / ``routes``. Python survives the
# back-edge because the sibling is reached mid-init, but it is still a
# cycle. Breaking it means replacing the relative package import with a
# direct submodule import (e.g. ``from app.modules.X.queries import
# ...``) and auditing the cycle.
BASELINE: dict[tuple[str, ...], str] = {
    ("app.modules.acogidas", "app.modules.acogidas.routes", "app.modules.acogidas.service"):
        "service.py imports queries through the package root, routes.py imports service -- pre-hexagonal pattern, break when FOSTER-02 lands its slice (Refs #420)",
    ("app.modules.adopciones", "app.modules.adopciones.routes", "app.modules.adopciones.service"):
        "service.py imports queries through the package root, routes.py imports service -- pre-hexagonal pattern, break when ADOPT-01 lands its slice (Refs #420)",
    ("app.modules.entradas", "app.modules.entradas.batch_routes", "app.modules.entradas.routes"):
        "__init__ re-exports both routers (batch_router, router); both routers import back through the package root for their respective services -- tolerated mid-migration (Refs #420)",
    ("app.modules.foster", "app.modules.foster.assignment", "app.modules.foster.routes"):
        "assignment.py imports `foster.service` via the package root (line 46); __init__ re-exports assignment + service -- tolerated mid-migration (Refs #420)",
        ("app.modules.tasks", "app.modules.tasks.service"):
            "pre-existing cycle on main before the materiales refactor; service.py imports queries through the package root -- break when TASKS-01 lands its hexagonal slice",
        ("app.modules.sanidad", "app.modules.sanidad.scheduling", "app.modules.sanidad.service"):
        "scheduling.py uses ActuacionSanitaria type hint from service.py; service.py calls scheduling.schedule_periodic_task; break by using Any in scheduling.py type annotations (Refs #54)",
}


def _module_path(p: Path, root: Path) -> str:
    rel = p.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _extract_imports(path: Path) -> list[str]:
    """Return the list of top-level app.* modules imported by ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(INTERNAL_PREFIX):
                    out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith(INTERNAL_PREFIX):
                out.append(mod)
    return out


def _build_graph(root: Path) -> dict[str, set[str]]:
    """Map app-module -> set of app-modules it imports."""
    graph: dict[str, set[str]] = {}
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            mod = _module_path(path, root)
            targets = set(_extract_imports(path))
            targets.discard(mod)
            if targets:
                graph[mod] = targets
    return graph


def _pop_scc(stack: list[str], on_stack: set[str], root: str) -> list[str]:
    """Pop from ``stack`` until ``root`` is at the top; the popped nodes form one SCC."""
    scc: list[str] = []
    while True:
        w = stack.pop()
        on_stack.discard(w)
        scc.append(w)
        if w == root:
            return scc


def _tarjan_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    """Return every SCC of size > 1 in ``graph`` (Tarjan, recursive)."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = 0

    def assign(v: str) -> None:
        nonlocal counter
        indices[v] = lowlinks[v] = counter
        counter += 1
        stack.append(v)
        on_stack.add(v)

    def recurse(v: str) -> None:
        assign(v)
        for w in graph.get(v, ()):
            if w not in indices:
                recurse(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])
        if lowlinks[v] == indices[v]:
            scc = _pop_scc(stack, on_stack, v)
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for v in graph:
        if v not in indices:
            recurse(v)
    return sccs


def _cycle_key(cycle: list[str]) -> tuple[str, ...]:
    return tuple(sorted(cycle))


def _discover_cycles(root: Path) -> set[tuple[str, ...]]:
    """Return the canonical key for every import cycle in ``root``."""
    return {_cycle_key(c) for c in _tarjan_sccs(_build_graph(root))}


def check(
    root: Path, baseline: dict[tuple[str, ...], str] | None = None
) -> tuple[list[str], list[str]]:
    """Compare the cycles in ``root`` against ``baseline``.

    Returns ``(violations, notices)``. Violations fail the check;
    notices are informational (a baselined cycle disappeared and the
    entry should be deleted to lock in the improvement).
    """
    if baseline is None:
        baseline = BASELINE
    cycles = _discover_cycles(root)
    violations: list[str] = []
    for key in sorted(cycles):
        if key in baseline:
            continue
        violations.append(
            f"{' -> '.join(key)}: NEW import cycle. Break it (or add to BASELINE "
            f"with an explicit reason -- never to legitimise debt, only to "
            f"freeze a known cycle for a follow-up issue)."
        )
    notices = [
        f"{' -> '.join(key)}: baselined but no longer a cycle -- remove the entry "
        f"from BASELINE in scripts/check_import_cycles.py to lock in the improvement"
        for key in sorted(set(baseline) - cycles)
    ]
    return violations, notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-baseline", action="store_true")
    parser.add_argument("root", nargs="?", default=".")
    ns = parser.parse_args(args)

    root = Path(ns.root).resolve()

    if ns.emit_baseline:
        print("BASELINE = {")
        for key in sorted(_discover_cycles(root)):
            reason = "cycle frozen at this commit; see comment in BASELINE"
            print(f"    {key!r}: \"{reason}\",")
        print("}")
        return 0

    violations, _ = check(root, BASELINE)
    if violations:
        for v in violations:
            print(f"FAIL {v}")
        print(f"check_import_cycles: {len(violations)} violation(s).")
        return 1
    print(f"check_import_cycles: OK ({len(BASELINE)} baselined cycle(s) remaining)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
