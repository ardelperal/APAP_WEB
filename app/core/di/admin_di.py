"""FastAPI dependency wiring for the admin slice.

The :func:`get_admin_template_adapter` provider is the seam between
FastAPI request handlers and the
:class:`~app.core.adapters.admin_template_adapter.AdminTemplateAdapter`
typed renderer. The adapter wraps the application-lifespan-owned
``Jinja2Templates`` (created in :func:`app.main.create_app` and stored
on ``app.state.templates``).

The provider is intentionally narrow: it yields the renderer adapter
only. The auth users port (``AuthUsersPort``) already has its own
provider in :mod:`app.core.di.auth_di` — admin handlers depend on
BOTH providers via ``Depends`` so each use case receives the right
seam.

Pattern mirrors :func:`app.core.di.auth_di.get_auth_users_port`: the
adapter is stateless and cheap to construct; no resource ownership is
transferred, so the ``yield`` (rather than ``return``) is purely for
FastAPI's dependency-injection contract symmetry, not for cleanup.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.admin_template_adapter import AdminTemplateAdapter


def get_admin_template_adapter(
    request: Request,
) -> Iterator[AdminTemplateAdapter]:
    """FastAPI dependency yielding the per-request admin renderer.

    Resolves the shared ``Jinja2Templates`` from ``app.state.templates``
    (created by the application lifespan so it can carry
    :func:`app.core.csrf.csrf_token_context_processor` and the base
    template context processor). The adapter holds no resources of its
    own.
    """
    adapter = AdminTemplateAdapter(request.app.state.templates)
    yield adapter


__all__ = ["get_admin_template_adapter"]
