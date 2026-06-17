"""Tests for the public HTML routes of the skeleton.

The landing page (/) and the access-denied page (/unauthorized) are
the only HTML routes shipped in Fase 1. They must render with the
Jinja2 base template, link the compiled CSS asset, and serve a
document with the right ``Content-Type``.
"""

from __future__ import annotations


def test_index_renders_html() -> None:
    """``GET /`` returns an HTML page rendered from base.html + index.html."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_index_links_compiled_css() -> None:
    """The landing page links the compiled Tailwind CSS asset."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/")

    assert "/static/css/output.css" in response.text


def test_index_mentions_app_name() -> None:
    """The landing page shows the application name from settings."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/")

    assert "APAP_WEB" in response.text


def test_unauthorized_renders_html() -> None:
    """``GET /unauthorized`` returns an HTML page with the access-denied copy."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/unauthorized")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "no autorizado" in response.text.lower()


def test_unauthorized_links_compiled_css() -> None:
    """The unauthorized page links the compiled Tailwind CSS asset."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/unauthorized")

    assert "/static/css/output.css" in response.text
