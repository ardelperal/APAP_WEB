"""Animals routes: list, create, get, edit, delete (soft).

Thin layer on top of ``app.modules.animals.service``. The routes
handle HTTP-specific concerns (form parsing, redirects, HTML
rendering) and delegate the SQL to the service.

Auth model: any active user from ``usuarios_autorizados`` (i.e. any
authorized user) can read and create animals. The admin panel
(``/admin``) is the only developer-only surface.
``require_authorized_user`` returns a 302 redirect to ``/login`` or
``/unauthorized`` for unauthenticated / unauthorised callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.insforge import InsForgeClient, InsForgeError
from app.modules.animals import service as animals_service
from app.modules.animals.service import Especie, Sexo

router = APIRouter(prefix="/animales", tags=["animales"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _client_dep(request: Request) -> InsForgeClient:
    """Per-request InsForge client (overridable in tests via dependency_overrides)."""
    from app.main import get_insforge_client
    return get_insforge_client()


def _current_user_optional(request: Request) -> dict | None:
    """Read the session cookie and return the payload, or None if not logged in.

    Mirrors ``app.main.get_current_user_optional`` to avoid the
    circular import (this module is imported by ``app.main``).
    """
    from app.core.config import get_settings
    from app.core.session import read_session, session_cookie_name

    settings = get_settings()
    token = request.cookies.get(session_cookie_name())
    if not token:
        return None
    return read_session(token, secret=settings.session_secret)


def require_authorized_user(
    request: Request,
    payload: dict | None = Depends(_current_user_optional),
) -> dict:
    """FastAPI dependency: 302 to /login or /unauthorized as appropriate."""
    if not payload:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"location": "/login"})
    if not payload.get("is_authorized", True):
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"location": "/unauthorized"})
    return payload


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Map a parsed form to the dict shape that ``service.create_animal`` expects.

    Only the columns present in the form are included; absent columns
    are returned as ``None`` so the service passes them as NULL to
    InsForge.
    """
    def _opt(key: str) -> str | None:
        value = form.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    return {
        "NCHIP": _opt("NCHIP"),
        "NombreAnimal": _opt("NombreAnimal"),
        "Especie": _opt("Especie"),
        "Sexo": _opt("Sexo"),
        "FNacimiento": _opt("FNacimiento"),
        "TraeNChip": _opt("TraeNChip"),
        "FIMPLANTACIONCHIP": _opt("FIMPLANTACIONCHIP"),
        "Raza": _opt("Raza"),
        "Color": _opt("Color"),
        "Pelo": _opt("Pelo"),
        "Tamano": _opt("Tamano"),
        "Caracter": _opt("Caracter"),
        "FDefuncion": _opt("FDefuncion"),
        "Terapia": _opt("Terapia"),
        "Observaciones": _opt("Observaciones"),
        "NombreFoto": _opt("NombreFoto"),
        "Cartilla": _opt("Cartilla"),
        "Eutanasia": _opt("Eutanasia"),
        "RazaPPP": _opt("RazaPPP"),
        "Mestizo": _opt("Mestizo"),
        "EutanasiaOtrasCausas": _opt("EutanasiaOtrasCausas"),
        "EutanasiaEnfermedad": _opt("EutanasiaEnfermedad"),
        "UltimoEstadoAntesDeFallecido": _opt("UltimoEstadoAntesDeFallecido"),
        "ComunicacionARIAC": _opt("ComunicacionARIAC"),
    }


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_animales(
    request: Request,
    user: dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(_client_dep),
):
    """Lista de animales activos, mas recientes primero."""
    animales = animals_service.list_animals(client)
    return _templates.TemplateResponse(
        request=request,
        name="animales/list.html",
        context={"user": user, "animales": animales},
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_animal_form(
    request: Request,
    user: dict = Depends(require_authorized_user),
):
    """Formulario vacio para dar de alta un animal."""
    return _templates.TemplateResponse(
        request=request,
        name="animales/form.html",
        context={
            "user": user,
            "form_data": {},
            "error": None,
            "especies": [e.value for e in Especie],
            "sexos": [s.value for s in Sexo],
        },
    )


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_animal_view(
    request: Request,
    NCHIP: str = Form(...),
    NombreAnimal: str = Form(...),
    Especie: str = Form(...),
    Sexo: str = Form(...),
    FNacimiento: str = Form(...),
    TraeNChip: str | None = Form(None),
    FIMPLANTACIONCHIP: str | None = Form(None),
    Raza: str | None = Form(None),
    Color: str | None = Form(None),
    Pelo: str | None = Form(None),
    Tamano: str | None = Form(None),
    Caracter: str | None = Form(None),
    FDefuncion: str | None = Form(None),
    Terapia: str | None = Form(None),
    Observaciones: str | None = Form(None),
    NombreFoto: str | None = Form(None),
    Cartilla: str | None = Form(None),
    Eutanasia: str | None = Form(None),
    RazaPPP: str | None = Form(None),
    Mestizo: str | None = Form(None),
    EutanasiaOtrasCausas: str | None = Form(None),
    EutanasiaEnfermedad: str | None = Form(None),
    UltimoEstadoAntesDeFallecido: str | None = Form(None),
    ComunicacionARIAC: str | None = Form(None),
    user: dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(_client_dep),
):
    """Procesa el submit del formulario. En exito, redirect al detalle."""
    form_data: dict[str, Any] = _form_data_to_params({
        "NCHIP": NCHIP, "NombreAnimal": NombreAnimal, "Especie": Especie,
        "Sexo": Sexo, "FNacimiento": FNacimiento, "TraeNChip": TraeNChip,
        "FIMPLANTACIONCHIP": FIMPLANTACIONCHIP, "Raza": Raza, "Color": Color,
        "Pelo": Pelo, "Tamano": Tamano, "Caracter": Caracter,
        "FDefuncion": FDefuncion, "Terapia": Terapia, "Observaciones": Observaciones,
        "NombreFoto": NombreFoto, "Cartilla": Cartilla, "Eutanasia": Eutanasia,
        "RazaPPP": RazaPPP, "Mestizo": Mestizo,
        "EutanasiaOtrasCausas": EutanasiaOtrasCausas,
        "EutanasiaEnfermedad": EutanasiaEnfermedad,
        "UltimoEstadoAntesDeFallecido": UltimoEstadoAntesDeFallecido,
        "ComunicacionARIAC": ComunicacionARIAC,
    })

    try:
        animal = animals_service.create_animal(client, form_data)
    except ValueError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="animales/form.html",
            context={
                "user": user,
                "form_data": form_data,
                "error": str(exc),
                "especies": [e.value for e in Especie],
                "sexos": [s.value for s in Sexo],
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except InsForgeError as exc:
        if exc.status_code == 409:
            return _templates.TemplateResponse(
                request=request,
                name="animales/form.html",
                context={
                    "user": user,
                    "form_data": form_data,
                    "error": "Ya existe un animal con ese NCHIP. Compruebalo.",
                    "especies": [e.value for e in Especie],
                    "sexos": [s.value for s in Sexo],
                },
                status_code=status.HTTP_409_CONFLICT,
            )
        raise

    return RedirectResponse(
        url=f"/animales/{animal.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{animal_id}", response_class=HTMLResponse)
def animal_detail(
    animal_id: str,
    request: Request,
    user: dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(_client_dep),
):
    """Detalle de un animal. 404 si no existe."""
    animal = animals_service.get_animal_by_id(client, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="animales/detail.html",
        context={"user": user, "animal": animal},
    )


# --- edit (form prellenado) ----------------------------------------------


@router.get("/{animal_id}/edit", response_class=HTMLResponse)
def edit_animal_form(
    animal_id: str,
    request: Request,
    user: dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(_client_dep),
):
    """Formulario prellenado para editar un animal."""
    animal = animals_service.get_animal_by_id(client, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="animales/form.html",
        context={
            "user": user,
            "form_data": _animal_to_form_data(animal),
            "error": None,
            "especies": [e.value for e in Especie],
            "sexos": [s.value for s in Sexo],
        },
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{animal_id}/update", response_class=HTMLResponse)
def update_animal_view(
    animal_id: str,
    request: Request,
    NCHIP: str = Form(...),
    NombreAnimal: str = Form(...),
    Especie: str = Form(...),
    Sexo: str = Form(...),
    FNacimiento: str = Form(...),
    TraeNChip: str | None = Form(None),
    FIMPLANTACIONCHIP: str | None = Form(None),
    Raza: str | None = Form(None),
    Color: str | None = Form(None),
    Pelo: str | None = Form(None),
    Tamano: str | None = Form(None),
    Caracter: str | None = Form(None),
    FDefuncion: str | None = Form(None),
    Terapia: str | None = Form(None),
    Observaciones: str | None = Form(None),
    NombreFoto: str | None = Form(None),
    Cartilla: str | None = Form(None),
    Eutanasia: str | None = Form(None),
    RazaPPP: str | None = Form(None),
    Mestizo: str | None = Form(None),
    EutanasiaOtrasCausas: str | None = Form(None),
    EutanasiaEnfermedad: str | None = Form(None),
    UltimoEstadoAntesDeFallecido: str | None = Form(None),
    ComunicacionARIAC: str | None = Form(None),
    user: dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(_client_dep),
):
    """Procesa el submit de edicion. Redirect al detalle en exito."""
    form_data = _form_data_to_params({
        "NCHIP": NCHIP, "NombreAnimal": NombreAnimal, "Especie": Especie,
        "Sexo": Sexo, "FNacimiento": FNacimiento, "TraeNChip": TraeNChip,
        "FIMPLANTACIONCHIP": FIMPLANTACIONCHIP, "Raza": Raza, "Color": Color,
        "Pelo": Pelo, "Tamano": Tamano, "Caracter": Caracter,
        "FDefuncion": FDefuncion, "Terapia": Terapia, "Observaciones": Observaciones,
        "NombreFoto": NombreFoto, "Cartilla": Cartilla, "Eutanasia": Eutanasia,
        "RazaPPP": RazaPPP, "Mestizo": Mestizo,
        "EutanasiaOtrasCausas": EutanasiaOtrasCausas,
        "EutanasiaEnfermedad": EutanasiaEnfermedad,
        "UltimoEstadoAntesDeFallecido": UltimoEstadoAntesDeFallecido,
        "ComunicacionARIAC": ComunicacionARIAC,
    })
    # El update completo: ejecutamos create_animal logic (validacion)
    # y luego un UPDATE. Aqui simplificamos: validamos, luego delegamos.
    # TODO LIFECYCLE-SERVICE-04: usar update_animal cuando exista.
    try:
        _validate_update_params(form_data)
    except ValueError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="animales/form.html",
            context={
                "user": user, "form_data": form_data, "error": str(exc),
                "especies": [e.value for e in Especie],
                "sexos": [s.value for s in Sexo],
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Update full: lo hacemos en la DB con un UPDATE SET ... WHERE id=$1
    update_sql = _build_update_sql(form_data)
    client.execute_sql(update_sql, [animal_id] + _build_update_params(form_data))

    return RedirectResponse(
        url=f"/animales/{animal_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) -------------------------------------------------------


@router.post("/{animal_id}/delete", response_class=HTMLResponse)
def delete_animal_view(
    animal_id: str,
    request: Request,
    user: dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(_client_dep),
):
    """Soft-delete: marca activo=false. Redirect a la lista."""
    # Verificar que existe
    if animals_service.get_animal_by_id(client, animal_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    client.execute_sql(
        "UPDATE animales SET activo = false, updated_at = now() WHERE id = $1",
        [animal_id],
    )
    return RedirectResponse(
        url="/animales", status_code=status.HTTP_303_SEE_OTHER
    )


# --- helpers -------------------------------------------------------------


def _animal_to_form_data(animal) -> dict[str, Any]:
    """Convierte un Animal a dict para pre-rellenar el form."""
    return {
        "NCHIP": animal.NCHIP or "",
        "NombreAnimal": animal.NombreAnimal or "",
        "Especie": animal.Especie.value if animal.Especie else "",
        "Sexo": animal.Sexo.value if animal.Sexo else "",
        "FNacimiento": animal.FNacimiento or "",
        "TraeNChip": animal.TraeNChip or "",
        "FIMPLANTACIONCHIP": animal.FIMPLANTACIONCHIP or "",
        "Raza": animal.Raza or "",
        "Color": animal.Color or "",
        "Pelo": animal.Pelo or "",
        "Tamano": animal.Tamano or "",
        "Caracter": animal.Caracter or "",
        "FDefuncion": animal.FDefuncion or "",
        "Terapia": animal.Terapia or "",
        "Observaciones": animal.Observaciones or "",
        "NombreFoto": animal.NombreFoto or "",
        "Cartilla": animal.Cartilla or "",
        "Eutanasia": animal.Eutanasia or "",
        "RazaPPP": animal.RazaPPP or "",
        "Mestizo": animal.Mestizo or "",
        "EutanasiaOtrasCausas": animal.EutanasiaOtrasCausas or "",
        "EutanasiaEnfermedad": animal.EutanasiaEnfermedad or "",
        "UltimoEstadoAntesDeFallecido": animal.UltimoEstadoAntesDeFallecido or "",
        "ComunicacionARIAC": animal.ComunicacionARIAC or "",
    }


def _validate_update_params(params: dict[str, Any]) -> None:
    """Mismas validaciones que create para update."""
    if not (params.get("NCHIP") or "").strip():
        raise ValueError("NCHIP es obligatorio")
    if not (params.get("NombreAnimal") or "").strip():
        raise ValueError("NombreAnimal es obligatorio")
    Especie(params.get("Especie"))  # raises if invalid
    Sexo(params.get("Sexo"))
    if not (params.get("FNacimiento") or "").strip():
        raise ValueError("FNacimiento es obligatorio")


_UPDATE_COLUMNS = (
    "NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento",
    "TraeNChip", "FIMPLANTACIONCHIP", "Raza", "Color", "Pelo", "Tamano",
    "Caracter", "FDefuncion", "Terapia", "Observaciones", "NombreFoto",
    "Cartilla", "Eutanasia", "RazaPPP", "Mestizo", "EutanasiaOtrasCausas",
    "EutanasiaEnfermedad", "UltimoEstadoAntesDeFallecido", "ComunicacionARIAC",
)


def _build_update_sql(params: dict[str, Any]) -> str:
    set_clause = ", ".join(f"{col} = ${i+2}" for i, col in enumerate(_UPDATE_COLUMNS))
    return f"UPDATE animales SET {set_clause}, updated_at = now() WHERE id = $1"


def _build_update_params(params: dict[str, Any]) -> list[Any]:
    return [params.get(col) for col in _UPDATE_COLUMNS]
