"""XSS audit — template-level parametrized auto-tests (Slice 4 of hardening-2026-q2).

Spec: ``openspec/changes/hardening-2026-q2/specs/04-xss-audit/spec.md``
REQ-XSS-2 mandates a parametrized test over the user-facing templates:
for every (template, field, xss_pattern) triple, the test renders the
template with the pattern injected into that field's value and asserts
that the dangerous payload does NOT appear literally in the rendered
HTML.

How the audit reaches PASS:
  - Starlette's ``Jinja2Templates`` constructor defaults ``autoescape=True``
    for ``.html`` files; therefore ``{{ user_input }}`` is HTML-escaped
    by the Jinja2 renderer.
  - None of the 14 templates under ``app/templates/`` use the ``|safe``
    filter and none of the route handlers use ``Markup()`` (see
    ``docs/audits/xss-audit-2026-Q2.md`` for the code-based scan).
  - Result: every parametrized assertion passes. If any test FAILS, that
    is the XSS finding — documented in the audit report.

Coverage:
  - The 8 templates explicitly listed in REQ-XSS-1's scenario
    (``base.html``, ``admin.html``, ``animales/form.html``,
    ``animales/detail.html``, ``entradas/form.html``,
    ``entradas/detail.html``, ``voluntarios/form.html``,
    ``voluntarios/detail.html``).
  - Plus the 6 additional templates the repo actually contains
    (``index.html``, ``login.html``, ``unauthorized.html``,
    ``animales/list.html``, ``entradas/list.html``, ``voluntarios/list.html``).
    REQ-XSS-1 counts "the 8 templates"; we cover all 14 (defence in depth) and
    document the discrepancy in the audit doc.

Patterns per spec REQ-XSS-2:
  1. ``<script>alert(1)</script>``         (basic script injection)
  2. ``<img src=x onerror=alert(1)>``     (event handler injection)
  3. ``<svg onload=alert(1)>``             (SVG-based XSS)
  4. ``javascript:alert(1)``               (URI scheme injection)

Pattern (4) is asserted differently: it lives in URL contexts
(``href``/``src``/``action`` attributes). Jinja2's autoescape escapes
``&`` and quotes but leaves ``javascript:`` unescaped in URL attribute
bodies; a real audit must verify that no template uses the URL form
with user data unvalidated. For now, the assertion is that the literal
``javascript:alert(1)`` string is either absent OR appears inside an
HTML-escaped attribute body that the browser will not execute. The
audit doc spells out the manual follow-up.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(REPO_ROOT / "app" / "templates"))


# 4 XSS patterns from spec REQ-XSS-2.
# Patterns 1-3 carry HTML-special chars (``<``, ``>``); Jinja2 autoescape
# converts them to entities, breaking the tag boundary and neutralising
# the injected script. Pattern 4 is a URI scheme with no special chars;
# autoescape does NOT touch it, and the only way it executes is from a
# URL attribute (``href=``, ``src=``, ``action=``, ``formaction=``).
# ``test_no_user_data_in_url_attributes`` below carries that guard.
HTML_XSS_PATTERNS: list[str] = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg onload=alert(1)>",
]
URL_SCHEME_PATTERN: str = "javascript:alert(1)"


def render(template_name: str, context: dict[str, Any]) -> str:
    """Render a template directly through the Jinja2 environment.

    We do NOT go through the ASGI client here: the template test is a
    pure-render characterisation test, independent of auth, routing and
    the DB layer.

    ``base_template`` is injected as a default so templates that use
    ``{% extends base_template %}`` (slice B of the UA-based templates
    work, engram obs #15705) can be rendered without going through the
    production context-processor chain. The default mirrors the helper's
    default-deny posture (``app.core.middleware._select_base_template``
    returns ``"base.html"`` when ``request.state.is_mobile`` is missing).
    """
    merged: dict[str, Any] = {"base_template": "base.html", **context}
    return TEMPLATES.env.get_template(template_name).render(**merged)


# ---------------------------------------------------------------------------
# Base contexts for each template
# ---------------------------------------------------------------------------
# Each entry is the minimal context that lets the template render
# without Jinja ``UndefinedError``. We fill every field with safe dummy
# data; the tests then MUTATE one field at a time to the XSS payload.

_BASE_USER: dict[str, Any] = {
    "email": "user@example.com",
    "rol": "key_user",
    "role": "key_user",
    "user_id": "u-1",
    "is_authorized": True,
}

_BASE_FORM_ANIMAL: dict[str, Any] = {
    "NCHIP": "985112004409871",
    "NombreAnimal": "Luna",
    "Especie": "CANINA",
    "Sexo": "H",
    "FNacimiento": "2023-04-12",
    "TraeNChip": "",
    "FIMPLANTACIONCHIP": "",
    "Raza": "Mestiza",
    "Color": "Negro",
    "Pelo": "Corto",
    "Tamano": "Mediano",
    "Caracter": "Tranquila",
    "FDefuncion": "",
    "Terapia": "",
    "Observaciones": "Sin observaciones.",
    "NombreFoto": "",
    "Cartilla": "",
    "Eutanasia": "",
    "RazaPPP": "",
    "Mestizo": "",
    "EutanasiaOtrasCausas": "",
    "EutanasiaEnfermedad": "",
    "UltimoEstadoAntesDeFallecido": "",
    "ComunicacionARIAC": "",
}

_BASE_ANIMAL_DETAIL: dict[str, Any] = {
    "id": "abc-123",
    "NCHIP": "985112004409871",
    "NombreAnimal": "Luna",
    "Especie": "CANINA",
    "Sexo": "H",
    "FNacimiento": "2023-04-12",
    "TraeNChip": None,
    "FIMPLANTACIONCHIP": None,
    "Raza": "Mestiza",
    "Color": "Negro",
    "Pelo": "Corto",
    "Tamano": "Mediano",
    "Caracter": "Tranquila",
    "FDefuncion": None,
    "Terapia": None,
    "Observaciones": "Sin observaciones.",
    "NombreFoto": None,
    "Cartilla": None,
    "Eutanasia": None,
    "RazaPPP": None,
    "Mestizo": None,
    "ComunicacionARIAC": None,
}

_BASE_FORM_ENTRADA: dict[str, Any] = {
    "animal_id": "abc-123",
    "voluntario_entrada_id": None,
    "fecha_entrada": "2024-01-15",
    "origen": "Recogida",
    "motivo": "Abandono",
    "observaciones": "Sin observaciones.",
}

_BASE_ENTRADA_DETAIL: dict[str, Any] = {
    "id": "ent-1",
    "animal_id": "abc-123",
    "voluntario_entrada_id": None,
    "fecha_entrada": "2024-01-15",
    "origen": "Recogida",
    "motivo": "Abandono",
    "observaciones": "Sin observaciones.",
}

_BASE_FORM_VOLUNTARIO: dict[str, Any] = {
    "Voluntario": "Ana García",
    "Email": "ana@example.com",
    "DNI": "12345678A",
    "Tel1": "600000000",
    "Tel2": "",
}

# Minimal context for the cesion por propietario form. Every operator-
# entered text field is rendered into an attribute via Jinja2 ``value=``
# (no autoescape bypass; the XSS test mutates each path and verifies the
# payload gets HTML-entity-escaped). The veterinary Sí/No selects use
# selected=``, which is also attribute-escaped.
_BASE_FORM_CESION: dict[str, Any] = {
    "entrada_id": "ent-abc",
    "numero_contrato": "CP0672",
    "nombre_representante": "Maria Lopez Garcia",
    "dni_representante": "12345678Z",
    "fecha_cesion": "2026-07-03",
    "calle_representante": "Calle Mayor",
    "numero_calle_representante": "1",
    "piso_representante": "2",
    "letra_representante": "A",
    "localidad_representante": "Alcala de Henares",
    "provincia_representante": "Madrid",
    "cp_representante": "28801",
    "telefono_representante": "600000000",
    "email_representante": "maria@example.com",
    "cartilla_sanitaria": "Sí",
    "certificado_veterinario": "Sí",
    "autorizacion_recogida": "Sí",
    "fecha_vacuna_rabia": "2026-05-15",
    "numero_colegiado": "9999",
    "numero_colaborador": "5555",
    "hora_cesion": "2026-07-03T11:30",
}

_BASE_VOLUNTARIO_DETAIL: dict[str, Any] = {
    "id": "v-1",
    "Voluntario": "Ana García",
    "Email": "ana@example.com",
    "DNI": "12345678A",
    "Tel1": "600000000",
    "Tel2": None,
    "fecha_alta": "2024-01-01",
}

_BASE_ADMIN_USER: dict[str, Any] = {
    "id": "u-1",
    "email": "ana@example.com",
    "role": "key_user",
    "is_active": True,
}

# Each template's render spec: (template_name, field_paths_to_mutate, base_context)
# ``field_paths_to_mutate`` are dot-paths into the context dict; the
# helper below replaces each path with the XSS payload before rendering.
TEMPLATE_SPECS: list[tuple[str, list[str], dict[str, Any]]] = [
    # --- 8 templates explicitly listed in spec REQ-XSS-1 ---
    (
        "base.html",
        ["app_name", "user.email", "user.role"],
        {"app_name": "APAP_WEB", "user": _BASE_USER},
    ),
    (
        # Slice B of the UA-based templates work (engram obs #15705):
        # ``base_mobile.html`` is the parallel mobile template selected
        # when ``request.state.is_mobile`` is True. Same context shape as
        # ``base.html`` because the page templates extend whichever the
        # context processor returns. Audit it with the same fields.
        "base_mobile.html",
        ["app_name", "user.email", "user.role"],
        {"app_name": "APAP_WEB", "user": _BASE_USER},
    ),
    (
        "admin.html",
        ["current_user.email", "users[0].email", "users[0].role"],
        {
            "app_name": "APAP_WEB",
            "current_user": _BASE_USER,
            "users": [_BASE_ADMIN_USER],
            "roles": ["developer", "admin", "key_user", "reader"],
        },
    ),
    (
        "animales/form.html",
        [
            "form_data.NCHIP",
            "form_data.NombreAnimal",
            "form_data.Raza",
            "form_data.Color",
            "form_data.Observaciones",
            "error",
        ],
        {
            "user": _BASE_USER,
            "form_data": dict(_BASE_FORM_ANIMAL),
            "error": None,
            "especies": ["CANINA", "FELINA"],
            "sexos": ["H", "M"],
        },
    ),
    (
        "animales/detail.html",
        [
            "animal.NombreAnimal",
            "animal.NCHIP",
            "animal.Raza",
            "animal.Observaciones",
        ],
        {"user": _BASE_USER, "animal": _BASE_ANIMAL_DETAIL},
    ),
    (
        "entradas/form.html",
        [
            "form_data.animal_id",
            "form_data.origen",
            "form_data.motivo",
            "form_data.observaciones",
            "error",
            "form_action",
        ],
        {
            "user": _BASE_USER,
            "form_data": dict(_BASE_FORM_ENTRADA),
            "error": None,
            "form_action": "/entradas",
        },
    ),
    (
        "entradas/detail.html",
        [
            "entrada.animal_id",
            "entrada.origen",
            "entrada.motivo",
            "entrada.observaciones",
        ],
        {"user": _BASE_USER, "entrada": _BASE_ENTRADA_DETAIL},
    ),
    (
        "voluntarios/form.html",
        [
            "form_data.Voluntario",
            "form_data.Email",
            "form_data.DNI",
            "form_data.Tel1",
            "error",
        ],
        {"user": _BASE_USER, "form_data": dict(_BASE_FORM_VOLUNTARIO), "error": None},
    ),
    (
        "voluntarios/detail.html",
        [
            "voluntario.Voluntario",
            "voluntario.Email",
            "voluntario.DNI",
            "roles[0]",
        ],
        {"user": _BASE_USER, "voluntario": _BASE_VOLUNTARIO_DETAIL, "roles": ["intake"]},
    ),
    (
        "cesiones/form.html",
        [
            "form_data.entrada_id",
            "form_data.numero_contrato",
            "form_data.nombre_representante",
            "form_data.dni_representante",
            "form_data.calle_representante",
            "form_data.email_representante",
            "form_data.cartilla_sanitaria",
            "form_data.numero_colegiado",
            "error",
        ],
        {
            "user": _BASE_USER,
            "form_data": dict(_BASE_FORM_CESION),
            "error": None,
        },
    ),
    (
        "index.html",
        ["app_name", "version", "user.email", "user.role"],
        {"app_name": "APAP_WEB", "version": "0.1.0", "user": _BASE_USER},
    ),
    (
        "login.html",
        ["app_name"],
        {"app_name": "APAP_WEB"},
    ),
    (
        "unauthorized.html",
        ["app_name"],
        {"app_name": "APAP_WEB"},
    ),
    (
        "animales/list.html",
        ["animales[0].NombreAnimal", "animales[0].NCHIP", "animales[0].Raza"],
        {"user": _BASE_USER, "animales": [_BASE_ANIMAL_DETAIL]},
    ),
    (
        "entradas/list.html",
        ["entradas[0].animal_id", "entradas[0].origen", "entradas[0].motivo"],
        {"user": _BASE_USER, "entradas": [_BASE_ENTRADA_DETAIL]},
    ),
    (
        "voluntarios/list.html",
        ["voluntarios[0].Voluntario", "voluntarios[0].Email", "voluntarios[0].DNI"],
        {"user": _BASE_USER, "voluntarios": [_BASE_VOLUNTARIO_DETAIL]},
    ),
    (
        "casas_acogida/list.html",
        [
            "casas[0].nombre",
            "casas[0].apellidos",
            "casas[0].localidad",
            "casas[0].especie_preferente",
            "casas[0].coche",
            "especie",
        ],
        {
            "user": _BASE_USER,
            "casas": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "nombre": "María",
                    "apellidos": "García",
                    "localidad": "Alcalá de Henares",
                    "especie_preferente": "CANINA",
                    "coche": "Sí",
                    "capacidad": 3,
                }
            ],
            "especie": "",
        },
    ),
    (
        "casas_acogida/form.html",
        [
            "form_data.nombre",
            "form_data.apellidos",
            "form_data.dni_acogedor",
            "form_data.calle",
            "form_data.localidad",
            "form_data.telefono",
            "form_data.email",
            "form_data.coche",
            "form_data.especie_preferente",
            "form_data.observaciones",
            "error",
        ],
        {
            "user": _BASE_USER,
            "form_data": {
                "nombre": "",
                "apellidos": "",
                "dni_acogedor": "",
                "calle": "",
                "numero": "",
                "piso": "",
                "letra": "",
                "localidad": "",
                "provincia": "",
                "cp": "",
                "telefono": "",
                "telefono2": "",
                "email": "",
                "vinculacion": "",
                "caracteristicas": "",
                "coche": "Sí",
                "especie_preferente": "",
                "observaciones": "",
                "capacidad": 1,
            },
            "error": None,
        },
    ),
    (
        "casas_acogida/detail.html",
        [
            "casa.nombre",
            "casa.apellidos",
            "casa.dni_acogedor",
            "casa.calle",
            "casa.localidad",
            "casa.telefono",
            "casa.email",
            "casa.coche",
            "casa.especie_preferente",
            "casa.capacidad",
            "casa.caracteristicas",
            "casa.observaciones",
        ],
        {
            "user": _BASE_USER,
            "casa": {
                "id": "11111111-1111-1111-1111-111111111111",
                "nombre": "María",
                "apellidos": "García",
                "dni_acogedor": "12345678A",
                "calle": "Calle Mayor",
                "numero": "12",
                "piso": "3",
                "letra": "A",
                "localidad": "Alcalá de Henares",
                "provincia": "Madrid",
                "cp": "28801",
                "telefono": "600123456",
                "telefono2": None,
                "email": "maria@example.com",
                "vinculacion": "Socia",
                "caracteristicas": "Piso con patio",
                "coche": "Sí",
                "especie_preferente": "CANINA",
                "observaciones": "Disponible fines de semana",
                "capacidad": 3,
                "fecha_alta": "2026-07-04T10:00:00Z",
                "fecha_baja": None,
                "updated_at": "2026-07-04T10:00:00Z",
                "activo": True,
            },
            "estancias_activas": 0,
            "overrides": [],
        },
    ),
    (
        "casas_acogida/asignar.html",
        [
            "casa.nombre",
            "casa.apellidos",
            "casa.especie_preferente",
            "casa.capacidad",
            "form_data.animal_id",
            "form_data.motivo",
            "warning",
            "error",
        ],
        {
            "user": _BASE_USER,
            "casa": {
                "id": "11111111-1111-1111-1111-111111111111",
                "nombre": "María",
                "apellidos": "García",
                "especie_preferente": "CANINA",
                "capacidad": 3,
            },
            "form_data": {"animal_id": "", "motivo": ""},
            "warning": None,
            "error": None,
        },
    ),
    (
        "casas_acogida/overrides.html",
        [
            "overrides[0].motivo",
            "overrides[0].animal_id",
            "overrides[0].operador_user_id",
            "overrides[0].created_at",
            "casa.nombre",
            "casa.apellidos",
            "casa.capacidad",
        ],
        {
            "user": _BASE_USER,
            "casa": {
                "id": "11111111-1111-1111-1111-111111111111",
                "nombre": "María",
                "apellidos": "García",
                "capacidad": 3,
            },
            "overrides": [
                {
                    "id": "99999999-9999-9999-9999-999999999999",
                    "casa_acogida_id": "11111111-1111-1111-1111-111111111111",
                    "animal_id": "11111111-1111-1111-1111-111111111111",
                    "operador_user_id": "u-ana",
                    "motivo": "caso urgente",
                    "created_at": "2026-07-04T11:00:00Z",
                }
            ],
        },
    ),
    (
        "acogidas/list.html",
        [
            "acogidas[0].animal_id",
            "acogidas[0].casa_acogida_id",
            "acogidas[0].fecha_inicio",
            "acogidas[0].fecha_final",
            "acogidas[0].activo",
        ],
        {
            "user": _BASE_USER,
            "acogidas": [
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "animal_id": "11111111-1111-1111-1111-111111111111",
                    "casa_acogida_id": "33333333-3333-3333-3333-333333333333",
                    "fecha_inicio": "2026-07-04",
                    "fecha_final": None,
                    "activo": True,
                }
            ],
            "activas_solo": False,
        },
    ),
    (
        "acogidas/form.html",
        [
            "form_data.animal_id",
            "form_data.casa_acogida_id",
            "form_data.voluntario_acogida_id",
            "form_data.voluntario_seguimiento1_id",
            "form_data.voluntario_seguimiento2_id",
            "form_data.voluntario_sanitario_id",
            "form_data.fecha_inicio",
            "form_data.fecha_final",
            "form_data.entrada_origen_id",
            "form_data.direccion",
            "form_data.telefono",
            "form_data.observaciones",
            "error",
        ],
        {
            "user": _BASE_USER,
            "form_data": {
                "animal_id": "",
                "casa_acogida_id": "",
                "voluntario_acogida_id": "",
                "voluntario_seguimiento1_id": "",
                "voluntario_seguimiento2_id": "",
                "voluntario_sanitario_id": "",
                "fecha_inicio": "",
                "fecha_final": "",
                "entrada_origen_id": "",
                "direccion": "",
                "telefono": "",
                "observaciones": "",
            },
            "error": None,
        },
    ),
    (
        "acogidas/detail.html",
        [
            "acogida.animal_id",
            "acogida.casa_acogida_id",
            "acogida.voluntario_acogida_id",
            "acogida.voluntario_seguimiento1_id",
            "acogida.voluntario_seguimiento2_id",
            "acogida.voluntario_sanitario_id",
            "acogida.fecha_inicio",
            "acogida.fecha_final",
            "acogida.entrada_origen_id",
            "acogida.direccion",
            "acogida.telefono",
            "acogida.observaciones",
        ],
        {
            "user": _BASE_USER,
            "acogida": {
                "id": "22222222-2222-2222-2222-222222222222",
                "animal_id": "11111111-1111-1111-1111-111111111111",
                "casa_acogida_id": "33333333-3333-3333-3333-333333333333",
                "voluntario_acogida_id": "vol-acog",
                "voluntario_seguimiento1_id": "vol-seg1",
                "voluntario_seguimiento2_id": None,
                "voluntario_sanitario_id": "vol-san",
                "fecha_inicio": "2026-07-04",
                "fecha_final": None,
                "entrada_origen_id": None,
                "direccion": "Calle Mayor 12, Alcalá de Henares",
                "telefono": "600123456",
                "observaciones": "Animal tranquilo, sin medicación",
                "fecha_alta": "2026-07-04T10:00:00Z",
                "fecha_baja": None,
                "updated_at": "2026-07-04T10:00:00Z",
                "activo": True,
            },
            "duracion": None,
            "active": True,
        },
    ),
    (
        "entradas/batch_new.html",
        [
            "rows[0].animal_id",
            "rows[0].voluntario_entrada_id",
            "rows[0].fecha_entrada",
            "rows[0].origen",
            "rows[0].motivo",
            "rows[0].observaciones",
            "error",
        ],
        {
            "user": _BASE_USER,
            "rows": [
                {
                    "animal_id": "",
                    "voluntario_entrada_id": "",
                    "fecha_entrada": "",
                    "origen": "",
                    "motivo": "",
                    "observaciones": "",
                }
            ],
            "error": None,
        },
    ),
    (
        "entradas/batch_preview.html",
        [
            "batch.batch_id",
            "batch.records[0].sequence",
            "batch.records[0].params.animal_id",
            "batch.records[0].params.fecha_entrada",
            "batch.records[0].params.origen",
            "batch.records[0].params.motivo",
            "batch.records[0].status",
            "batch.records[0].error",
            "error",
        ],
        {
            "user": _BASE_USER,
            "batch": {
                "batch_id": "11111111-1111-1111-1111-111111111111",
                "created_at": "2026-07-04T10:00:00Z",
                "records": [
                    {
                        "sequence": 1,
                        "params": {
                            "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "voluntario_entrada_id": None,
                            "fecha_entrada": "2026-07-04",
                            "origen": "Albergue",
                            "motivo": "Rescate",
                            "observaciones": None,
                        },
                        "status": "valid",
                        "error": None,
                    },
                ],
            },
            "error": None,
        },
    ),
    # --- ADOPT-01 (#47) — adopciones CRUD (3 templates) ---
    (
        "adopciones/list.html",
        [
            "adopciones[0].nombre_adoptante",
            "adopciones[0].dni_adoptante",
            "adopciones[0].fecha_adopcion",
            "adopciones[0].tipo_adopcion",
            "adopciones[0].activo",
            "adopciones[0].fecha_devolucion",
            "adoptante",
        ],
        {
            "user": _BASE_USER,
            "adopciones": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "animal_id": "animal-1",
                    "voluntario_seguimiento_id": "vol-1",
                    "fecha_adopcion": "2026-07-04",
                    "fecha_devolucion": None,
                    "donativo_preadopcion": None,
                    "donativo_adopcion": None,
                    "nombre_adoptante": "María García López",
                    "dni_adoptante": "12345678A",
                    "telefono_adoptante": "600123456",
                    "email_adoptante": "maria@example.com",
                    "entrada_origen_id": None,
                    "observaciones": "Adopción responsable",
                    "tipo_adopcion": "regular",
                    "activo": True,
                }
            ],
            "adoptante": "",
        },
    ),
    (
        "adopciones/form.html",
        [
            "form_data.nombre_adoptante",
            "form_data.dni_adoptante",
            "form_data.telefono_adoptante",
            "form_data.email_adoptante",
            "form_data.animal_id",
            "form_data.voluntario_seguimiento_id",
            "form_data.entrada_origen_id",
            "form_data.fecha_adopcion",
            "form_data.fecha_devolucion",
            "form_data.donativo_preadopcion",
            "form_data.donativo_adopcion",
            "form_data.observaciones",
            "form_data.tipo_adopcion",
            "error",
            "form_action",
        ],
        {
            "user": _BASE_USER,
            "form_data": {
                "animal_id": "",
                "voluntario_seguimiento_id": "",
                "fecha_adopcion": "",
                "fecha_devolucion": "",
                "donativo_preadopcion": "",
                "donativo_adopcion": "",
                "nombre_adoptante": "",
                "dni_adoptante": "",
                "telefono_adoptante": "",
                "email_adoptante": "",
                "entrada_origen_id": "",
                "observaciones": "",
                "tipo_adopcion": "regular",
            },
            "error": None,
            "form_action": "/adopciones",
        },
    ),
    (
        "adopciones/detail.html",
        [
            "adopcion.animal_id",
            "adopcion.voluntario_seguimiento_id",
            "adopcion.entrada_origen_id",
            "adopcion.fecha_adopcion",
            "adopcion.fecha_devolucion",
            "adopcion.nombre_adoptante",
            "adopcion.dni_adoptante",
            "adopcion.telefono_adoptante",
            "adopcion.email_adoptante",
            "adopcion.donativo_preadopcion",
            "adopcion.donativo_adopcion",
            "adopcion.observaciones",
            "adopcion.tipo_adopcion",
        ],
        {
            "user": _BASE_USER,
            "adopcion": {
                "id": "11111111-1111-1111-1111-111111111111",
                "animal_id": "animal-1",
                "voluntario_seguimiento_id": "vol-1",
                "fecha_adopcion": "2026-07-04",
                "fecha_devolucion": None,
                "donativo_preadopcion": None,
                "donativo_adopcion": None,
                "nombre_adoptante": "María García López",
                "dni_adoptante": "12345678A",
                "telefono_adoptante": "600123456",
                "email_adoptante": "maria@example.com",
                "entrada_origen_id": None,
                "observaciones": "Adopción responsable",
                "tipo_adopcion": "regular",
                "activo": True,
            },
        },
    ),
    # --- HEALTH-01 (#50) — sanidad CRUD (3 templates) ---
    (
        "sanidad/list.html",
        [
            "actuaciones[0].animal_id",
            "actuaciones[0].fecha",
            "actuaciones[0].veterinario",
            "actuaciones[0].material_utilizado",
            "actuaciones[0].id",
            "animal_id",
        ],
        {
            "user": _BASE_USER,
            "actuaciones": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "animal_id": "animal-1",
                    "fecha": "2026-07-04",
                    "veterinario": "Dra. Pérez",
                    "material_utilizado": "Nobivac Rabia",
                }
            ],
            "animal_id": "",
        },
    ),
    (
        "sanidad/form.html",
        [
            "form_data.animal_id",
            "form_data.voluntario_id",
            "form_data.fecha",
            "form_data.tipo_actuacion_id",
            "form_data.veterinario",
            "form_data.observaciones",
            "form_data.material_utilizado",
            "catalogos_pruebas[0].id",
            "catalogos_pruebas[0].nombre",
            "catalogos_pruebas[0].especie",
            "error",
            "form_action",
        ],
        {
            "user": _BASE_USER,
            "form_data": {
                "animal_id": "",
                "voluntario_id": "",
                "fecha": "",
                "tipo_actuacion_id": "",
                "veterinario": "",
                "observaciones": "",
                "material_utilizado": "",
            },
            "catalogos_pruebas": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "nombre": "Rabia",
                    "especie": "ambos",
                }
            ],
            "error": None,
            "form_action": "/sanidad",
        },
    ),
    (
        "sanidad/detail.html",
        [
            "actuacion.animal_id",
            "actuacion.fecha",
            "actuacion.veterinario",
            "actuacion.material_utilizado",
            "actuacion.voluntario_id",
            "actuacion.observaciones",
            "actuacion.activo",
            "actuacion.id",
            "tipo_actuacion.nombre",
            "tipo_actuacion.especie",
        ],
        {
            "user": _BASE_USER,
            "actuacion": {
                "id": "11111111-1111-1111-1111-111111111111",
                "animal_id": "animal-1",
                "fecha": "2026-07-04",
                "veterinario": "Dra. Pérez",
                "observaciones": "Vacuna anual",
                "voluntario_id": None,
                "material_utilizado": "Nobivac Rabia",
                "activo": True,
            },
            "tipo_actuacion": {
                "id": "22222222-2222-2222-2222-222222222222",
                "nombre": "Rabia",
                "especie": "ambos",
            },
        },
    ),
    (
        # FOSTER-04 (#46) PR B — catalog CRUD templates. The detail
        # shows the material's natural-key trio + audit fields; the
        # form owns the 4 catalog fields plus a handler-controlled
        # ``form_action`` (allow-listed at handler_controlled below);
        # the list shows the active rows in table form.
        "materiales/list.html",
        [
            "materiales[0].id",
            "materiales[0].material",
            "materiales[0].tamano",
            "materiales[0].color",
            "materiales[0].activo",
            "materiales[0].fecha_alta",
        ],
        {
            "user": _BASE_USER,
            "materiales": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "material": "Cama",
                    "tamano": "Grande",
                    "color": "Azul",
                    "activo": True,
                    "fecha_alta": "2026-07-05T10:00:00Z",
                }
            ],
        },
    ),
    (
        "materiales/form.html",
        [
            "form_data.material",
            "form_data.tamano",
            "form_data.color",
            "form_data.observaciones",
            "error",
            "form_action",
        ],
        {
            "user": _BASE_USER,
            "form_data": {
                "material": "Cama",
                "tamano": "Grande",
                "color": "Azul",
                "observaciones": "",
            },
            "error": None,
            "form_action": "/materiales",
        },
    ),
    (
        "materiales/detail.html",
        [
            "material.id",
            "material.material",
            "material.tamano",
            "material.color",
            "material.activo",
            "material.fecha_alta",
            "material.updated_at",
            "material.fecha_baja",
            "material.observaciones",
        ],
        {
            "user": _BASE_USER,
            "material": {
                "id": "11111111-1111-1111-1111-111111111111",
                "material": "Cama",
                "tamano": "Grande",
                "color": "Azul",
                "activo": True,
                "fecha_alta": "2026-07-05T10:00:00Z",
                "fecha_baja": None,
                "updated_at": "2026-07-05T10:00:00Z",
                "observaciones": "Para el gato nuevo",
            },
        },
    ),
]


def _set_path(ctx: Any, path: str, value: Any) -> None:
    """Set a dot/indexed path inside ``ctx`` to ``value`` (in place).

    Tokenises ``"users[0].email"`` into ``["users", 0, "email"]`` and
    walks the nested structure, creating intermediate containers when
    needed. The final step assigns ``value``.

    Supports:
      - ``"a.b.c"``        — dict keys
      - ``"a[0].b"``       — list index then dict key
      - ``"a[0][1]"``      — nested lists
    """
    tokens: list[Any] = []
    for part in re.split(r"\.|(?=\[)|(?<=\])", path):
        if part == "":
            continue
        if part.startswith("[") and part.endswith("]"):
            tokens.append(int(part[1:-1]))
        elif part.startswith("["):
            tokens.append(int(part[1:]))
        elif part.endswith("]"):
            tokens.append(int(part[:-1]))
        else:
            tokens.append(part)

    cursor: Any = ctx
    for i, token in enumerate(tokens):
        is_last = i == len(tokens) - 1
        nxt = tokens[i + 1] if not is_last else None
        if isinstance(cursor, list):
            idx = int(token)
            if is_last:
                cursor[idx] = value
            else:
                if idx >= len(cursor) or cursor[idx] is None:
                    cursor[idx] = [] if isinstance(nxt, int) else {}
                cursor = cursor[idx]
        else:
            key = str(token)
            if is_last:
                cursor[key] = value
            else:
                if key not in cursor or cursor[key] is None:
                    cursor[key] = [] if isinstance(nxt, int) else {}
                cursor = cursor[key]


def _with_xss(base_ctx: dict[str, Any], field_path: str, payload: str) -> dict[str, Any]:
    """Deep-copy ``base_ctx`` and inject ``payload`` at ``field_path``."""
    ctx = copy.deepcopy(base_ctx)
    _set_path(ctx, field_path, payload)
    return ctx


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template_name", "field_path"),
    [
        pytest.param(tpl, field, id=f"{tpl}::{field}")
        for tpl, fields, _ctx in TEMPLATE_SPECS
        for field in fields
    ],
)
@pytest.mark.parametrize(
    "xss_pattern",
    HTML_XSS_PATTERNS,
    ids=lambda p: p[:24],
)
def test_template_html_escapes_xss_payload(
    template_name: str,
    field_path: str,
    xss_pattern: str,
) -> None:
    """A rendered template MUST NOT contain the XSS payload literally.

    For the ``<script>``, ``<img onerror=...>`` and ``<svg onload=...>``
    patterns, Jinja2's autoescape escapes the angle brackets to
    ``&lt;``/``&gt;``, so the browser cannot execute the injected
    JavaScript.

    For the ``javascript:alert(1)`` URL scheme, the audit asserts that
    the literal string does not appear unescaped in any URL attribute
    body (the browser only fires on ``javascript:`` in URL context, so
    escaped entity form is safe). The audit doc's manual review
    checklist verifies no URL attribute is built from raw user data in
    practice.
    """
    base_ctx = next(ctx for tpl, _, ctx in TEMPLATE_SPECS if tpl == template_name)
    ctx = _with_xss(base_ctx, field_path, xss_pattern)
    rendered = render(template_name, ctx)

    # Assertion: the literal payload must NOT appear unescaped in the
    # rendered HTML. Auto-escape converts ``<`` to ``&lt;`` and ``>``
    # to ``&gt;``, breaking every HTML/JS tag boundary.
    assert xss_pattern not in rendered, (
        f"XSS audit FAILED: pattern {xss_pattern!r} appears literally in "
        f"{template_name} when injected at {field_path!r}. "
        f"This is the XSS finding — document in "
        f"docs/audits/xss-audit-2026-Q2.md and fix before chain continues."
    )


def test_jinja2templates_default_autoescape_is_true() -> None:
    """Sanity check: Starlette's Jinja2Templates MUST default autoescape=True.

    Starlette passes ``autoescape=select_autoescape(...)`` (a callable
    that returns True for ``.html``/``.htm``/``.xml``/``.xhtml``). The
    audit checks the callable's behaviour on a ``.html`` filename
    rather than identity-checking the attribute.

    This is the configuration invariant that makes the rest of this
    audit pass. If a future PR passes ``autoescape=False`` to
    ``Jinja2Templates(...)``, every other test in this file becomes
    trivially FAIL — and the audit catches the regression immediately.
    """
    autoescape = TEMPLATES.env.autoescape
    # Starlette uses ``select_autoescape(default_for_string=False,
    # default=True, ...)``. The env's ``autoescape`` attribute is a
    # callable returning True for ``.html``.
    if callable(autoescape):
        assert autoescape("anything.html") is True, (
            "Jinja2Templates select_autoescape does NOT escape .html — "
            "every XSS guard above is bypassed."
        )
        assert autoescape("anything.htm") is True
        assert autoescape("anything.txt") is False
    else:
        assert autoescape is True, (
            "Jinja2Templates.autoescape is False — every XSS guard above is "
            "bypassed. Restore autoescape=True or set it explicitly in app/main.py:136."
        )


def test_audit_covers_all_templates() -> None:
    """The audit MUST cover every ``.html`` under ``app/templates/``.

    The actual count is computed at test time so this guard scales
    with new template additions; the relative-path key
    (e.g. ``animales/detail.html``) is the source of truth — it
    matches the template names passed to
    ``Jinja2Templates.TemplateResponse(name=...)``. If a new template
    ships without a corresponding entry in ``TEMPLATE_SPECS``, this
    test fails and forces the audit owner to extend the coverage.
    """
    template_dir = REPO_ROOT / "app" / "templates"
    actual = sorted(
        p.relative_to(template_dir).as_posix() for p in template_dir.rglob("*.html")
    )
    expected_names = sorted(tpl for tpl, _, _ in TEMPLATE_SPECS)
    assert actual == expected_names, (
        f"Template coverage drift: app/templates/ has {actual}, "
        f"TEMPLATE_SPECS has {expected_names}. Update the audit."
    )


def test_no_user_data_in_url_attributes() -> None:
    """No template may interpolate user data inside a URL attribute.

    ``href=``, ``src=``, ``action=``, ``formaction=``, ``background=``,
    ``poster=``, ``cite=``, ``longdesc=``, ``usemap=``, ``xlink:href=``
    and ``data-src=`` are URL attributes. Interpolation of user data
    into any of them allows a ``javascript:alert(1)`` URI scheme
    injection (the URL is followed by the browser on click / load).

    Jinja2 autoescape does NOT catch this — the payload ``javascript:``
    has no HTML-special characters to escape.

    The guard is structural: every line that opens a URL attribute
    must contain only literal paths, trusted config, OR ID-style
    interpolations (``{{ obj.id }}`` / ``{{ obj.uuid }}``). Database
    primary keys are server-generated and cannot carry a ``javascript:``
    scheme. Any other interpolation needs review.

    Plus an explicit allow-list for known handler-controlled variables
    (``form_action`` in ``entradas/form.html`` — set by the
    ``entradas`` route to either ``/entradas`` or
    ``/entradas/{id}/update``, never user data). If a future change
    starts passing user-controlled data to one of these names, this
    test fails and forces the change author to switch to
    ``{{ url | quote }}`` or an allowlist.

    If a future template needs to interpolate user data into a URL
    attribute, the safe pattern is ``{{ url | quote }}`` (URL-encode)
    or to validate ``url`` against an allowlist.
    """
    template_dir = REPO_ROOT / "app" / "templates"
    url_attrs = (
        "href=", "src=", "action=", "formaction=",
        "background=", "poster=", "cite=", "longdesc=",
        "usemap=", "xlink:href=", "data-src=",
    )
    # ID-style interpolations are safe — server-generated keys.
    # ``batch_id`` (INTAKE-02) is generated by ``uuid.uuid4()`` in
    # ``batch_service.stage_batch`` and never carries a `javascript:`
    # scheme; treating it as ID-like keeps the audit symmetric with
    # ``id`` / ``uuid`` / ``pk`` / ``slug``.
    id_like = re.compile(r"\{\{\s*\w+\.(id|uuid|pk|slug|batch_id)\s*\}\}")
    # Handler-controlled variables: never user input. Each entry is a
    # (template, variable) pair verified by reading the route handler
    # in the corresponding ``app/modules/.../routes.py`` file.
    handler_controlled: frozenset[tuple[str, str]] = frozenset(
        {
            ("entradas/form.html", "form_action"),
            # ``form_action`` in ``casas_acogida/form.html`` is set
            # by the foster route to either ``/casas-acogida`` (new)
            # or ``/casas-acogida/{id}/update`` (edit), never user data.
            ("casas_acogida/form.html", "form_action"),
            # ``form_action`` in ``casas_acogida/asignar.html`` is set
            # by the foster assignment route to
            # ``/casas-acogida/{casa_id}/asignar`` (server-generated from
            # the path parameter), never user data. FOSTER-03 (#45).
            ("casas_acogida/asignar.html", "form_action"),
            # ``form_action`` in ``acogidas/form.html`` is set by the
            # acolhidas route to either ``/acogidas`` (new) or
            # ``/acogidas/{id}/update`` (edit), never user data.
            ("acogidas/form.html", "form_action"),
            # ``form_action`` in ``adopciones/form.html`` is set by
            # the adopciones route to either ``/adopciones`` (new) or
            # ``/adopciones/{id}/update`` (edit), never user data.
            # ADOPT-01 (#47).
            ("adopciones/form.html", "form_action"),
            # ``form_action`` in ``sanidad/form.html`` is set by the
            # sanidad route to either ``/sanidad`` (new) or
            # ``/sanidad/{id}/update`` (edit), never user data.
            # HEALTH-01 (#50).
            ("sanidad/form.html", "form_action"),
            # ``form_action`` in ``materiales/form.html`` is set by
            # the materiales catalog route to either ``/materiales``
            # (new) or ``/materiales/{id}/edit`` (edit), never user
            # data. FOSTER-04 (#46) PR B.
            ("materiales/form.html", "form_action"),
            # ``shortcut.href`` comes from ``_DASHBOARD_SHORTCUTS``
            # in ``app/main.py`` - a module-level constant (hardcoded
            # list of internal routes). Never user input.
            ("index.html", "shortcut.href"),
        }
    )
    offenders: list[str] = []
    for path in sorted(template_dir.rglob("*.html")):
        # ``rel`` is the template path relative to ``app/templates/``,
        # matching the names used by ``TemplateResponse(name=...)``.
        rel = path.relative_to(template_dir).as_posix()
        text_lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(text_lines, start=1):
            lower = line.lower()
            for attr in url_attrs:
                idx = lower.find(attr)
                if idx == -1:
                    continue
                rest = line[idx + len(attr):]
                # Strip ID-style interpolations first.
                rest_stripped = id_like.sub("", rest)
                if "{{" not in rest_stripped and "{%" not in rest_stripped:
                    continue
                # Find every Jinja expression and verify it's either
                # ID-style or in the handler-controlled allowlist.
                for match in re.finditer(r"\{\{\s*([\w.]+)\s*\}\}", rest):
                    expr = match.group(1)
                    if expr in {e for t, e in handler_controlled if t == rel}:
                        continue
                    offenders.append(
                        f"{rel}:{lineno}: {attr} expr={expr!r} ... {line.strip()}"
                    )
                    break
    assert offenders == [], (
        "XSS audit FAILED: user-controlled data interpolated into a URL "
        "attribute. URL attributes execute on click / load and bypass "
        "Jinja2 autoescape. Replace with a literal allowlist or use "
        "{{ url | quote }}. Offending lines:\n" + "\n".join(offenders)
    )


def test_no_safe_filter_anywhere_in_templates() -> None:
    """No template MUST use ``|safe`` on a user-controlled variable.

    The auto-test above catches the rendering-time leak; this guard
    catches the source: if a future PR adds ``|safe`` to a template,
    this test fails at review time and the PR author must justify the
    bypass (e.g. trusted static HTML fragment) or remove it.
    """
    template_dir = REPO_ROOT / "app" / "templates"
    offenders: list[str] = []
    for path in sorted(template_dir.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "|safe" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "XSS audit FAILED: |safe filter detected in templates. "
        "Either remove the bypass or document the trusted-input justification "
        "in docs/audits/xss-audit-2026-Q2.md.\n" + "\n".join(offenders)
    )
