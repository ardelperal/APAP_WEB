"""Slice-completeness gate for APAP_WEB (AGENTS.md rule 33, hardening Step 2).

Companion to ``scripts/check_layers.py``: that ratchet proves "no
forbidden import"; this one proves a slice is structurally complete.
Four assertions per slice:

1. ``port-declared`` -- a Protocol lives in ports/<slice>_port.py.
2. ``adapter-in-di`` -- the concrete adapter is wired from di/<slice>_di.py.
3. ``application-adapter-free`` -- application/<slice>/** never imports
   a concrete adapter (slice-scoped re-assertion of check_layers.py's
   rule, with finer keys).
4. ``tests-per-layer`` -- every layer the slice occupies has at least one
   matching test file.

Slices that predate the gate live in ``BASELINE`` (shrink-only, same
contract as ``check_module_size.py:46``).

A slice is in scope iff it occupies at least one of ``application``,
``ports``, ``adapters``, ``delivery``. Di-only slices (e.g. the
auxiliary ``app/core/di/auth_dependencies_di.py``) and domain-only
slices are excluded -- they are parts of other slices, not slices.

Usage::

    python scripts/check_slice_completeness.py [root]
    python scripts/check_slice_completeness.py --emit-baseline

Exit 0 on clean. Stdlib-only, deterministic, path-separator safe. Pinned
by ``tests/test_slice_completeness.py::test_ci_workflow_lint_job_runs_slice_completeness_gate``.

Design: ``docs/quality/slice-completeness-design.md``.
"""
from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

DEPTH_AT_SEGMENT_1 = 2
DEPTH_AT_SEGMENT_2 = 3
DEPTH_AT_SEGMENT_3 = 4
DEPTH_AT_SEGMENT_4 = 5

SCAN_DIRS = ("app",)
PORTS_FILENAME_SUFFIX = "_port"
DI_FILENAME_SUFFIX = "_di"
TESTS_DIR = "tests"

#: An adapter file is any ``<slice>_*_adapter*.py`` in the adapters layer.
#: SQL-queries siblings (``<slice>_<vendor>_queries.py``) are imported
#: by the adapter itself, not by di, and are excluded.
ADAPTER_FRAGMENT = "_adapter"

#: Layers under app/core whose immediate child package names a slice
#: (mirrors scripts/check_layers.py:137).
SLICE_BY_SUBPACKAGE = ("domain", "application", "adapters")

#: Layer directories whose file names carry the slice via a suffix
#: (mirrors scripts/check_layers.py:141).
SLICE_BY_FILE_SUFFIX = {
    "ports": PORTS_FILENAME_SUFFIX,
    "di": DI_FILENAME_SUFFIX,
}

#: Packages under app/core that hold domain entities but have not yet
#: been moved under app/core/domain/. Mirrors scripts/check_layers.py:157.
LEGACY_DOMAIN_PACKAGES = frozenset({"catalogos"})

#: Slices occupying ONLY the di layer are auxiliary composition helpers
#: (e.g. app/core/di/auth_dependencies_di.py). They are excluded.
DI_ONLY_EXCLUDED = True

#: A slice layer set considered "in scope": domain is optional, the
#: rest means the slice has something to wire.
SCOPE_LAYERS = frozenset(
    {"domain", "ports", "application", "adapters", "infrastructure",
     "di", "delivery"}
)


# ---------------------------------------------------------------------------
# Slice classification (mirrors check_layers.py so the two ratchets
# agree on what a slice is for a given file).
# ---------------------------------------------------------------------------


def _classify_app_core_by_layer_segment(candidate: str) -> str:
    if candidate in SCOPE_LAYERS:
        return candidate
    if candidate in LEGACY_DOMAIN_PACKAGES:
        return "domain"
    return "infrastructure"


def _classify_app_core_flat(parts: list[str]) -> str | None:
    """Classify a flat ``app/core/<file>.py`` (DEPTH_AT_SEGMENT_2)."""
    if parts[2] == "__init__.py":
        return None
    stem = parts[2].removesuffix(".py")
    if stem == "data_access":
        return "ports"
    if stem == "domain" or stem.startswith("domain_"):
        return "domain"
    return "infrastructure"


def classify_layer(rel_posix: str) -> str | None:
    """Map a repo-relative POSIX path to its architectural layer.

    Mirrors ``scripts/check_layers.py:218``. The duplication is
    deliberate: a shared helper module could drift the two ratchets
    independently, and ``check_layers.py`` cannot be touched (its 673
    lines are pinned against the §21 700-line cap; issue #436).
    """
    parts = rel_posix.split("/")
    if not rel_posix.endswith(".py") or parts[0] != "app":
        return None
    if len(parts) < DEPTH_AT_SEGMENT_1:
        return None
    if parts[1] == "modules":
        return "delivery"
    if parts[1] != "core":
        return None
    if len(parts) >= DEPTH_AT_SEGMENT_3:
        return _classify_app_core_by_layer_segment(parts[2])
    return _classify_app_core_flat(parts)


def classify_slice(rel_posix: str, layer: str | None) -> str | None:
    """Map a file path to its vertical slice, if any.

    Mirrors ``scripts/check_layers.py:277``. Package roots
    (``app/modules/__init__.py``, ``app/core/<layer>/__init__.py``)
    return ``None`` -- they are namespaces, not slice members.
    """
    if layer is None:
        return None
    parts = rel_posix.split("/")
    if layer == "delivery":
        return _slice_from_delivery(parts)
    if len(parts) < DEPTH_AT_SEGMENT_3 or parts[1] != "core":
        return None
    return _slice_from_app_core(parts, layer)


def _slice_from_delivery(parts: list[str]) -> str | None:
    if len(parts) < DEPTH_AT_SEGMENT_2 or parts[1] != "modules":
        return None
    if parts[2].startswith("__"):
        return None
    return parts[2]


def _slice_from_app_core(parts: list[str], layer: str) -> str | None:
    stem = parts[-1].removesuffix(".py")
    if (
        stem == "__init__"
        and layer != "domain"
        and len(parts) < DEPTH_AT_SEGMENT_4
    ):
        return None
    if parts[2] in LEGACY_DOMAIN_PACKAGES:
        return parts[2]
    if layer in SLICE_BY_SUBPACKAGE:
        return _slice_from_subpackage(parts, stem, layer)
    suffix = SLICE_BY_FILE_SUFFIX.get(layer)
    if suffix is not None and stem.endswith(suffix):
        return stem.removesuffix(suffix)
    return None


def _slice_from_subpackage(parts: list[str], stem: str, layer: str) -> str | None:
    if layer == "adapters":
        vendor = parts[3]
        marker = f"_{vendor}"
        if len(parts) >= DEPTH_AT_SEGMENT_4 and marker in stem:
            return stem.split(marker, 1)[0] or None
        return None
    if len(parts) >= DEPTH_AT_SEGMENT_4:
        return parts[3]
    return None


# ---------------------------------------------------------------------------
# Slice discovery
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(
            path for path in base.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(files)


def discover_slices(root: Path) -> dict[str, dict[str, set[str]]]:
    """Return ``{slice_name: {layer: {files}}}`` for every in-scope slice.

    Auxiliary di-only slices (the only layer is ``di``) are removed --
    they are composition helpers, not slices in their own right.
    """
    raw: dict[str, dict[str, set[str]]] = {}
    for path in _iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        layer = classify_layer(rel)
        if layer is None:
            continue
        slice_name = classify_slice(rel, layer)
        if slice_name is None:
            continue
        raw.setdefault(slice_name, {}).setdefault(layer, set()).add(rel)

    out: dict[str, dict[str, set[str]]] = {}
    for slice_name, by_layer in raw.items():
        if DI_ONLY_EXCLUDED and set(by_layer) == {"di"}:
            continue
        if not by_layer:
            continue
        out[slice_name] = by_layer
    return out


# ---------------------------------------------------------------------------
# Assertion 1 -- port-declared
# ---------------------------------------------------------------------------


def _expected_ports_path(slice_name: str) -> str:
    return f"app/core/ports/{slice_name}{PORTS_FILENAME_SUFFIX}.py"


def _file_declares_protocol(rel_posix: str, root: Path) -> bool:
    """Return ``True`` when ``rel_posix`` contains a Protocol class.

    Accepts ``class X(Protocol)`` (typing.Protocol or a re-imported
    alias) or ``@runtime_checkable`` on a class with at least one
    base. The decorator alone is not enough -- the Protocol call site
    needs a concrete type to register against.
    """
    full = root / rel_posix
    if not full.is_file():
        return False
    try:
        tree = ast.parse(full.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        has_protocol_base = any(
            _base_name(base) == "Protocol" for base in node.bases
        )
        if has_protocol_base:
            return True
        has_runtime = any(
            isinstance(dec, ast.Name) and dec.id == "runtime_checkable"
            for dec in node.decorator_list
        )
        if has_runtime and node.bases:
            return True
    return False


def _base_name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def check_port_declared(
    root: Path, inventory: dict[str, dict[str, set[str]]]
) -> list[tuple[str, str]]:
    """Every slice with a port file must declare a Protocol inside it."""
    out: list[tuple[str, str]] = []
    for slice_name, by_layer in sorted(inventory.items()):
        ports_files = by_layer.get("ports", set())
        if ports_files:
            ok = any(_file_declares_protocol(f, root) for f in ports_files)
            if ok:
                continue
            out.append(
                (
                    f"port-declared::{slice_name}",
                    f"slice '{slice_name}': no Protocol in any ports file "
                    f"({', '.join(sorted(ports_files))}) -- "
                    f"ports/<slice>_port.py must declare at least one "
                    f"typing.Protocol",
                )
            )
            continue
        non_delivery = {
            layer
            for layer in by_layer
            if layer in {"application", "adapters", "di", "infrastructure"}
        }
        if non_delivery:
            expected = _expected_ports_path(slice_name)
            out.append(
                (
                    f"port-declared::{slice_name}",
                    f"slice '{slice_name}': missing ports file {expected} "
                    f"-- every slice with a non-delivery layer must "
                    f"declare a Protocol in app/core/ports/",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Assertion 2 -- adapter-in-di
# ---------------------------------------------------------------------------


def _expected_di_path(slice_name: str) -> str:
    return f"app/core/di/{slice_name}{DI_FILENAME_SUFFIX}.py"


def _is_adapter_file(rel: str) -> bool:
    """An adapter file is ``<slice>_*adapter*.py`` under the adapters layer.

    Queries modules (``<slice>_<vendor>_queries.py``) and ``__init__``
    files are excluded -- queries are imported by adapters, not by di.
    """
    if not rel.startswith("app/core/adapters/"):
        return False
    if rel.endswith("/__init__.py"):
        return False
    stem = rel.removesuffix(".py").split("/")[-1]
    return ADAPTER_FRAGMENT in stem


def _module_path_for(rel: str) -> str:
    """Convert ``app/core/adapters/local-backend/foo.py`` to its dotted module."""
    return rel.removesuffix(".py").replace("/", ".")


def _di_imports_module(di_source: str, dotted_module: str) -> bool:
    """True when ``di_source`` has any import targeting ``dotted_module``.

    Matches ``import x.y``, ``from x.y import z``, and the
    ``from a.b import c`` form whose full ``a.b.c`` is the target.
    The match is prefix-based so partial renames never matter.
    """
    target_parts = tuple(dotted_module.split("."))
    try:
        tree = ast.parse(di_source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            tuple(alias.name.split("."))[: len(target_parts)] == target_parts
            for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _from_import_hits(node, target_parts)
        ):
            return True
    return False


def _from_import_hits(node: ast.ImportFrom, target_parts: tuple[str, ...]) -> bool:
    """True when ``from <node.module> import <names>`` mentions target_parts."""
    base = node.module or ""
    base_parts = tuple(base.split("."))
    if base_parts[: len(target_parts)] == target_parts:
        return True
    return any(
        tuple((base + "." + alias.name).split("."))[: len(target_parts)]
        == target_parts
        for alias in node.names
    )


def check_adapter_in_di(
    root: Path, inventory: dict[str, dict[str, set[str]]]
) -> list[tuple[str, str]]:
    """Every concrete adapter file must be referenced from ``di/<slice>_di.py``.

    Skipped for slices whose only layer is delivery (module slices
    have no own adapter -- they consume core ports by injection).
    """
    out: list[tuple[str, str]] = []
    for slice_name, by_layer in sorted(inventory.items()):
        adapter_files = {
            f for f in by_layer.get("adapters", set()) if _is_adapter_file(f)
        }
        if not adapter_files:
            continue
        di_file = _expected_di_path(slice_name)
        di_full = root / di_file
        if not di_full.is_file():
            out.append(
                (
                    f"adapter-in-di::{slice_name}::",
                    f"slice '{slice_name}': adapters exist "
                    f"({', '.join(sorted(adapter_files))}) but no di file at "
                    f"{di_file}",
                )
            )
            continue
        di_source = di_full.read_text(encoding="utf-8")
        for adapter in sorted(adapter_files):
            module_path = _module_path_for(adapter)
            if not _di_imports_module(di_source, module_path):
                out.append(
                    (
                        f"adapter-in-di::{slice_name}::{adapter}",
                        f"slice '{slice_name}': adapter {adapter} is not "
                        f"referenced from {di_file} -- the composition "
                        f"root must wire every concrete adapter it "
                        f"instantiates",
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Assertion 3 -- application-adapter-free
# ---------------------------------------------------------------------------


def _forbidden_adapter_prefixes(slice_name: str) -> list[str]:
    """Dotted module prefixes ``application/<slice>/**`` must avoid."""
    return [
        f"app.core.adapters.{slice_name}_",
        f"app.core.adapters.local_backend.{slice_name}_",
    ]


def _import_module_target(node: ast.AST) -> str | None:
    """Return the dotted absolute module string for an Import/ImportFrom."""
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
        return names[0] if names else None
    if isinstance(node, ast.ImportFrom):
        if node.module is None:
            return None
        names = [alias.name for alias in node.names]
        if not names:
            return node.module
        return f"{node.module}.{names[0]}"
    return None


def check_application_adapter_free(
    root: Path, inventory: dict[str, dict[str, set[str]]]
) -> list[tuple[str, str]]:
    """``application/<slice>/**`` must not import a concrete adapter.

    This is the slice-scoped form of ``check_layers.py``'s rule. The
    finer key makes a passing-with-baseline scenario pointed enough
    to act on.
    """
    out: list[tuple[str, str]] = []
    for slice_name, by_layer in sorted(inventory.items()):
        app_files = by_layer.get("application", set())
        if not app_files:
            continue
        forbidden_prefixes = _forbidden_adapter_prefixes(slice_name)
        for rel in sorted(app_files):
            full = root / rel
            try:
                source = full.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                target = _import_module_target(node)
                if target is None:
                    continue
                if any(target.startswith(p) for p in forbidden_prefixes):
                    out.append(
                        (
                            f"application-adapter-free::{rel}",
                            f"slice '{slice_name}': {rel} imports concrete "
                            f"adapter '{target}' from application layer -- "
                            f"the use case must depend on a Protocol, never "
                            f"on the concrete adapter; inject the port instead",
                        )
                    )
                    break
    return out


# ---------------------------------------------------------------------------
# Assertion 4 -- tests-per-layer
# ---------------------------------------------------------------------------


def _slice_centric_match(stem: str, slice_name: str) -> bool:
    """True when ``stem`` is any ``test_<slice>*`` variant.

    Permissive: ``test_<slice>.py``, ``test_<slice>_slice.py``,
    ``test_<slice>_*.py`` -- all accepted as "the slice is being
    tested somewhere". A failure mode of this breadth is that a test
    that does NOT actually exercise the layer still counts; that
    failure mode is the mutation gate's job (issue #433, §34), not
    this one's -- this gate is structural.
    """
    test_prefix = f"test_{slice_name}"
    return (
        stem in {test_prefix, f"{test_prefix}_slice"}
        or stem.startswith(f"{test_prefix}_")
    )


def _layer_specific_match(stem: str, slice_name: str, layer: str) -> bool:
    """Per-layer recognition: precise ``test_<slice>_<layer>.py`` match only."""
    return stem in {f"test_{slice_name}_{layer}", f"test_{layer}_{slice_name}"}


def _slice_has_any_test(test_files: list[str], slice_name: str) -> bool:
    return any(
        _slice_centric_match(t.removesuffix(".py"), slice_name)
        for t in test_files
    )


def check_tests_per_layer(
    root: Path, inventory: dict[str, dict[str, set[str]]]
) -> list[tuple[str, str]]:
    """For each (slice, layer) occupied, find at least one test file.

    Per-layer: a precise ``tests/test_<slice>_<layer>.py`` match is
    the only way to claim that specific layer is tested. Fallback
    for a slice with no per-layer file: the slice-level integration
    test (``test_<slice>_slice.py``) or any ``test_<slice>_*`` file
    covers the layer -- integration coverage is acceptable because
    every per-layer test in this codebase that targets a slice also
    reaches its siblings.
    """
    out: list[tuple[str, str]] = []
    tests_dir = root / TESTS_DIR
    if not tests_dir.is_dir():
        for slice_name, by_layer in sorted(inventory.items()):
            for layer in sorted(by_layer):
                out.append(
                    (
                        f"tests-per-layer::{slice_name}::{layer}",
                        f"slice '{slice_name}' ({layer}): tests directory "
                        f"({TESTS_DIR}/) does not exist -- cannot verify tests",
                    )
                )
        return out

    test_files = sorted(
        p.name for p in tests_dir.iterdir()
        if p.is_file() and p.suffix == ".py" and p.name.startswith("test_")
    )

    for slice_name, by_layer in sorted(inventory.items()):
        for layer in sorted(by_layer):
            if any(
                _layer_specific_match(t.removesuffix(".py"), slice_name, layer)
                for t in test_files
            ):
                continue
            if _slice_has_any_test(test_files, slice_name):
                continue
            out.append(
                (
                    f"tests-per-layer::{slice_name}::{layer}",
                    f"slice '{slice_name}' ({layer}): no recognised test "
                    f"file under {TESTS_DIR}/. Expected one of "
                    f"tests/test_{slice_name}_{layer}.py, "
                    f"tests/test_{layer}_{slice_name}.py, "
                    f"tests/test_{slice_name}_slice.py, "
                    f"tests/test_{slice_name}.py, "
                    f"or any tests/test_{slice_name}_*.py",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


#: Violations that predate the gate being switched on. Keyed by
#: ``<rule>::<key>`` so each rule stands or falls on its own
#: justification, and each entry can shrink independently. RATCHET:
#: entries may only disappear. When you fix one, delete its entry in
#: the same PR --
#: ``tests/test_slice_completeness.py::test_baseline_entries_are_still_real_violations``
#: fails on a stale entry, and any new violation fails the gate.
#: Never add a new entry except in the acquisition PR; from then on,
#: fix the violation.
BASELINE: Mapping[str, str] = {
    # admin slice (#419) BASELINE collapsed in #584. The four
    # entries (port-declared::admin plus three
    # application-adapter-free::app/core/application/admin/*.py) were
    # cleared when app/core/ports/admin_port.py landed with the
    # AdminTemplatePort Protocol and the three application files
    # retargeted to depend on it.
    # insforge_error_handler slice (epic #641): the test file was
    # deleted during the InsForge sweep. Delete the adapter package
    # (app/core/adapters/insforge/, insforge_error_handler_di.py,
    # insforge_error_handler_port.py) in a follow-up to clear these.
    "tests-per-layer::insforge_error_handler::di": (
        "epic #641: test deleted, adapter removal pending"
    ),
    "tests-per-layer::insforge_error_handler::ports": (
        "epic #641: test deleted, adapter removal pending"
    ),
}


def check_tree(
    root: Path, *, baseline: Mapping[str, str] | None = None
) -> tuple[list[str], list[str]]:
    """Run all four assertions and return ``(violations, notices)``.

    Violations fail the check. Notices are informational: a baselined
    violation disappeared and the entry should be deleted to lock in
    the improvement.
    """
    if baseline is None:
        baseline = BASELINE
    inventory = discover_slices(root)

    assertions = (
        check_port_declared(root, inventory),
        check_adapter_in_di(root, inventory),
        check_application_adapter_free(root, inventory),
        check_tests_per_layer(root, inventory),
    )

    violations: list[str] = []
    seen_baselined: set[str] = set()
    seen_keys: set[str] = set()
    for results in assertions:
        for key, message in results:
            if key in baseline:
                seen_baselined.add(key)
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            violations.append(message)

    notices = [
        f"{key}: baselined but no longer a violation -- remove the entry "
        f"from BASELINE in scripts/check_slice_completeness.py to lock in "
        f"the improvement"
        for key in sorted(set(baseline) - seen_baselined)
    ]

    check_tree.last_inventory = inventory  # type: ignore[attr-defined]
    return sorted(violations), notices


def emit_baseline(root: Path) -> str:
    """Print a ``BASELINE`` skeleton for the current violation set.

    Used by ``--emit-baseline`` to acquire the initial set of entries.
    The operator (or PR) replaces the placeholder rationale per key
    with a real WHY-and-WHAT-removes-it note.
    """
    inventory = discover_slices(root)
    seen: set[str] = set()
    lines = [
        "# BASELINE for scripts/check_slice_completeness.py -- shrink-only.",
        "# Acquired on the same commit that wired the gate to CI.",
        "# Each entry pins a violation that predates the gate; it must",
        "# shrink (one key at a time) as the owning slice grows.",
        "",
        "BASELINE: dict[str, str] = {",
    ]
    for results in (
        check_port_declared(root, inventory),
        check_adapter_in_di(root, inventory),
        check_application_adapter_free(root, inventory),
        check_tests_per_layer(root, inventory),
    ):
        for key, _msg in results:
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"    \"{key}\": (\n"
                f"        \"ACQUIRED -- replace this rationale with WHY "
                f"the slice predates the gate and WHAT removes it.\"\n"
                f"    ),\n"
            )
    lines.append("}")
    return "\n".join(lines)


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    emit = False
    rest: list[str] = []
    for arg in args:
        if arg == "--emit-baseline":
            emit = True
        else:
            rest.append(arg)
    root = (
        Path(rest[0]).resolve()
        if rest
        else Path(__file__).resolve().parents[1]
    )
    if emit:
        print(emit_baseline(root))
        return 0

    violations, notices = check_tree(root)
    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")
    if violations:
        print(
            f"check_slice_completeness: {len(violations)} violation(s). "
            f"Slices must declare a Protocol in ports/, wire every adapter "
            f"from di/, keep application adapter-free, and own a test file "
            f"per occupied layer (AGENTS.md rule 33; hardening roadmap "
            f"Step 2)."
        )
        return 1
    print(
        f"check_slice_completeness: OK "
        f"({len(BASELINE)} baselined violation(s) remaining)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
