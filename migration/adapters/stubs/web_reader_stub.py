"""Stub adapter for ``WebReaderPort`` — pending local-backend implementation.

Replaces the legacy ``migration.adapters.legacy.web_reader_legacy_adapter``
(the directory was removed with the rest of the LocalBackend runtime in
issue #5). A real LocalBackend-backed adapter lands in the migration
package rewrite (issue #8); until then, every method raises
:class:`NotImplementedError` so the migration CLI fails loud per call.
"""

from __future__ import annotations

from migration.ports.web_reader_port import WebReaderPort


class StubWebReaderPort(WebReaderPort):
    """Placeholder :class:`WebReaderPort` whose every method raises."""

    def load_web_snapshot(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError(
            "WebReaderPort.load_web_snapshot: pending LocalBackend adapter, see #8"
        )


__all__ = ["StubWebReaderPort"]
