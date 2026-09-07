"""Use cases for reading the web backend during migration.

Each submodule owns one use case. The use cases depend only on
:class:`migration.ports.web_reader_port.WebReaderPort`; the
adapter-side I/O lives in
:mod:`migration.adapters.local_backend.web_reader_local_backend_adapter`.
"""

from __future__ import annotations

from migration.application.web_reader.load_web_snapshot import load_web_snapshot

__all__ = ["load_web_snapshot"]
