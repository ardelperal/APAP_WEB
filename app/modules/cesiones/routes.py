"""Routes for the cesion por propietario workflow (issue #41 / INTAKE-03).

Mirrors ``app.modules.entradas.routes`` exactly: routes are a thin
HTTP layer that delegates to ``app.modules.cesiones.service``. Auth
guards, form parsing and HTML rendering live here; SQL, validation and
domain rules live in the service. Per AGENTS.md rule 1, this module
must never call ``client.execute_sql`` directly — that guard is
enforced by ``tests/test_cesiones_routes.py`` via static analysis of
the source file.

The route surface is intentionally minimal (issue #41 acceptance
criteria):

- ``GET /cesiones/new`` — render the surrender form (operator side).
- ``POST /cesiones`` — process the form. Returns 303 on success,
  422 on validation errors, 409 if a cesión already exists for the
  referenced ``entrada_id`` (FK UNIQUE enforcement).

On success the route redirects to ``/entradas/{entrada_id}`` because
the cesión carries enough context to be inspected from the parent
intake detail page. Adding a standalone ``/cesiones/{id}`` detail view
is deferred until Fase 7 (contract generation) ships, when the
cesión page will render alongside its generated contrato / PDF.

CSRF defense (AGENTS.md rule 10): the form template renders an
``<input type="hidden" name="csrf_token" value="{{ csrf_token }}">``;
``CsrfMiddleware`` validates the token before this handler runs. The
POST is wrapped by ``make_csrf_request`` in route tests so the
middleware does not reject them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.cesiones import service as cesiones_service

router = APIRouter(prefix="/cesiones", tags=["cesiones"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


def _opt(value: str | None) -> str | None:
    """Strip a string or convert empty to ``None`` for optional fields.

    Mirrors ``entradas/routes.py::_opt``. Lets the operator leave
    optional fields blank in the form (e.g. telefono_representante) and
    have the service write NULL to the DB rather than empty string.
    """
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Translate the raw form dict into the service's ``params`` schema.

    Three required fields are kept verbatim (entrada_id, numero_contrato,
    nombre_representante — the form's required inputs render with
    ``required`` and the service raises ``ValueError`` if they are
    blank, which the route surfaces as 422). The other 17 fields are
    optional and pass through ``_opt`` so blanks become ``None``.
    """
    return {
        "entrada_id": _opt(form.get("entrada_id")),
        "numero_contrato": _opt(form.get("numero_contrato")),
        "nombre_representante": _opt(form.get("nombre_representante")),
        "dni_representante": _opt(form.get("dni_representante")),
        "fecha_cesion": _opt(form.get("fecha_cesion")),
        "calle_representante": _opt(form.get("calle_representante")),
        "numero_calle_representante": _opt(form.get("numero_calle_representante")),
        "piso_representante": _opt(form.get("piso_representante")),
        "letra_representante": _opt(form.get("letra_representante")),
        "localidad_representante": _opt(form.get("localidad_representante")),
        "provincia_representante": _opt(form.get("provincia_representante")),
        "cp_representante": _opt(form.get("cp_representante")),
        "telefono_representante": _opt(form.get("telefono_representante")),
        "email_representante": _opt(form.get("email_representante")),
        "cartilla_sanitaria": _opt(form.get("cartilla_sanitaria")),
        "certificado_veterinario": _opt(form.get("certificado_veterinario")),
        "autorizacion_recogida": _opt(form.get("autorizacion_recogida")),
        "fecha_vacuna_rabia": _opt(form.get("fecha_vacuna_rabia")),
        "numero_colegiado": _opt(form.get("numero_colegiado")),
        "numero_colaborador": _opt(form.get("numero_colaborador")),
        "hora_cesion": _opt(form.get("hora_cesion")),
    }


def _render_form(
    request: Request,
    user: Response | dict,
    form_data: dict[str, Any],
    error: str | None,
    status_code: int = status.HTTP_200_OK,
):
    """Render the cesion form template with the operator's payload.

    The form is the only write surface for issue #41; it carries all
    19 legacy ``TbCesionPorPropietario`` columns plus the
    ``hora_cesion`` time portion so the superset is visible at a
    glance for the operator.
    """
    return _templates.TemplateResponse(
        request=request,
        name="cesiones/form.html",
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
        },
        status_code=status_code,
    )


# --- new (form) ----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_cesion_form(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_CESIONES))],
):
    """Render the empty surrender form for the operator."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None)


# --- create (submit) -----------------------------------------------------


@router.post("", response_class=HTMLResponse)
async def create_cesion_view(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_CESIONES))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    entrada_id: Annotated[str, Form()],
    numero_contrato: Annotated[str, Form()],
    nombre_representante: Annotated[str, Form()],
    dni_representante: Annotated[str | None, Form()] = None,
    fecha_cesion: Annotated[str | None, Form()] = None,
    calle_representante: Annotated[str | None, Form()] = None,
    numero_calle_representante: Annotated[str | None, Form()] = None,
    piso_representante: Annotated[str | None, Form()] = None,
    letra_representante: Annotated[str | None, Form()] = None,
    localidad_representante: Annotated[str | None, Form()] = None,
    provincia_representante: Annotated[str | None, Form()] = None,
    cp_representante: Annotated[str | None, Form()] = None,
    telefono_representante: Annotated[str | None, Form()] = None,
    email_representante: Annotated[str | None, Form()] = None,
    cartilla_sanitaria: Annotated[str | None, Form()] = None,
    certificado_veterinario: Annotated[str | None, Form()] = None,
    autorizacion_recogida: Annotated[str | None, Form()] = None,
    fecha_vacuna_rabia: Annotated[str | None, Form()] = None,
    numero_colegiado: Annotated[str | None, Form()] = None,
    numero_colaborador: Annotated[str | None, Form()] = None,
    hora_cesion: Annotated[str | None, Form()] = None,
):
    """Process the cesión form. On success, redirect to the parent
    ``/entradas/{entrada_id}`` (the cesión lives 1-a-1 with its
    intake); on validation errors re-render with 422; on the
    FK-UNIQUE-conflict re-render with 409 and a friendly message
    (P1 fidelity: legacy ``TbCesionPorPropietario`` was 1-a-1 with
    ``TbEntradas``, so a second cesión for the same entrada is an
    error, not a silent override).
    """
    if (early := return_early_if_response(user)) is not None:
        return early

    form_data = _form_data_to_params(
        {
            "entrada_id": entrada_id,
            "numero_contrato": numero_contrato,
            "nombre_representante": nombre_representante,
            "dni_representante": dni_representante,
            "fecha_cesion": fecha_cesion,
            "calle_representante": calle_representante,
            "numero_calle_representante": numero_calle_representante,
            "piso_representante": piso_representante,
            "letra_representante": letra_representante,
            "localidad_representante": localidad_representante,
            "provincia_representante": provincia_representante,
            "cp_representante": cp_representante,
            "telefono_representante": telefono_representante,
            "email_representante": email_representante,
            "cartilla_sanitaria": cartilla_sanitaria,
            "certificado_veterinario": certificado_veterinario,
            "autorizacion_recogida": autorizacion_recogida,
            "fecha_vacuna_rabia": fecha_vacuna_rabia,
            "numero_colegiado": numero_colegiado,
            "numero_colaborador": numero_colaborador,
            "hora_cesion": hora_cesion,
        }
    )

    try:
        cesion, _contrato = cesiones_service.create_cesion(client, form_data)
    except cesiones_service.CesionConflictError:
        return _render_form(
            request,
            user,
            form_data,
            "Ya existe una cesión por propietario para esta entrada. "
            "Edita la existente o elimínala antes de crear otra.",
            status_code=status.HTTP_409_CONFLICT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar la cesión: {exc}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return RedirectResponse(
        url=f"/entradas/{cesion.entrada_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
