# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""A file with no complexity at all and an enormous mutation surface.

Every function here is trivial and every one passes the complexity and CRAP ceilings. The file
is still a bad place to change anything, because a mutation run has to cover every one of these
literals. Surface is a property of the file, not of any single function — which is exactly the
gap this gate fills.
"""

DEFAULTS = {
    "host": "localhost",
    "port": "8000",
    "scheme": "https",
    "timeout": "30",
    "retries": "3",
    "backoff": "2",
    "pool_size": "10",
    "pool_overflow": "5",
    "echo": "false",
    "locale": "es_ES",
    "timezone": "Europe/Madrid",
    "currency": "EUR",
    "page_size": "25",
    "max_upload": "10485760",
    "session_ttl": "3600",
    "csrf_ttl": "1800",
    "login_attempts": "5",
    "lockout_seconds": "900",
    "password_min": "12",
    "password_rounds": "12",
    "smtp_host": "smtp.local",
    "smtp_port": "587",
    "smtp_tls": "true",
    "log_level": "INFO",
    "log_format": "json",
    "metrics_path": "/metrics",
    "health_path": "/health",
    "static_path": "/static",
    "media_path": "/media",
    "cache_ttl": "300",
}

FEATURE_FLAGS = {
    "expedientes": "true",
    "lanzadera": "true",
    "informes": "false",
    "exportacion": "false",
    "auditoria": "true",
    "notificaciones": "false",
    "adjuntos": "true",
    "firma": "false",
    "sso": "false",
    "mfa": "true",
    "api_publica": "false",
    "webhooks": "false",
    "bulk_import": "false",
    "soft_delete": "true",
    "versionado": "true",
    "plantillas": "false",
    "calendario": "false",
    "geolocalizacion": "false",
    "impresion": "true",
    "etiquetas": "true",
    "busqueda_avanzada": "false",
    "panel_kpi": "false",
    "modo_oscuro": "true",
    "accesibilidad": "true",
    "traduccion": "false",
}


def get(name: str) -> str:
    return DEFAULTS[name]


def flag(name: str) -> str:
    return FEATURE_FLAGS[name]
