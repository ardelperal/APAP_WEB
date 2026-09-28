"""Tests for the contratos ports layer (DOC-01 CP1, issue #850).

CP1 ships the transport-free surface the later chained PRs build on:
``ContratosPdfPort`` (HTML→PDF bytes), ``ContratosStoragePort``
(put / get / delete PDF objects) and the ``ContratoPdf`` value object.

Test classification (skills/apap-testing-strategy §3): application unit
(hexagonal) — the port surface is exercised against in-memory fakes with
no I/O, no DB and no network. Gate B does not apply: nothing here
touches SQL, triggers or constraints. Honours web-tdd-philosophy rules
1 (fixture gate), 3 (cardinality), 4 (no humo), 5 (three paths) and 8
(no production mutation).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, field

import pytest

from app.modules.contratos.ports.contrato_pdf import ContratoPdf
from app.modules.contratos.ports.contratos_pdf_port import ContratosPdfPort
from app.modules.contratos.ports.contratos_storage_port import (
    ContratosStoragePort,
)

# --- 1. In-memory fakes (implement the Protocols) --------------------------


@dataclass
class _InMemoryPdfGenerator:
    """Deterministic stub for :class:`ContratosPdfPort`.

    Records the HTML it receives so callers can pin what was handed
    to the port, and returns a fixed byte payload.
    """

    recorded_html: list[str] = field(default_factory=list)
    return_value: bytes = b"%PDF-fake-bytes"

    def render_html_to_pdf(self, html: str) -> bytes:
        self.recorded_html.append(html)
        return self.return_value


@dataclass
class _InMemoryPdfStorage:
    """Deterministic fake for :class:`ContratosStoragePort`.

    Stores bodies in a ``{(bucket, key): bytes}`` dict. ``get_pdf_stream``
    returns ``None`` for missing keys (the contract under test), not an
    exception — the route handler (CP3) maps ``None`` to a 404.
    """

    objects: dict[tuple[str, str], bytes] = field(
        default_factory=dict
    )

    def put_pdf(self, *, bucket: str, key: str, body: bytes) -> str:
        self.objects[(bucket, key)] = body
        return f"{bucket}/{key}"

    def get_pdf_stream(
        self, *, bucket: str, key: str
    ) -> ContratoPdf | None:
        body = self.objects.get((bucket, key))
        if body is None:
            return None
        return ContratoPdf(
            bucket=bucket,
            key=key,
            media_type="application/pdf",
            content_length=len(body),
            body=body,
        )

    def delete_pdf(self, *, bucket: str, key: str) -> bool:
        return self.objects.pop((bucket, key), None) is not None


# --- 2. ContratoPdf value object -------------------------------------------


def test_contrato_pdf_construction_pins_every_field() -> None:
    """Full construction pins all five fields byte-for-byte."""
    asset = ContratoPdf(
        bucket="apap-contracts",
        key="A_42.pdf",
        media_type="application/pdf",
        content_length=11,
        body=b"%PDF-stored",
    )
    assert asset.bucket == "apap-contracts"
    assert asset.key == "A_42.pdf"
    assert asset.media_type == "application/pdf"
    assert asset.content_length == 11
    assert asset.body == b"%PDF-stored"


def test_contrato_pdf_defaults() -> None:
    """Only ``bucket`` and ``key`` are mandatory; the rest default.

    ``media_type`` defaults to the only media type the contratos slice
    produces, ``content_length`` to ``None`` (unknown length) and
    ``body`` to an empty byte string.
    """
    asset = ContratoPdf(bucket="apap-contracts", key="E_1.pdf")
    assert asset.media_type == "application/pdf"
    assert asset.content_length is None
    assert asset.body == b""


def test_contrato_pdf_is_frozen() -> None:
    """The value object is immutable — mutation raises."""
    asset = ContratoPdf(bucket="apap-contracts", key="E_1.pdf")
    with pytest.raises(FrozenInstanceError):
        asset.key = "other.pdf"  # type: ignore[misc]


# --- 3. ContratosPdfPort conformance ---------------------------------------


def test_pdf_generator_fake_satisfies_protocol() -> None:
    """The in-memory fake structurally conforms to ``ContratosPdfPort``."""
    assert isinstance(_InMemoryPdfGenerator(), ContratosPdfPort)


def test_pdf_generator_renders_html_to_bytes() -> None:
    """``render_html_to_pdf`` records its input and returns fixed bytes."""
    generator = _InMemoryPdfGenerator()
    result = generator.render_html_to_pdf("<html><body>x</body></html>")
    assert result == b"%PDF-fake-bytes"
    assert generator.recorded_html == ["<html><body>x</body></html>"]


# --- 4. ContratosStoragePort conformance -----------------------------------


def test_storage_fake_satisfies_protocol() -> None:
    """The in-memory fake structurally conforms to ``ContratosStoragePort``."""
    assert isinstance(_InMemoryPdfStorage(), ContratosStoragePort)


# --- 5. Storage round trip --------------------------------------------------


def test_put_pdf_returns_marker_and_stores_body() -> None:
    """``put_pdf`` returns ``{bucket}/{key}`` and stores the body."""
    storage = _InMemoryPdfStorage()
    assert len(storage.objects) == 0  # cardinality before

    marker = storage.put_pdf(
        bucket="apap-contracts", key="A_42.pdf", body=b"%PDF-stored"
    )
    assert marker == "apap-contracts/A_42.pdf"
    assert len(storage.objects) == 1  # cardinality after
    assert storage.objects[("apap-contracts", "A_42.pdf")] == (
        b"%PDF-stored"
    )


def test_put_then_get_round_trip_returns_contrato_pdf() -> None:
    """``get_pdf_stream`` reconstructs the stored object faithfully."""
    storage = _InMemoryPdfStorage()
    storage.put_pdf(
        bucket="apap-contracts", key="A_42.pdf", body=b"%PDF-stored"
    )
    asset = storage.get_pdf_stream(
        bucket="apap-contracts", key="A_42.pdf"
    )
    assert asset == ContratoPdf(
        bucket="apap-contracts",
        key="A_42.pdf",
        media_type="application/pdf",
        content_length=11,
        body=b"%PDF-stored",
    )


def test_get_pdf_stream_returns_none_for_missing_key() -> None:
    """A missing object returns ``None`` instead of raising (sad path)."""
    storage = _InMemoryPdfStorage()
    assert (
        storage.get_pdf_stream(bucket="apap-contracts", key="gone.pdf")
        is None
    )


def test_put_pdf_overwrites_existing_body() -> None:
    """Storing the same bucket/key twice replaces the body (cardinality 1)."""
    storage = _InMemoryPdfStorage()
    storage.put_pdf(bucket="apap-contracts", key="E_1.pdf", body=b"v1")
    storage.put_pdf(bucket="apap-contracts", key="E_1.pdf", body=b"v2")
    assert len(storage.objects) == 1
    assert storage.objects[("apap-contracts", "E_1.pdf")] == b"v2"


# --- 6. Delete semantics ----------------------------------------------------


def test_delete_pdf_returns_true_when_object_existed() -> None:
    """Deleting an existing object returns ``True`` and removes it."""
    storage = _InMemoryPdfStorage()
    storage.put_pdf(bucket="apap-contracts", key="C_7.pdf", body=b"%PDF")
    assert storage.delete_pdf(bucket="apap-contracts", key="C_7.pdf")
    assert len(storage.objects) == 0  # cardinality after delete
    assert (
        storage.get_pdf_stream(bucket="apap-contracts", key="C_7.pdf")
        is None
    )


def test_delete_pdf_returns_false_when_object_absent() -> None:
    """Deleting an absent object is idempotent — returns ``False``."""
    storage = _InMemoryPdfStorage()
    assert not storage.delete_pdf(bucket="apap-contracts", key="nope.pdf")
    assert len(storage.objects) == 0


def test_delete_pdf_second_call_is_idempotent() -> None:
    """A second delete after the first succeeds does not raise (edge)."""
    storage = _InMemoryPdfStorage()
    storage.put_pdf(bucket="apap-contracts", key="X.pdf", body=b"%PDF")
    assert storage.delete_pdf(bucket="apap-contracts", key="X.pdf")
    assert not storage.delete_pdf(bucket="apap-contracts", key="X.pdf")


# --- 7. Edge paths ----------------------------------------------------------


def test_put_and_get_empty_body() -> None:
    """An empty body round-trips with ``content_length == 0``."""
    storage = _InMemoryPdfStorage()
    storage.put_pdf(bucket="apap-contracts", key="empty.pdf", body=b"")
    asset = storage.get_pdf_stream(bucket="apap-contracts", key="empty.pdf")
    assert asset is not None
    assert asset.body == b""
    assert asset.content_length == 0
