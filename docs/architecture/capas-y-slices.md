# Layers and vertical slices

APAP_WEB is being rebuilt inside-out: dependencies point toward the
domain, and the domain knows nothing about the web, the database, or the
vendor SDK. The refactor lands one **vertical slice** at a time
(`auth`, `catalogos`, `schema_bootstrap`, ...), so at any given moment
the tree is part hexagonal and part legacy.

This document is the contract. `scripts/check_layers.py` enforces it in
CI (AGENTS.md rule 33); when the two disagree, the script is what
merges, so fix them together.

## Dependency direction

```text
        delivery                      app/modules/**, app/main.py
           |                          FastAPI routes, templates
           v
          di                          app/core/di/**
           |                          composition root: the only layer
           |                          that may see the whole graph
    +------+------+
    v             v
adapters      application             app/core/adapters/**
    |             |                   app/core/application/**
    |             v
    |          ports                  app/core/ports/**
    +------+------+                   Protocols, the seam
           v
        domain                        app/core/domain/**
                                      entities and invariants
```

| Layer | May import | Never imports |
|---|---|---|
| `domain` | `domain` | everything else |
| `ports` | `domain`, `ports` | application, adapters, infrastructure, delivery |
| `application` | `domain`, `ports`, `application` | **`adapters`**, infrastructure, delivery |
| `adapters` | `domain`, `ports`, `adapters`, `infrastructure` | application, delivery |
| `infrastructure` | `domain`, `ports`, `infrastructure` | application, adapters, delivery |
| `di` | everything except `delivery` | delivery |
| `delivery` | everything | — |

The row that matters most is **`application` must not import
`adapters`**. That is the hexagon. A use case declares what it needs as
a port Protocol; the concrete InsForge adapter is wired in by
`app/core/di/<slice>_di.py` and arrives as a constructor or dependency
argument. If a use case imports an adapter, the port is decoration and
the slice is not testable without a network.

The second is that **no inner layer may import `app/modules/**`**. A
route may call a use case; a use case may never call a route.

## Inner-layer purity

`domain`, `ports`, and `application` must not import a web framework or
a storage vendor: `fastapi`, `starlette`, `jinja2`, `httpx`, `requests`,
`insforge`, `sqlalchemy`, `psycopg`. If a use case needs one of them, it
needs a port instead.

This is the tree-wide generalisation of the per-slice invariants in
`tests/test_catalogos_slice.py`, so a *new* slice cannot forget them.

## Vertical slices

A slice is one business capability owning a column through every layer:

```text
app/core/domain/auth/**                     entities
app/core/ports/auth_port.py                 the Protocol
app/core/application/auth/**                use cases
app/core/adapters/insforge/auth_insforge_*  the InsForge implementation
app/core/di/auth_di.py                      the wiring
app/modules/<slice>/{routes,service,queries}.py   the web surface
```

The slice name is derived from the path: the sub-package under
`domain/` and `application/`, the `<slice>_port` / `<slice>_di` file
stem, the prefix before the vendor segment in
`adapters/<vendor>/<slice>_<vendor>_<role>.py`, and the directory under
`app/modules/`.

Rules:

- **Inside `app/core/**`, a slice does not import another slice.** If
  two capabilities need each other, that is a composition concern:
  express it in `app/core/di/`, which is exempt.
- **Inside `app/modules/**`, cross-slice imports go through the public
  package root.** `from app.modules.animals import get_animal_by_id` is
  fine — the target slice's `__init__.py` decides what it exposes, and
  that decision stays reviewable. Importing the same capability from an
  internal adapter module is not: it welds the caller to the
  callee's internal file layout.

## The ratchet

Violations that predate the rule live in `BASELINE` inside
`scripts/check_layers.py`, each with a note explaining why it still
exists and what removes it. The dict is **shrink-only**:

- A violation not in `BASELINE` fails the build.
- A `BASELINE` entry that is no longer a violation is reported as a
  notice, and `tests/test_layers.py::test_baseline_entries_are_still_real_violations`
  fails until the entry is deleted. Fixing an import and leaving its
  entry behind would silently license the same import to come back.
- Never add an entry. Fix the import, or move the code to the layer it
  belongs in.

## Mid-migration behaviour

Layers that do not exist yet are not matched, so the gate is green on a
tree where only some slices are ported and binds automatically the
moment a new slice lands. Legacy flat modules are classified by name so
the pre-hexagonal tree is covered too:

- `app/core/domain.py` and `app/core/domain_*.py` → `domain`
- `app/core/data_access.py` (the `SqlExecutor` Protocol and the
  Protocol-level exception hierarchy) → `ports`
- `app/core/catalogos/**` (frozen dataclasses, domain entities in their
  pre-move location) → `domain`, slice `catalogos`
- every other flat `app/core/*.py` → `infrastructure`

As those modules move under `app/core/<layer>/`, delete their special
case from `classify_layer` — the path-based rule takes over.

## Running it

```bash
make check-layers          # or: python scripts/check_layers.py .
```

Exit 0 when clean. Tests: `tests/test_layers.py`.
