"""Animals routes: list, create, get, edit, delete (soft).

Thin layer on top of ``app.modules.animals.service``. The routes
handle HTTP-specific concerns (form parsing, redirects, HTML
rendering) and delegate the SQL to the service.

Auth model: any active user from ``usuarios_autorizados`` (i.e. any
authorized user) can read and create animals. The admin panel
(``/admin``) is the only developer-only surface.
``require_authorized_user`` returns a 302 redirect to ``/login`` or
``/unauthorized`` for unauthenticated / unauthorised callers.

Las dependencias de auth (``get_insforge_client_dep``,
``get_current_user_optional`` y ``require_authorized_user``) viven
en ``app.core.auth_dependencies`` para evitar el copy-paste con
``app.modules.voluntarios.routes``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    require_authorized_user,
    require_writer_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.middleware import base_template_context_processor
from app.modules.animals import photo_service
from app.modules.animals import service as animals_service
from app.modules.animals.forms import AnimalForm

# Los handlers de create/update reciben los campos ``Especie`` y
# ``Sexo`` del form (mismo nombre que las columnas del schema y los
# enums de dominio). Si importaramos ``Especie`` / ``Sexo`` con su
# nombre canonico, los parametros de los handlers los shadow-ean y
# referencias como ``[e.value for e in EspecieEnum]`` (usadas para
# poblar el dropdown del form en el path 422) iteran sobre los
# caracteres del string en vez de sobre los miembros del enum.
# Por eso importamos los enums bajo alias y usamos ``EspecieEnum``
# / ``SexoEnum`` en los bodies de los handlers.
from app.modules.animals.service import Especie as EspecieEnum
from app.modules.animals.service import Sexo as SexoEnum

router = APIRouter(prefix="/animales", tags=["animales"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


# PR4b placeholder photo (1x1 transparent PNG, 67 bytes). Served when the
# animal has no ``NombreFoto``, when the row carries the migration sentinel
# ``__missing__``, or when the storage stream fails closed. The bytes are
# inlined so the route does NOT touch disk on the placeholder path.
_PLACEHOLDER_PHOTO_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
    b"\xfeA\xc0\xc1\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Lista de animales activos, mas recientes primero."""
    if (early := return_early_if_response(user)) is not None:
        return early
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
    user: Response | dict = Depends(require_authorized_user),
):
    """Formulario vacio para dar de alta un animal."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _templates.TemplateResponse(
        request=request,
        name="animales/form.html",
        context={
            "user": user,
            "form_data": {},
            "error": None,
            "especies": [e.value for e in EspecieEnum],
            "sexos": [s.value for s in SexoEnum],
        },
    )


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_animal_view(
    request: Request,
    form: AnimalForm = Form(...),  # type: ignore[assignment]
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Procesa el submit del formulario. En exito, redirect al detalle.

    Uses ``AnimalForm`` (Pydantic v2 with ``Form()``) as the single
    source of truth for the 24 form fields. Adding a column means
    adding it to ``app.modules.animals.forms.AnimalForm`` (which
    asserts the field set matches the service's ``_INSERT_COLUMNS``
    at import time) — the two routes cannot drift.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(
        form.model_dump(exclude_none=True)
    )

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
                "especies": [e.value for e in EspecieEnum],
                "sexos": [s.value for s in SexoEnum],
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
                    "especies": [e.value for e in EspecieEnum],
                    "sexos": [s.value for s in SexoEnum],
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
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Detalle de un animal. 404 si no existe."""
    if (early := return_early_if_response(user)) is not None:
        return early
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
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Formulario prellenado para editar un animal."""
    if (early := return_early_if_response(user)) is not None:
        return early
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
            "especies": [e.value for e in EspecieEnum],
            "sexos": [s.value for s in SexoEnum],
        },
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{animal_id}/update", response_class=HTMLResponse)
def update_animal_view(
    animal_id: str,
    request: Request,
    form: AnimalForm = Form(...),  # type: ignore[assignment]
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Procesa el submit de edicion. Redirect al detalle en exito.

    Same ``AnimalForm`` as ``create_animal_view`` — single source of
    truth (see ``app/modules/animals/forms.py``). The handler stays
    thin: it only translates ``ValueError`` -> 422 and success -> 303.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(form.model_dump(exclude_none=True))

    try:
        animals_service.update_animal(client, animal_id, form_data)
    except ValueError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="animales/form.html",
            context={
                "user": user, "form_data": form_data, "error": str(exc),
                "especies": [e.value for e in EspecieEnum],
                "sexos": [s.value for s in SexoEnum],
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return RedirectResponse(
        url=f"/animales/{animal_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) -------------------------------------------------------


@router.post("/{animal_id}/delete", response_class=HTMLResponse)
def delete_animal_view(
    animal_id: str,
    request: Request,
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete via ``animals_service.delete_animal``. Redirect a la lista.

    El service hace un solo ``UPDATE … WHERE id = $1 RETURNING id``;
    si la fila no existia (RETURNING vacio) devuelve ``False`` y el
    handler responde 404. Asi evitamos el patron anterior (SELECT
    previo + UPDATE) y cerramos el problema #1 del code review externo.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not animals_service.delete_animal(client, animal_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/animales", status_code=status.HTTP_303_SEE_OTHER
    )


# --- foto (authenticated stream) -----------------------------------------


@router.get("/{animal_id}/foto")
def animal_foto(
    animal_id: str,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Stream the private photo bytes for ``animal_id``.

    Contract (per ``live-migration-private-photo-storage`` spec):

    - No session → middleware redirects to ``/login`` BEFORE this handler
      runs; the handler NEVER sees an anonymous request.
    - ``animal_id`` is the ``animales.id`` UUID primary key. NCHIP is the
      natural-key lookup column, never the route identifier.
    - The storage surface is the private ``apap-photos`` bucket. The
      presigned URL returned by InsForge is server-stream-only and MUST
      NOT be exposed to the browser/client (AGENTS.md §18, privacy
      default-deny).
    - Sentinel ``__missing__`` and ``None``/empty ``NombreFoto`` short-circuit
      to a 1x1 placeholder PNG WITHOUT any InsForge I/O.
    - Any **storage-stream** failure (network drop, auth, 404, 5xx,
      timeout, mid-iteration read timeout) fails closed to the same
      placeholder — never 5xx to the browser. ``photo_service`` wraps
      iteration so mid-stream errors surface as ``PhotoStreamError`` on
      the first failing ``next()``; the route's eager first-byte check
      below catches them BEFORE ``StreamingResponse`` commits the
      response status. SQL lookup failures (animal row SELECT) are NOT
      covered by this fail-closed contract — they surface as 500; see
      ``docs/audits/pii-live-migration-2026-Q3.md`` for the precise
      scope claim.

    The handler delegates the stream decision to
    :mod:`app.modules.animals.photo_service` (single responsibility, no
    SQL knowledge) and translates the typed outcome into an HTTP response.
    """
    if (early := return_early_if_response(user)) is not None:
        return early

    animal = animals_service.get_animal_by_id(client, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if photo_service.is_missing_nombrefoto(animal.NombreFoto):
        # No storage I/O: serve the inlined placeholder bytes.
        return Response(
            content=_PLACEHOLDER_PHOTO_PNG,
            media_type="image/png",
        )

    # ``stream_animal_photo`` is a generator; calling it returns a
    # generator object without executing the body. The route consumes
    # the full iterator into memory so ANY mid-stream error
    # (``httpx.RemoteProtocolError``, ``httpx.ReadTimeout``, per-chunk
    # 5xx surfaced from the underlying transport, etc.) is caught by
    # the ``except PhotoStreamError`` branch and translated to the
    # placeholder. This trades the spec's "no full file in memory"
    # property for placeholder reliability — the streaming alternative
    # (FastAPI ``StreamingResponse``) cannot retroactively replace a
    # partial body once the response status has been committed.
    #
    # Photos in the project are KB-to-low-MB JPEGs; the memory cost
    # is bounded by the photo size limit (10 MiB per the spec).
    try:
        byte_iter = photo_service.stream_animal_photo(
            client, nombrefoto=animal.NombreFoto
        )
        chunks = list(byte_iter)
    except photo_service.PhotoStreamError:
        # Fail closed: any storage-side failure (eager OR mid-iteration)
        # becomes the placeholder, never a 5xx.
        return Response(
            content=_PLACEHOLDER_PHOTO_PNG,
            media_type="image/png",
        )

    if not chunks:
        # Empty stream: the storage returned a 200 with no body. Treat
        # as missing — placeholder, no 5xx.
        return Response(
            content=_PLACEHOLDER_PHOTO_PNG,
            media_type="image/png",
        )

    return Response(
        content=b"".join(chunks),
        media_type=photo_service.content_type_for_key(animal.NombreFoto),
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


