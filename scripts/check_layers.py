"""Hexagonal layer + vertical-slice ratchet for APAP_WEB (AGENTS.md rule 33).

The hexagonal refactor is being built incrementally (one vertical slice
at a time: ``auth``, ``catalogos``, ``schema_bootstrap``, ...). This
checker is the harness that makes the direction of that build
irreversible: once a slice is ported, nothing can quietly import its way
back out of the architecture.

It enforces two independent axes over ``app/``:

**Axis 1 -- hexagonal dependency direction.** Every layer declares which
layers it may import (``ALLOWED_IMPORTS``). Dependencies point inward:
``domain`` knows nobody, ``application`` talks to ``domain`` and
``ports`` but never to ``adapters``, and only ``di`` (the composition
root) may see the whole graph. The analogue of dysflow's
``check-core-adapter-boundary.mjs``: the use-case layer must receive its
adapter implementations by injection, never by import.

**Axis 2 -- vertical slicing.** Each slice (``auth``, ``animals``, ...)
owns a column through the layers. A slice may not reach into another
slice's internals; cross-slice traffic goes through the other slice's
public package root, and inside ``app/core/**`` it does not happen at
all outside ``di``.

**Axis 3 -- inner-layer purity.** ``domain`` and ``application`` must not
import a web framework or a storage vendor (``fastapi``, ``insforge``,
``httpx``, ...). This generalises the per-slice invariants in
``tests/test_catalogos_slice.py`` so a *new* slice cannot forget them.

Layers that do not exist yet are simply not matched, so the gate is
green on a tree mid-migration and binds automatically the moment a slice
lands. Violations that predate the rule live in ``BASELINE``, which is a
**ratchet**: entries may only disappear. A new violation always fails.

Usage::

    python scripts/check_layers.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic,
path-separator-safe (keys are POSIX-style relative paths).

Run locally before pushing; CI runs it in the ``lint`` job (pinned by
``tests/test_layers.py::test_ci_workflow_lint_job_runs_layers_gate``).

Tests: ``tests/test_layers.py``.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

#: Root package under which the architecture is enforced.
ROOT_PACKAGE = "app"

#: Directories (relative to the scanned root) subject to the rules.
#: Only ``app/`` -- ``migration/`` is a standalone ETL tool with its own
#: runtime boundary (tests/migration/test_runtime_boundary.py), and
#: tests/ + scripts/ are tooling, not product architecture.
SCAN_DIRS = ("app",)

# ---------------------------------------------------------------------------
# Axis 1 -- layers
# ---------------------------------------------------------------------------

#: Layers from innermost to outermost. Used only for error messages;
#: the real contract is ALLOWED_IMPORTS, which is explicit on purpose --
#: an ordering alone cannot express that ``adapters`` may see ``ports``
#: while ``application`` may not see ``adapters``.
LAYER_ORDER = (
    "domain",
    "ports",
    "application",
    "adapters",
    "infrastructure",
    "di",
    "delivery",
)

#: The contract. ``ALLOWED_IMPORTS[layer]`` is the complete set of
#: layers a file in ``layer`` may import from. Anything else is a
#: violation. A layer always implicitly allows itself.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    # The centre. Entities and invariants, no outbound knowledge at all.
    "domain": frozenset({"domain"}),
    # Protocols. They speak in domain types and nothing else.
    "ports": frozenset({"domain", "ports"}),
    # Use cases. They orchestrate domain objects behind port Protocols.
    # NOT "adapters": that is the whole point of the hexagon -- the
    # implementation arrives by injection from di, never by import.
    "application": frozenset({"domain", "ports", "application"}),
    # Driven side. Implements ports against a concrete vendor, so it
    # needs the vendor client that lives in infrastructure.
    "adapters": frozenset({"domain", "ports", "adapters", "infrastructure"}),
    # Cross-cutting technical services (session, csrf, logging, the
    # InsForge client itself). May depend on the port Protocols it
    # implements against, never on use cases or delivery.
    "infrastructure": frozenset({"domain", "ports", "infrastructure"}),
    # Composition root. The one place allowed to see the whole graph
    # and wire an adapter into a use case.
    "di": frozenset(
        {"domain", "ports", "application", "adapters", "infrastructure", "di"}
    ),
    # Driving side: FastAPI routes, templates, the app factory.
    # Outermost, so it may reach anything inward.
    "delivery": frozenset(LAYER_ORDER),
}

#: Layers that must stay free of web frameworks and storage vendors.
PURE_LAYERS = frozenset({"domain", "ports", "application"})

#: Top-level third-party packages banned inside PURE_LAYERS. Matched on
#: the first dotted segment, so ``fastapi.responses`` is caught too.
FORBIDDEN_IN_PURE_LAYERS = frozenset(
    {
        "fastapi",
        "starlette",
        "jinja2",
        "httpx",
        "requests",
        "insforge",
        "sqlalchemy",
        "psycopg",
        "psycopg2",
    }
)

# ---------------------------------------------------------------------------
# Axis 2 -- vertical slices
# ---------------------------------------------------------------------------

#: Layer directories under ``app/core/`` whose immediate child package
#: names a vertical slice (``app/core/application/auth/...``).
SLICE_BY_SUBPACKAGE = ("domain", "application", "adapters")

#: Layer directories under ``app/core/`` whose *file* names carry the
#: slice, with the given suffix (``app/core/ports/auth_port.py``).
SLICE_BY_FILE_SUFFIX = {
    "ports": "_port",
    "di": "_di",
}

#: Layers exempt from the cross-slice rule. ``di`` is the composition
#: root: wiring slice A's adapter into slice A's use case is its job,
#: and a request-scoped provider legitimately touches several slices.
SLICE_EXEMPT_LAYERS = frozenset({"di"})

#: Packages under ``app/core/`` that hold domain entities but have not
#: been moved under ``app/core/domain/`` yet. ``catalogos`` is frozen
#: dataclasses ("Domain entity for a Motivo catalog entry"), so treating
#: it as infrastructure would wrongly flag every port and use case that
#: legitimately speaks in those types. The package name is also the
#: slice name. Entries disappear as the packages are relocated.
LEGACY_DOMAIN_PACKAGES = frozenset({"catalogos"})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_layer(rel_posix: str) -> str | None:
    """Map a repo-relative POSIX path to its architectural layer.

    Returns ``None`` for files outside the architecture (static
    assets, templates, ``__init__.py`` of the root package).

    Legacy flat modules are classified by name so the pre-hexagonal
    tree is covered too: ``app/core/domain*.py`` is domain,
    ``app/core/data_access.py`` holds the ``SqlExecutor`` Protocol and
    the Protocol-level exception hierarchy, so it is a port.
    """
    if not rel_posix.endswith(".py"):
        return None
    parts = rel_posix.split("/")
    if parts[0] != ROOT_PACKAGE:
        return None

    if len(parts) >= 2 and parts[1] == "modules":
        return "delivery"
    if len(parts) == 2:
        # app/main.py, app/routes_registry.py, app/__init__.py
        return "delivery"
    if parts[1] != "core":
        return None
    if len(parts) == 3 and parts[2] == "__init__.py":
        # The `app.core` package root itself is a namespace, not a layer.
        return None

    # app/core/<something>/...
    if len(parts) >= 4:
        candidate = parts[2]
        if candidate in ALLOWED_IMPORTS:
            return candidate
        if candidate in LEGACY_DOMAIN_PACKAGES:
            return "domain"
        return "infrastructure"

    # app/core/<file>.py -- the legacy flat layout.
    stem = parts[2].removesuffix(".py")
    if stem == "domain" or stem.startswith("domain_"):
        return "domain"
    if stem == "data_access":
        return "ports"
    return "infrastructure"


def classify_slice(rel_posix: str, layer: str | None) -> str | None:
    """Map a repo-relative POSIX path to its vertical slice, if any."""
    if layer is None:
        return None
    parts = rel_posix.split("/")

    if layer == "delivery":
        # app/modules/<slice>/...
        if len(parts) >= 3 and parts[1] == "modules":
            return parts[2]
        return None

    if len(parts) < 4 or parts[1] != "core":
        return None
    stem = parts[-1].removesuffix(".py")
    if stem == "__init__" and layer != "domain":
        # A layer's package root re-exports every slice it contains, so
        # it belongs to no single slice.
        if len(parts) < 5:
            return None

    if parts[2] in LEGACY_DOMAIN_PACKAGES:
        return parts[2]

    if layer in SLICE_BY_SUBPACKAGE:
        if layer == "adapters":
            # app/core/adapters/<vendor>/<slice>_<vendor>_<role>.py --
            # split on the vendor segment, not on the first underscore,
            # or `schema_bootstrap_insforge_adapter` reads as `schema`.
            vendor = parts[3]
            marker = f"_{vendor}"
            if len(parts) >= 5 and marker in stem:
                return stem.split(marker, 1)[0] or None
            return None
        # app/core/{domain,application}/<slice>/...
        return parts[3] if len(parts) >= 5 else None

    suffix = SLICE_BY_FILE_SUFFIX.get(layer)
    if suffix is not None and stem.endswith(suffix):
        return stem.removesuffix(suffix)
    return None


def module_to_rel_paths(module: str) -> tuple[str, str]:
    """Return the two candidate paths a dotted module could live at."""
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def resolve_module(root: Path, module: str) -> str | None:
    """Resolve a dotted module to the repo-relative file that defines it.

    Returns ``None`` when nothing on disk matches. This is what keeps
    the checker honest: ``from app.core.domain_lifecycle import
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL`` produces the candidate
    ``app.core.domain_lifecycle.ANIMAL_...``, which is a *symbol*, not a
    module. Only a candidate that resolves to a real file or package is
    treated as an architectural edge -- the same discipline as resolving
    an import through the language's own module resolver instead of
    matching strings.
    """
    if module.split(".")[0] != ROOT_PACKAGE:
        return None
    file_path, package_path = module_to_rel_paths(module)
    for candidate in (file_path, package_path):
        if (root / candidate).is_file():
            return candidate
    return None


def classify_module(root: Path, module: str) -> tuple[str | None, str | None]:
    """Classify an imported dotted module into ``(layer, slice)``."""
    resolved = resolve_module(root, module)
    if resolved is None:
        return None, None
    layer = classify_layer(resolved)
    if layer is None:
        return None, None
    return layer, classify_slice(resolved, layer)


def _resolve_relative(module: str | None, level: int, file_module: str) -> str | None:
    """Resolve a ``from .. import x`` specifier to an absolute module."""
    if level == 0:
        return module
    package_parts = file_module.split(".")[:-1]
    if level > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - level + 1]
    if module:
        base = [*base, *module.split(".")]
    return ".".join(base) if base else None


def _file_module(rel_posix: str) -> str:
    stem = rel_posix.removesuffix(".py")
    if stem.endswith("/__init__"):
        stem = stem.removesuffix("/__init__")
    return stem.replace("/", ".")


def extract_imports(source: str, file_module: str) -> list[tuple[str, int]]:
    """Return ``(absolute_module, lineno)`` for every import in ``source``.

    ``from app.modules.foster import assignment_service`` yields both
    the package (``app.modules.foster``) and the candidate submodule
    (``app.modules.foster.assignment_service``) so the slice rule can
    tell a public-package import from an internals import. The
    submodule candidate is only reported when it resolves to a real
    layer, so importing a plain symbol is never mistaken for one.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative(node.module, node.level, file_module)
            if resolved is None:
                continue
            found.append((resolved, node.lineno))
            found.extend(
                (f"{resolved}.{alias.name}", node.lineno)
                for alias in node.names
                if alias.name != "*"
            )
    return found


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def violation_key(rel_posix: str, rule_id: str, target: str) -> str:
    """Build the stable BASELINE key for a violation.

    Deliberately excludes the line number: moving an import inside a
    file must not require re-baselining, and the ratchet cares about
    *which* forbidden edge exists, not where it is written.
    """
    return f"{rel_posix} -> {target} [{rule_id}]"


def _check_layer_direction(
    rel: str, layer: str, module: str, target_layer: str
) -> tuple[str, str] | None:
    if target_layer in ALLOWED_IMPORTS[layer]:
        return None
    if layer == "application" and target_layer == "adapters":
        hint = (
            "the use-case layer must receive adapters by injection from "
            "app/core/di/, never import them"
        )
    elif target_layer == "delivery":
        hint = "inner layers must not know about routes/templates (dependency inversion)"
    elif layer == "domain":
        hint = "the domain is the centre of the hexagon: it imports nothing but domain"
    else:
        hint = f"{layer} may only import {', '.join(sorted(ALLOWED_IMPORTS[layer]))}"
    return violation_key(rel, "layer-direction", module), (
        f"{rel}: {layer} imports {module} ({target_layer}) -- {hint}"
    )


def _check_purity(rel: str, layer: str, module: str) -> tuple[str, str] | None:
    if layer not in PURE_LAYERS:
        return None
    top = module.split(".")[0]
    if top not in FORBIDDEN_IN_PURE_LAYERS:
        return None
    return violation_key(rel, "layer-purity", top), (
        f"{rel}: {layer} imports the third-party package '{top}' -- "
        f"{', '.join(sorted(PURE_LAYERS))} must stay free of web frameworks "
        f"and storage vendors; put it behind a port in app/core/ports/"
    )


def _check_slice(
    rel: str,
    layer: str,
    own_slice: str | None,
    module: str,
    target_layer: str,
    target_slice: str | None,
) -> tuple[str, str] | None:
    if own_slice is None or target_slice is None or own_slice == target_slice:
        return None
    if layer in SLICE_EXEMPT_LAYERS or target_layer in SLICE_EXEMPT_LAYERS:
        return None

    if layer == "delivery" and target_layer == "delivery":
        # Cross-module traffic is allowed, but only through the other
        # module's public package root: `from app.modules.foster import x`,
        # never `from app.modules.foster.service import x`.
        depth = len(module.split("."))
        if depth <= 3:
            return None
        return violation_key(rel, "slice-internals", module), (
            f"{rel}: slice '{own_slice}' imports slice '{target_slice}' internals "
            f"({module}) -- import from the package root "
            f"'app.modules.{target_slice}' and let that slice choose what it "
            f"exposes"
        )

    return violation_key(rel, "slice-boundary", module), (
        f"{rel}: slice '{own_slice}' ({layer}) imports slice '{target_slice}' "
        f"({module}) -- vertical slices own their column through the layers; "
        f"compose them in app/core/di/ instead"
    )


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

#: Violations that predate the gate being switched on (issue #436), each
#: mapped to why it still exists.
#: RATCHET: entries may only disappear. When you fix one, delete its entry
#: in the same PR -- tests/test_layers.py::
#: test_baseline_entries_are_still_real_violations fails on a stale entry,
#: and any violation not listed here fails the gate. Never add a new entry:
#: fix the import instead.
#:
#: Measured against origin/main @41fbd2a: 53 violations (40 layer-direction,
#: 10 slice-boundary, 3 layer-purity). The previous 4-entry baseline was
#: calibrated against an unmerged local refactor and left the gate red on
#: main, which is why it never ran in CI.
_EPIC_420 = (
    "app/core/ is mid-migration to the hexagon (epic #420); this edge predates "
    "the gate. Delete the entry as the owning slice lands."
)

_LAZY_CYCLE = (
    "CLI-only lazy import that dodges a module-load cycle (AGENTS.md \u00a726); "
    "resolved when the tasks slice grows an application layer."
)

BASELINE: Mapping[str, str] = {
    "app/core/adapters/insforge/auth_insforge_adapter.py -> app.core.application.auth._domain_errors [layer-direction]": _EPIC_420,
    "app/core/admin_handlers.py -> app.core.adapters.admin_template_adapter [layer-direction]": _EPIC_420,
    "app/core/admin_handlers.py -> app.core.application.admin.add_user [layer-direction]": _EPIC_420,
    "app/core/admin_handlers.py -> app.core.application.admin.deactivate_user [layer-direction]": _EPIC_420,
    "app/core/admin_handlers.py -> app.core.application.admin.render_admin_panel [layer-direction]": _EPIC_420,
    "app/core/admin_handlers.py -> app.core.di.admin_di [layer-direction]": _EPIC_420,
    "app/core/admin_handlers.py -> app.core.di.auth_di [layer-direction]": _EPIC_420,
    "app/core/application/admin/add_user.py -> app.core.adapters.admin_template_adapter [layer-direction]": _EPIC_420,
    "app/core/application/admin/add_user.py -> app.core.admin_helpers [layer-direction]": _EPIC_420,
    "app/core/application/admin/add_user.py -> app.core.application.auth.add_authorized_user [slice-boundary]": _EPIC_420,
    "app/core/application/admin/add_user.py -> app.core.domain.auth.rol [slice-boundary]": _EPIC_420,
    "app/core/application/admin/add_user.py -> app.core.ports.auth_port [slice-boundary]": _EPIC_420,
    "app/core/application/admin/add_user.py -> fastapi [layer-purity]": _EPIC_420,
    "app/core/application/admin/deactivate_user.py -> app.core.adapters.admin_template_adapter [layer-direction]": _EPIC_420,
    "app/core/application/admin/deactivate_user.py -> app.core.application.auth.deactivate_authorized_user [slice-boundary]": _EPIC_420,
    "app/core/application/admin/deactivate_user.py -> app.core.ports.auth_port [slice-boundary]": _EPIC_420,
    "app/core/application/admin/deactivate_user.py -> fastapi [layer-purity]": _EPIC_420,
    "app/core/application/admin/render_admin_panel.py -> app.core.adapters.admin_template_adapter [layer-direction]": _EPIC_420,
    "app/core/application/admin/render_admin_panel.py -> app.core.ports.auth_port [slice-boundary]": _EPIC_420,
    "app/core/application/admin/render_admin_panel.py -> fastapi [layer-purity]": _EPIC_420,
    "app/core/application/auth/add_authorized_user.py -> app.core.auth_cache [layer-direction]": _EPIC_420,
    "app/core/application/auth/add_authorized_user.py -> app.core.auth_helpers [layer-direction]": _EPIC_420,
    "app/core/application/auth/deactivate_authorized_user.py -> app.core.auth_cache [layer-direction]": _EPIC_420,
    "app/core/application/auth/ensure_schema_and_seed.py -> app.core.config [layer-direction]": _EPIC_420,
    "app/core/application/auth/get_user_by_email.py -> app.core.auth_helpers [layer-direction]": _EPIC_420,
    "app/core/application/oauth/callback.py -> app.core.domain.auth.user [slice-boundary]": _EPIC_420,
    "app/core/application/oauth/callback.py -> app.core.ports.auth_port [slice-boundary]": _EPIC_420,
    "app/core/application/oauth/login_page.py -> app.core.config [layer-direction]": _EPIC_420,
    "app/core/application/oauth/logout.py -> app.core.session [layer-direction]": _EPIC_420,
    "app/core/application/oauth/start_google_login.py -> app.core.config [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.adapters.insforge.auth_insforge_adapter [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth._has_other_active_developers [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth.add_authorized_user [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth.deactivate_authorized_user [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth.ensure_schema_and_seed [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth.get_user_by_email [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth.get_user_by_id [layer-direction]": _EPIC_420,
    "app/core/auth.py -> app.core.application.auth.list_authorized_users [layer-direction]": _EPIC_420,
    "app/core/auth_dependencies.py -> app.core.di.auth_dependencies_di [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.adapters.insforge.auth_insforge_adapter [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.adapters.insforge.oauth_insforge_adapter [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.application.oauth [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.application.oauth.callback [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.application.oauth.login_page [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.application.oauth.logout [layer-direction]": _EPIC_420,
    "app/core/auth_flow.py -> app.core.application.oauth.start_google_login [layer-direction]": _EPIC_420,
    "app/core/domain/__init__.py -> app.core.adapters.insforge.schema_bootstrap_insforge_adapter [layer-direction]": _EPIC_420,
    "app/core/domain/__init__.py -> app.core.insforge [layer-direction]": _EPIC_420,
    "app/core/domain/auth/rol.py -> app.core.roles [layer-direction]": _EPIC_420,
    "app/core/domain/oauth/session.py -> app.core.domain.auth.rol [slice-boundary]": _EPIC_420,
    "app/core/domain/oauth/session.py -> app.core.domain.auth.user [slice-boundary]": _EPIC_420,
    "app/core/tasks/scheduler.py -> app.modules.tasks [layer-direction]": _LAZY_CYCLE,
    "app/core/tasks/scheduler.py -> app.modules.tasks.service [layer-direction]": _LAZY_CYCLE,
}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(
            path for path in base.rglob("*.py") if "__pycache__" not in path.parts
        )
    return sorted(files)


def check_tree(
    root: Path, *, baseline: Mapping[str, str] | None = None
) -> tuple[list[str], list[str]]:
    """Check every module under ``root``'s SCAN_DIRS against the contract.

    Returns ``(violations, notices)``. Violations fail the check;
    notices are informational (a baselined violation disappeared and the
    entry should be deleted to lock in the improvement).
    """
    if baseline is None:
        baseline = BASELINE
    violations: list[str] = []
    seen_baselined: set[str] = set()
    reported: set[str] = set()

    for path in _iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        layer = classify_layer(rel)
        if layer is None:
            continue
        own_slice = classify_slice(rel, layer)
        file_module = _file_module(rel)
        source = path.read_text(encoding="utf-8")

        for module, _lineno in extract_imports(source, file_module):
            target_layer, target_slice = classify_module(root, module)
            results = []
            if target_layer is None:
                results.append(_check_purity(rel, layer, module))
            else:
                results.append(
                    _check_layer_direction(rel, layer, module, target_layer)
                )
                results.append(
                    _check_slice(
                        rel, layer, own_slice, module, target_layer, target_slice
                    )
                )

            for result in results:
                if result is None:
                    continue
                key, message = result
                if key in baseline:
                    seen_baselined.add(key)
                    continue
                if key in reported:
                    continue
                reported.add(key)
                violations.append(message)

    notices = [
        f"{key}: baselined but no longer a violation -- remove the entry from "
        f"BASELINE in scripts/check_layers.py to lock in the improvement"
        for key in sorted(set(baseline) - seen_baselined)
    ]
    return sorted(violations), notices


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    violations, notices = check_tree(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_layers: {len(violations)} violation(s). The hexagon points "
            f"inward and slices own their column (AGENTS.md rule 33; see "
            f"docs/architecture/capas-y-slices.md)."
        )
        return 1
    print(f"check_layers: OK ({len(BASELINE)} baselined violation(s) remaining)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
