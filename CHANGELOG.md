# Changelog

Todos los cambios relevantes de APAP_WEB se documentan aquí. El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto respeta [Semantic Versioning](https://semver.org/).

## Where to find release notes

Las notas detalladas por tag viven en GitHub Releases; este changelog agrega los cambios con la perspectiva histórica del proyecto.

- [GitHub Releases](https://github.com/ardelperal/APAP_WEB/releases) — notas detalladas por tag
- [docs/roadmap.md](docs/roadmap.md) — hoja de ruta viva (fases y transversales)

## Unreleased

### Added

- `docs(repo): add DOCS.md, CONTRIBUTING.md, CHANGELOG.md, SECURITY.md and CODEOWNERS at repo root (closes #552)`.

## v0.1.0 — 2026-08-01

Versión de referencia del primer corte de auditoría pública. Cubre el esqueleto FastAPI + HTMX + Jinja2 con backend InsForge, los módulos de dominio en producción y la cadena de gates de calidad.

### Added

- `app(main)`: landing `/`, healthz, login, callback OAuth Google vía proxy InsForge, logout y unauthorized.
- `app(core)`: sesión firmada (`itsdangerous`), `CsrfMiddleware`, `log_safe` con redacción de 12 campos, `require_authorized_user` con caché TTL, rate limiting y middleware de seguridad.
- `app(modules)`: animals, voluntarios, entradas (single + batch), foster, acogidas, cesiones, adopciones, sanidad (single + batch), salud (terapias + recomendaciones), tareas, materiales.
- `app(admin)`: panel `/admin` con alta y desactivación de usuarios para rol `developer`.
- `docs(proceso)`: playbook operativo de issue (preflight → cierre con evidencia).
- `docs(architecture-insforge-stack)`: target de stack, reglas InsForge, despliegue Coolify.
- `ci(.github/workflows/ci.yml)`: jobs `lint`, `typecheck`, `test`, `build`, `e2e`, `deploy` con cobertura `--cov-fail-under=80`.

### Changed

- `app(routes_registry)`: orden de `include_router` fijado para preservar precedencia entre paths dinámicos solapados (issue #204).

### Deprecated

- `docs(development)`: comandos legacy pendientes de traducir a Castellano peninsular formal.

### Breaking

- `app(modules)`: los routers con paths dinámicos solapados requieren el orden de `include_router` fijado en `app/routes_registry.py`. Reordenar routers rompe la precedencia.

## Breaking changes

| Versión anterior | Versión nueva | Migración |
|---|---|---|
| `<old API>` | `<new API>` | `<steps>` |

[← Back to README](README.md) · [Next: DOCS →](DOCS.md)