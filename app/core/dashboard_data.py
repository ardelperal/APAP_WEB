"""Dashboard card and shortcut data for the APAP landing page.

Extracted from ``app/main.py`` so the factory module stays thin.
Issue #336.
"""

from __future__ import annotations

DASHBOARD_PENDING_CARDS: list[dict[str, str]] = [
    {
        "label": "Tareas pendientes",
        "description": "Tareas manuales y automáticas que requieren atención.",
        "href": "/tareas",
    },
    {
        "label": "Animales incoherentes",
        "description": "Revisa fichas con datos que necesitan contraste antes de continuar la gestión.",
    },
    {
        "label": "Pendientes de entrada",
        "description": "Animales que aún necesitan completar su entrada en protectora.",
    },
    {
        "label": "Pendientes de nueva situación",
        "description": "Fichas que esperan registrar el siguiente cambio de estado operativo.",
    },
    {
        "label": "Pendientes de chip",
        "description": "Animales cuya identificación debe comprobarse o completarse.",
    },
    {
        "label": "Cambio de titular pendiente",
        "description": "Casos que requieren seguimiento hasta cerrar el cambio de titularidad.",
    },
    {
        "label": "Fallecidos sin RIAC",
        "description": "Animales fallecidos con comunicación RIAC pendiente de registrar.",
    },
    {
        "label": "Impresos por entregar",
        "description": "Documentación preparada que todavía debe llegar a su destinatario.",
    },
    {
        "label": "Impresos entregados no recibidos",
        "description": "Documentos entregados que aún no constan como recibidos o adjuntados.",
    },
    {
        "label": "Seguimientos activos",
        "description": "Adopciones y casos abiertos que necesitan atención próxima.",
    },
    {
        "label": "Seguimientos totales",
        "description": "Vista de control para medir la carga completa de seguimiento.",
    },
]

DASHBOARD_SHORTCUTS: list[dict[str, str]] = [
    {"label": "Buscar animal", "href": "/animales", "description": "Consulta o actualiza una ficha."},
    {"label": "Nueva entrada", "href": "/entradas", "description": "Registra una llegada a protectora."},
    {"label": "Voluntarios", "href": "/voluntarios", "description": "Gestiona personas colaboradoras."},
]
