"""Contracts slice: DOC-01 (#56).

Hexagonal slice for contract PDF generation. This module owns the
domain entities, ports and use cases for generating 8 legacy contract
types from templates with conditionals (species / sex / age).

Slice taxonomy (mirrors ``app/modules/materiales/`` per issue #752):

- ``domain/``           — pure entities + rules, no I/O.
- ``ports/``            — Protocol: what the use cases need.
- ``application/``      — one use case per file (render template).
- ``adapters/local_backend/`` — LocalBackend storage adapter (PR 3).
- ``di/``               — composition root for the slice (PR 4).

PR 1 of #56 lands the template engine (domain + use case + adapter-less
ports) and the corresponding RED+GREEN atoms in ``tests/test_contratos_*.py``.

PR 2 (later) adds the LocalBackend storage adapter for the PDF draft
and the S3 / object-storage wiring required by the issue acceptance
criteria. PR 3 adds the route handler that invokes the use case from a
form post.

See ``docs/discovery/feature-04-documents-contracts-reports.md`` §4.2
for the source-of-truth capability description and
``docs/legacy-signed-contract-flow.md`` for the legacy fidelity
constraints.
"""

from __future__ import annotations

__all__: list[str] = []
