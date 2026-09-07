# Changelog

Todos los cambios relevantes de APAP_WEB se documentan aquí. El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto respeta [Semantic Versioning](https://semver.org/).

## Where to find release notes

Las notas detalladas por tag viven en GitHub Releases; este changelog agrega los cambios con la perspectiva histórica del proyecto.

- [GitHub Releases](https://github.com/ardelperal/APAP_WEB/releases) — notas detalladas por tag
- [docs/roadmap.md](docs/roadmap.md) — hoja de ruta viva (fases y transversales)

## Unreleased

### Removed

- `chore(secrets)`: drop InsForge settings fields and validation gate (closes #658):
    - `app/core/config.py`: drop fields `insforge_url`, `insforge_anon_key`, `insforge_service_key`; drop the `_validate_secrets` gate for `APAP_INSFORGE_SERVICE_KEY`; update module + `Settings` docstrings.
    - `app/core/di/auth_dependencies_session_di.py`: drop the dead `AttributeError` fallback in `get_insforge_client_dep` that constructed `InsForgeClient(settings.insforge_url, ...)` — the lifespan always wires `sql_executor`. Function now just yields `request.app.state.sql_executor`.
    - `app/core/tasks/scheduler.py`: replace `InsForgeClient(settings.insforge_url, settings.insforge_service_key)` with `LocalPostgresExecutor(settings.local_db_url)`; drop the `client.close()` call (LocalPostgresExecutor manages per-call connections).
    - `tests/test_config.py`: replace 5 atoms that asserted `insforge_*` field existence with atoms that assert `AttributeError` on access and that `_validate_secrets` does not require the InsForge key.

### Notes

- `migration/cli.py:639-640` and `migration/storage_spike.py:406-407` still read the removed fields. These are CLI-tool paths covered by issue #8 (migration package rewrite); the migration tests don't run on PR CI.

## v0.1.0 — 2026-08-01

- `chore(config)`: drop InsForge from the deployment surface (closes #654):
    - `Dockerfile`: drop `ENV APAP_INSFORGE_URL=http://localhost:7130` (the container no longer references InsForge).
    - `coolify/apap-web-coolify.yaml`: drop `APAP_INSFORGE_URL` and `APAP_INSFORGE_SERVICE_KEY` from the env list and the operator secret list.
    - `pyproject.toml`: drop `"insforge"` from `keywords`; clean two stale comment references to `docs/architecture/architecture-insforge-stack.md`.
    - `opencode.json.example`: delete (the only entry was the `@insforge/mcp@latest` MCP server).
    - `tests/test_coolify_web_yaml.py`: drop the two `APAP_INSFORGE_*` entries from the env-contract pin.
    - `docs/setup.md`: drop the "Configurar el MCP de InsForge" step and the InsForge prerequisite row.
    - `docs/runbooks/operator-deploy-2026.md`: drop `APAP_INSFORGE_SERVICE_KEY` from the required secrets list.
    - `docs/runbooks/startup-config-validation.md`: drop all 5 `APAP_INSFORGE_SERVICE_KEY` mentions; rewrite the local-validation example.

### Notes

- `app/core/config.py` still defines `insforge_url`, `insforge_anon_key`, and `insforge_service_key` — those are removed in #5 once the consumer code is gone. `tests/migration/test_insforge_storage_methods.py` and its `.gitleaksignore` allowlist are removed in #7.

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