# APAP_WEB

APAP_WEB reemplaza el Access/VBA legacy de APAP con una aplicación web server-rendered para la gestión de animales, voluntarios y operaciones del refugio, construida sobre FastAPI + Jinja2 + InsForge y desplegada en Coolify.

[Quick Navigation](#quick-navigation) · [Roadmap](docs/roadmap.md) · [Proceso](docs/proceso.md) · [Arquitectura](docs/architecture-insforge-stack.md) · [Reglas del repo](AGENTS.md)

---

## Quick Navigation

| Sección | Para qué |
|---|---|
| [¿Qué es APAP_WEB?](#qué-es-apap_web) | Producto, anclas y audiencia. |
| [Features en producción](#features-en-producción) | Lo que ya corre en `main` por área de dominio. |
| [Pendiente (no en producción)](#pendiente-no-en-producción) | Roadmap abierto, agrupado por fase. |
| [Stack técnico](#stack-técnico) | Lenguaje, framework, backend, despliegue. |
| [Arquitectura](#arquitectura) | Diagrama request path browser → InsForge. |
| [Estructura del repo](#estructura-del-repo) | Carpetas y módulos a nivel de superficie. |
| [Quick start](#quick-start) | Clonar, venv, Tailwind, dev server. |
| [Configuración](#configuración) | Variables de entorno (`APAP_*`). |
| [Workflow de desarrollo](#workflow-de-desarrollo) | TDD, CodeGraph, gates locales, PR, revisión. |
| [CI/CD](#cicd) | Jobs de `.github/workflows/ci.yml` y despliegue. |
| [Seguridad](#seguridad) | Defensa en profundidad anclada en `AGENTS.md`. |
| [Índice de documentación](#índice-de-documentación) | Dónde mirar para cada pregunta. |

---

## ¿Qué es APAP_WEB?

APAP_WEB es la reescritura web de la herramienta interna que APAP (Asociación para la Atención de Personas con Autismo y otros Trastornos del Desarrollo) usa para operar el refugio de animales. La versión legacy corre en Microsoft Access / VBA sobre un único puesto, almacena todo en DAO y arrastra una deuda técnica que ninguna reescritura puede ignorar si quiere mantener los flujos diarios del equipo.

La reescritura se sostiene sobre tres anclas:

1. **Superset funcional del legacy (premisa P1 de fidelidad).** Cada capacidad del Access que el equipo usa —intake, asignación de casas de acogida, adopciones, actos sanitarios, cesiones, registro de voluntarios con mapeo de roles, catálogos sembrados desde Access— se conserva bit a bit o se reemplaza por un equivalente documentado en [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md). Las brechas descubiertas durante el trabajo se tratan como `type:bug` con label `gap:legacy`, nunca como omisión silenciosa.
2. **Acceso allowlisted por Google OAuth.** La autenticación la delega Google (proxy OAuth de InsForge); la autorización es una allowlist en `usuarios_autorizados`, revisada contra la fuente autoritativa en cada request (con caché de `APAP_AUTH_CACHE_TTL_SECONDS`, 300s por defecto; una desactivación surte efecto dentro de esa ventana). Solo `/healthz`, `/login`, `/auth/google`, `/auth/callback`, `/logout` y `/static` quedan fuera del allowlist.
3. **Server-rendered, JS mínimo, auditable.** Plantillas Jinja2, Tailwind v4 CSS-first (sin `tailwind.config.js`), un cliente `httpx` por request hacia InsForge. Toda acción que cambia estado pasa por el middleware CSRF y emite un evento estructurado `log_safe(...)` con redacción automática de 12 campos de PII.

El contrato autoritativo de la reescritura vive en tres documentos, que el README enlaza y nunca duplica:

- [`docs/roadmap.md`](docs/roadmap.md) — fases del producto y estado actual.
- [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) — decisiones de stack, reglas InsForge, target de despliegue.
- [`docs/proceso.md`](docs/proceso.md) — cómo llevar una issue de `open` a `closed` con evidencia.

---

## Features en producción

Los features listados están vivos en `main`. Cada fila referencia la issue que los entregó. Para detalle por módulo, ver [CODEBASE-GUIDE](docs/CODEBASE-GUIDE.md) (Tier 2 de #464 — pendiente de crear; mientras tanto, la estructura de `app/modules/` y los issues listados son la fuente autoritativa de qué hace cada módulo).

### Autenticación y sesión

| Feature | Issue / PR |
|---|---|
| Google OAuth 2.0 vía proxy InsForge, con PKCE (`/login` → `/auth/google` → `/auth/callback`). | #16, fix loop #125, logout fix #124 |
| Re-validación de autorización por request contra `usuarios_autorizados`, con caché TTL configurable. | #143, follow-ups #144, #145 |
| Middleware CSRF (`CsrfMiddleware`) sobre cada POST/PUT/PATCH/DELETE, con tokens vinculados a la sesión. | §10 de AGENTS.md |
| Cookies de sesión firmadas (`itsdangerous`), `HttpOnly`, `Secure`, `SameSite=Strict`; cookie PKCE en `Lax` para el rebote OAuth. | [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md) |

### Módulos de dominio (`app/modules/`)

| Módulo | Qué hace | Issues |
|---|---|---|
| `animals` | CRUD sobre `animales` con campos obligatorios Access; búsqueda paginada; soft-delete preserva historial; tabla append-only `animal_lifecycle_events`. | #28, #31, #67–68, #70–81, #129 |
| `voluntarios` | Registro de voluntarios con validación de campos núcleo; soft-delete preserva FK. | #34, #82–86 |
| `entradas` | Intake de animales (single + batch API); CTE atómico para batches; flujo de cesión por dueño. | #87–89, #40–42, #65 |
| `foster` | Red de casas de acogida con capacidad y especie preferida; `foster_capacity_overrides` audita cada excepción operativa. | #43, #45 (#44 aporta la FK) |
| `acogidas` | Estancias de acogida con FK estructurada a `casas_acogida` y `voluntarios`; helpers `compute_duracion` e `is_active`. | #44 |
| `adopciones` | CRUD con FKs a `animales` + `voluntarios` + `entradas`; detección de conflicto por clave natural `(animal_id, fecha_adopcion)`. | #47 |
| `sanidad` | Actos clínicos (`actuacion_sanitaria`) con validación D-24 (ISO, no futura, no anterior a `fecha_alta`). | #50 |
| `cesiones` | Transferencias de dueño atadas a `entrada_origen_id`. | #41 |

### Catálogos y panel admin

- **5 catálogos de referencia** (`catalogos_origenes`, `catalogos_motivos`, `catalogos_pruebas`, `catalogos_periodicidad`, `catalogos_tipos_contrato`), sembrados desde Access vía `INSERT ... ON CONFLICT DO NOTHING` idempotente. (#65 / CATALOG-01).
- **Panel `/admin`** para el rol `developer`: listar usuarios, alta por email + rol, desactivación. Construido sobre `require_developer_user_redirect`. (#146).

### Logging y operación

- **Logging estructurado con `log_safe`.** Toda emisión de logs bajo `app/` pasa por [`app/core/logging.py::log_safe`](app/core/logging.py), que redacta una lista cerrada de 12 campos (`email`, `session_token`, `jwt`, `oauth_code`, `pkce_verifier`, `csrf_token`, `pkce_challenge`, `authorization`, `cookie`, `referer`, `ip_address`, `x_forwarded_for`) antes de escribir el JSON a stdout.
- **Schema bootstrap en cold start.** El `lifespan` ejecuta en orden: `configure_logging` → `ensure_schema_and_seed` → `ensure_catalogs` (#65) → `ensure_domain_schema` → `apply_sql_migrations`. Cada paso es idempotente y falla rápido.
- **Linter de reglas del proyecto** vía `scripts/check_rules.py` (Detector 5–8: ban de `logger.*` y `print(...)` en `app/`, registro de CSRF middleware, `SameSite=Strict`). Se corre con `make check-rules`.

---

## Pendiente (no en producción)

El roadmap completo (Fases 3–7 + transversales) vive en [`docs/roadmap.md`](docs/roadmap.md) §3 con estado de cada fase, números de issue y referencia al change de OpenSpec. Resumen de lo abierto contra `main`:

- **Voluntarios** — VOL-02..05: junction `roles_voluntario`, pipeline de dedup fuzzy, migración FK nombre/DNI, gate de activo (#35–#38).
- **Foster** — FOSTER-04 asignación de material a estancias; atomicidad `record_override` ↔ `create_acogida` (#46, #142).
- **Adopciones** — ADOPT-03 state machine de 4 estados (#49). ADOPT-02 (#48) cancelada por defecto legacy — ver `openspec/changes/correct-preadoption-legacy-provenance/`.
- **Sanidad** — HEALTH-02..06: batch import, API resumen, terapias CRUD, motor de periodicidad, migración de pruebas (#51–#55).
- **Lifecycle animal** — state resolver estilo `DameSituacion()`, schema `estado_actual_animal`, API de búsqueda, cascada de cambio de chip (#29, #30, #33, #69).
- **Documentos e informes** — DOC-01..04 (PDFs contractuales, registro de uploads firmados, adjuntos polimórficos, migración legacy → object storage); REPORT-01..05 (constructor de queries parametrizado, ejecución server-side con export PDF/Excel, informe trimestral, motor de notificaciones, dashboard de contadores en vivo) (#56–#64).
- **RBAC** — matriz completa de permisos a nivel de API (#66).
- **Foundation UX/UI** (#6) y **motor de tareas** (#7) como transversales.

Para el detalle — issues abiertas por área, issues pendientes de crear, referencias cruzadas a discovery / legacy / decisiones — ver [`docs/roadmap.md`](docs/roadmap.md) §3 (estado por fase), §4 (abiertas), §5 (por abrir), §6 (índice de docs).

---

## Stack técnico

Pinned por [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) y `pyproject.toml`. El runtime levanta el suelo; producción corre la última línea estable.

| Área | Decisión | Notas |
|---|---|---|
| Lenguaje | Python 3.11+ | `requires-python = ">=3.11"` |
| Framework web | FastAPI (BFF) | Application boundary: routing, validación, reglas de negocio, autorización. |
| Servidor ASGI | Uvicorn (`uvicorn[standard]`) | Entrypoint de dev y producción. |
| Templates | Jinja2 | Páginas server-rendered; una carpeta `app/templates/<módulo>/` por dominio. |
| Validación y settings | Pydantic 2.13+ + `pydantic-settings` | Single source of truth para env vars en [`app/core/config.py`](app/core/config.py). |
| Cliente HTTP | httpx (sync `Client` por request vía `InsForgeClient`) | Un cliente por request, cerrado vía `yield`/`finally` en `get_insforge_client_dep`. |
| Firma de sesión | itsdangerous `URLSafeTimedSerializer` | Un secreto cacheado por proceso; rotación en [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md). |
| Auth | Google OAuth 2.0 vía proxy InsForge, PKCE | `/login` → `/auth/google` → `/auth/callback` → cookie firmada. |
| Parsing de forms | python-multipart | Requerido por FastAPI para forms y files. |
| Estilos | Tailwind CSS v4 (CSS-first, sin `tailwind.config.js`) | Compilado en build (etapa Node 20) a `app/static/css/output.css`. |
| Backend gestionado | InsForge (PostgreSQL + PostgREST + Storage + Functions + Realtime + Auth) | Accedido por HTTP desde [`app/core/insforge.py`](app/core/insforge.py). |
| Inteligencia de código | CodeGraph (`@aroman22/codegraph-vba` + MCP `codegraph_explore`) | [`AGENTS.md`](AGENTS.md) §14. |
| Tests | pytest + pytest-cov | TDD red → green → refactor ([`docs/proceso.md`](docs/proceso.md) §4). El test concurrente de voluntarios requiere `APAP_E2E_BASE_URL` y se deselecciona en CI/local. |
| Lint | Ruff (`ruff check .`) | Más los detectores propios en [`scripts/check_rules.py`](scripts/check_rules.py). |
| Build | `python -m build` (backend hatchling) | Wheel consumido por el job `deploy` del webhook. |
| Container | Multi-stage Dockerfile (Node 20 para Tailwind, Python 3.11-slim para runtime) | Build verificado por `ci / build`. |
| Hosting | Coolify sobre VPS del proyecto | Auto-deploy vía webhook firmado al `push: main`. |

El SDK `@insforge/sdk` no se usa: no hay bundle JS en este repo ni frontend Node. El `InsForgeClient` en Python habla con los endpoints REST de InsForge (`/api/database/advance/rawsql`, `/api/auth/oauth/exchange`, etc.).

---

## Arquitectura

```text
+--------------------- browser ---------------------+
| HTML + Tailwind v4 (+ htmx mínimo cuando aplique) |
+----------------------+---------------------------+
                       | session cookie (SameSite=Strict, signed)
                       v
+----------------- FastAPI / Uvicorn ----------------+
| UADetectionMiddleware      (UA -> is_mobile)        |
| CsrfMiddleware             (POST/PUT/PATCH/DELETE)  |
| protect_user_facing_routes (cookie -> /login)       |
| require_authorized_user    (per-request, cached)    |
| routes (app/main.py + app/modules/<area>/routes.py)|
| services (app/modules/<area>/service.py)           |
+----------------------+-----------------------------+
                       | httpx.Client (per request, bearer service key)
                       v
+---------------- InsForge (managed) ----------------+
| PostgreSQL (advance/rawsql)                         |
| Auth (Google OAuth hosted proxy, /auth/oauth/*)    |
| Storage (object storage, en uso desde Fase 7)      |
+----------------------------------------------------+
```

El contrato por capas detallado vive en [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) (stack, reglas InsForge, herramientas MCP para infra), con detalle de auth y autorización en §"Authentication and authorization".

---

## Estructura del repo

Layout real (paths verificados por `ls`, no el árbol aspiracional de `architecture-insforge-stack.md`):

```text
APAP_WEB/
  app/
    main.py                      # FastAPI factory, lifespan, top-level routes
    core/                        # infra transversal (sin reglas de dominio)
      config.py                  # Pydantic-settings (prefijo APAP_*)
      auth.py                    # auth InsForge + usuarios_autorizados
      auth_dependencies.py       # require_authorized_user, _writer, _developer, ...
      auth_cache.py              # caché TTL para autorización por request (#143)
      csrf.py                    # CsrfMiddleware + tokens por sesión
      session.py                 # lectura/escritura/borrado de cookie firmada
      pkce.py                    # par PKCE
      insforge.py                # InsForgeClient + OAuth exchange + execute_sql
      logging.py                 # log_safe + redacción de 12 campos
      middleware.py              # UADetectionMiddleware + base context processor
      ua.py                      # clasificación is_mobile(UA)
      catalogs.py                # 5 catálogos de referencia (#65)
      domain.py                  # ensure_domain_schema (SQL del producto)
      migration/                 # runner de DDL versionado + CLI reconcile
    modules/                     # una carpeta por área de dominio
      animals/                   # routes.py + service.py (+ forms.py)
      voluntarios/               # routes.py + service.py
      entradas/                  # routes.py + service.py + batch_routes.py + batch_service.py
      foster/                    # routes.py + service.py + assignment_routes.py + assignment.py
      acogidas/                  # routes.py + service.py
      cesiones/                  # routes.py + service.py
      adopciones/                # routes.py + service.py
      sanidad/                   # routes.py + service.py
    templates/                   # Jinja2 (base.html, base_mobile.html, login.html,
                                # unauthorized.html, index.html, admin.html,
                                # <module>/{list,form,detail}.html)
    static/css/output.css        # Salida compilada de Tailwind v4
  tests/                         # suite pytest (TDD per docs/proceso.md §4)
    e2e/                         # Playwright (job CI separado)
  scripts/
    check_rules.py               # detectores propios
    check_audit_and_runbook.py   # ayuda de docs/PR
    coolify_webhook.py           # trigger de deploy Coolify con HMAC
    dev_server_no_lifespan.py    # arranque CI/dev sin bootstrap de InsForge
    pytest_plugin/               # coverage_gate.py + fixtures de linter
    ruff_plugin/                 # plugin APAP001
  docs/                          # documentación canónica (ver §"Índice de documentación")
  tailwindcss/                   # fuente Tailwind en Node + @tailwindcss/cli
  openspec/                      # workspace SDD
  .github/workflows/ci.yml       # pipeline CI
  Dockerfile                     # multi-stage (Node 20 + Python 3.11-slim)
  pyproject.toml                 # metadata + deps runtime
  AGENTS.md                      # reglas del repo para IAs (33 secciones)
  docs/proceso.md                # playbook operativo (preflight → issue → TDD → merge → close)
  docs/setup.md                  # setup local por desarrollador
  docs/roadmap.md                # hoja de ruta viva
  docs/architecture-insforge-stack.md
  docs/decisiones-proyecto.md    # registro formal de decisiones
```

---

## Quick start

```bash
git clone https://github.com/ardelperal/APAP_WEB.git
cd APAP_WEB

python -m venv .venv
.venv\Scripts\Activate.ps1                # PowerShell
# source .venv/bin/activate               # POSIX
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cd tailwindcss
npm install
npx @tailwindcss/cli -i ./styles/app.css -o ../app/static/css/output.css --minify
cd ..

# Copiar y editar secretos
Copy-Item opencode.json.example opencode.json     # PowerShell
# cp opencode.json.example opencode.json          # POSIX

# Arrancar dev server (uvicorn con --reload en 127.0.0.1:8000)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Abrir <http://127.0.0.1:8000/healthz> para el JSON health probe, o `/login` una vez configurados `APAP_GOOGLE_CLIENT_ID` y `APAP_GOOGLE_CLIENT_SECRET`. Walkthrough completo — setup del MCP de InsForge, gestión de secretos, atajo `make run` — en [`docs/setup.md`](docs/setup.md).

---

## Configuración

Toda la configuración runtime se lee de variables de entorno (o `.env`) con prefijo `APAP_`. Existen defaults para desarrollo local que permiten arrancar sin secretos; **producción debe override cada valor marcado como requerido**. La single source of truth es [`app/core/config.py`](app/core/config.py) (`Settings`): si esta tabla y el código divergen, gana el código (premisa P3 de `docs/proceso.md` §0).

| Variable | Propósito | Requerido en prod |
|---|---|---|
| `APAP_INSFORGE_URL` | URL base de InsForge (PostgREST-compatible). | sí |
| `APAP_INSFORGE_SERVICE_KEY` | Service key con privilegios para admin SQL (schema bootstrap, seed de catálogos, gestión de usuarios). Nunca exponer al browser. | sí |
| `APAP_INSFORGE_ANON_KEY` | JWT anónimo para uso cliente; el servidor no la usa hoy. | opcional |
| `APAP_GOOGLE_CLIENT_ID` | OAuth client id de Google. | sí |
| `APAP_GOOGLE_CLIENT_SECRET` | OAuth client secret de Google. | sí |
| `APAP_GOOGLE_REDIRECT_URI` | Callback OAuth registrado en Google; debe coincidir exacto (ej. `https://apap.romancaba.com/auth/callback` en prod). | sí |
| `APAP_INITIAL_ADMIN_EMAIL` | Email pre-sembrado como primer `developer` en `usuarios_autorizados` en el primer arranque. Vacío = no siembra. | recomendado en primer deploy |
| `APAP_SESSION_SECRET` | Secreto HMAC usado por `itsdangerous` para firmar las cookies de sesión. **Rotar fuerza un logout global** — [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md). | sí |
| `APAP_AUTH_CACHE_TTL_SECONDS` | TTL en segundos del caché de autorización por request. Default `300`. Bajar para revocación más estricta a costa de un SELECT extra por request. `0` desactiva el caché. | opcional |
| `APAP_CSRF_ENABLED` | Feature flag de `CsrfMiddleware`. Default `true`. Pasar a `false` solo en rollback de incidente — emite `csrf.disabled` por request. | mantener `true` |
| `APAP_LOG_LEVEL` | Nivel raíz del handler JSON a stdout. Default `INFO`. Valores desconocidos caen a `INFO` en runtime. | opcional |
| `APAP_DEBUG` | Toggle de comportamiento debug-only. Default `false`. | opcional |

Procedimiento de rotación de `APAP_SESSION_SECRET` (cuándo rotar, pre-deploy checklist, pasos en Coolify, verificación, rollback) en [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md).

---

## Workflow de desarrollo

El playbook end-to-end vive en [`docs/proceso.md`](docs/proceso.md). Highlights que el README necesita anclar:

- **TDD por defecto.** Red → green → refactor. Los tests van primero en `type:bug`, `type:feature` y `type:refactor`; `type:docs` y ops puros están exentos. ([`docs/proceso.md`](docs/proceso.md) §4).
- **CodeGraph antes de leer fuente.** `codegraph_explore` (MCP) y `codegraph explore` (CLI) son Read-equivalent; usar `Read`/`Grep`/`Glob` solo para confirmar un detalle que codegraph no cubrió. ([`AGENTS.md`](AGENTS.md) §14).
- **Gate de validación local** antes de commit + push (desde la raíz del repo):

  ```bash
  python -m pytest -W error::DeprecationWarning \
      --ignore=tests/e2e \
      --deselect tests/test_voluntarios_concurrent.py

  ruff check .
  python -m build
  python scripts/check_rules.py .
  ```

- **Sesiones de CodeGraph** arrancan con `codegraph status .` y confirman `[OK] Index is up to date` + un daemon vivo; correr `codegraph sync .` una vez tras crear un directorio top-level nuevo (no re-`init`).
- **Convenciones de commit y PR.** Conventional Commits en inglés; PR con `Closes #N` o `Refs #N`; PR bajo el presupuesto de revisión de 400 líneas (usar el skill `chained-pr` para trocear cuando se supere); review lenses (`code-review-expert` obligatorio cada slice, `judgment-day` adicional en diffs de alto riesgo) según [`AGENTS.md`](AGENTS.md) §17.
- **Pre-MVP single-branch.** Todo el trabajo va a `main`; las ramas no-`main` se borran tras merge. Post-MVP se revierte a `staging` + canal UAT — [`AGENTS.md`](AGENTS.md) §15.4.
- **Gate de cobertura de helpers.** Cualquier función que matchee `_row_to_*` o esté en `CRITICAL_HELPERS` debe tener 100% de cobertura de línea; [`scripts/pytest_plugin/coverage_gate.py`](scripts/pytest_plugin/coverage_gate.py) falla el build si no. ([`AGENTS.md`](AGENTS.md) §11).
- **Disciplina de logging.** Toda emisión de log bajo `app/` pasa por `log_safe(event, **fields)`; `logger.*` y `print(...)` están baneados por [`scripts/check_rules.py`](scripts/check_rules.py). ([`AGENTS.md`](AGENTS.md) §9).
- **Disciplina de CSRF.** Cada template de form renderiza `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` en todo `<form method="post">`; el middleware CSRF es el gate. ([`AGENTS.md`](AGENTS.md) §10).

---

## CI/CD

Pipeline en `.github/workflows/ci.yml` con cinco jobs:

| Job | Trigger | Qué hace |
|---|---|---|
| `lint` | PR + push a `main`/`staging`, manual | `ruff check .`; grep de secret-leak sobre `.github/`. |
| `typecheck` | PR + push a `main`/`staging`, manual | `python -m mypy` con flags de `[tool.mypy]` en `pyproject.toml` (alcance y opciones son single source of truth). |
| `test` | PR + push, tras `lint` | `pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py` con cobertura `--cov-fail-under=80` y `coverage.json` para el gate `CRITICAL_HELPERS`. |
| `build` | tras `test` | `python -m build` (wheel hatchling). |
| `e2e` | tras `build`, solo si `APAP_OAUTH_CLIENT_ID != ''` | Arranca dev server sin lifespan y corre Playwright. |
| `deploy` | `push: main` solo, tras lint/test/build, **skipped en merge commits** | Firma y POST al webhook de Coolify (HMAC SHA-256 con `COOLIFY_WEBHOOK_SECRET`). |

Los jobs `e2e` y `deploy` son condicionales: `e2e` se salta cuando el árbol `e2e/` está ausente o cuando faltan env vars OAuth; `deploy` se salta en merge commits (un push disparado por merge de PR no es un evento "deploy this change") y cuando `COOLIFY_WEBHOOK_URL` no está seteada.

El job `deploy` delega la firma HMAC a [`scripts/coolify_webhook.py`](scripts/coolify_webhook.py), cubierto end-to-end por la suite de tests; producción y CI comparten el mismo code path.

Para el contrato completo del pipeline, ver el bloque de comentario al tope de [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Seguridad

APAP_WEB sigue un modelo de defensa en profundidad anclado en [`AGENTS.md`](AGENTS.md) reglas §1–§17 más la `web-security-quality-baseline` cross-project.

- **Autorización re-validada por request.** La cookie firmada lleva identidad; la dependencia `require_authorized_user` re-consulta `usuarios_autorizados` (con caché `APAP_AUTH_CACHE_TTL_SECONDS`), así una desactivación surte efecto dentro de la ventana TTL en vez de esperar hasta 7 días a que la cookie expire. ([AGENTS.md](AGENTS.md) §1; web-security-baseline rule 1).
- **Cada rol declarado se enforce a nivel de route.** `reader` no puede escribir (vía `require_writer_user` por route), `developer` es el único rol permitido en `/admin` (`require_developer_user_redirect`), y la consolidación sobre `app.core.auth.Rol` saca los literales de rol del código de los handlers. (web-security-baseline rules 2, 7).
- **CSRF en profundidad.** `CsrfMiddleware` valida un token vinculado a la sesión en cada POST/PUT/PATCH/DELETE (vía header `X-CSRFToken` o campo `csrf_token` del form). Todo template de form renderiza `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`. Contrato en AGENTS §10.
- **Cookies de sesión** con `HttpOnly`, `Secure`, `SameSite=Strict`, firmadas con `itsdangerous`. La cookie PKCE durante el rebote OAuth va en `SameSite=Lax` para que el redirect top-level de Google pueda leerla.
- **Redacción de logs.** Toda llamada de log pasa por `app.core.logging.log_safe`, que redacta una lista cerrada de 12 campos (`email`, `session_token`, `jwt`, `oauth_code`, `pkce_verifier`, `csrf_token`, `pkce_challenge`, `authorization`, `cookie`, `referer`, `ip_address`, `x_forwarded_for`) antes de que el handler JSON escriba a stdout. AGENTS §9 + `scripts/check_rules.py` banean `logger.*` y `print(...)` directos en `app/`.
- **Defaults inseguros fallan rápido en producción.** `Settings` usa un placeholder no vacío para `session_secret` que permite desarrollo local; los deploys de producción lo overridean vía env vars en Coolify. `tests/test_config.py` pinea el contrato.
- **Ciclo de vida del cliente HTTP.** `InsForgeClient` se construye por request y se cierra vía la forma `yield`/`finally` de `get_insforge_client_dep`, así un único `httpx.Client` queda atado al scope del request.
- **Rate limiting** sobre login, OAuth callback y endpoints admin está en el rollout (rule 5 de la security baseline) y aterriza con el slice de hardening de staging.
- **Headers de seguridad** (`CSP`, `X-Frame-Options`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `HSTS` tras TLS) llegan con el slice del middleware de security headers; el stack actual sigue iterándolos (ver [`docs/audits/`](docs/audits/) para auditorías previas).
- **Secretos solo en env vars.** Nunca commiteados. `opencode.json` carga la admin key de InsForge y está `.gitignore`d; `scripts/check_rules.py` y `tests/test_ci_workflow.py` enforce el límite.
- **Cobertura de auditoría.** Cada slice sensible — desactivación de auth, cookies de callback OAuth, allowlist XSS, enforce RBAC, overflow de nav móvil, CRUD sanitario — tiene su propio doc de auditoría en `docs/audits/` (ej. `auth-revalidation-2026-Q3.md`, `rbac-enforcement-2026-Q3.md`, `xss-audit-2026-Q2.md`). Los cambios sensibles nuevos deben añadir o actualizar una auditoría según AGENTS §12.

Para la baseline cross-project de web security & quality que sostiene estas reglas, ver el bloque `web-security-quality-baseline` en [`AGENTS.md`](AGENTS.md).

---

## Índice de documentación

| Documento | Para qué |
|---|---|
| [`docs/roadmap.md`](docs/roadmap.md) | Hoja de ruta viva (Fases 0–7 + transversales). |
| [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) | Stack, reglas InsForge, target de despliegue. |
| [`docs/proceso.md`](docs/proceso.md) | Playbook operativo por issue (preflight → cierre con evidencia). |
| [`docs/setup.md`](docs/setup.md) | Setup local por desarrollador. |
| [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md) | Registro formal de decisiones (D-01–D-41). |
| [`docs/development.md`](docs/development.md) | Comandos de desarrollo local (legacy, pendiente de traducir). |
| [`docs/design-tokens-apap-actual.md`](docs/design-tokens-apap-actual.md) | Tokens de diseño heredados del legacy. |
| [`docs/hardening-2026-q2-rule-history.md`](docs/hardening-2026-q2-rule-history.md) | Tracker resuelto de conflictos del Q2 hardening. |
| `docs/discovery/` | Análisis de dominio: índice maestro en [`docs/discovery/README.md`](docs/discovery/README.md), con `business-feature-map.md`, `feature-01..04-*.md`, `data-model-notes.md`, `state-machines.md`. |
| `docs/legacy-*.md` | Análisis del legacy Access (no clonar UX; consultar solo para razonar paridad). |
| `docs/audits/` | Auditorías por slice sensible. |
| `docs/runbooks/` | Runbooks de operador (rotación de cookie, multi-worker auth cache). |
| [`AGENTS.md`](AGENTS.md) | Reglas del repo para IAs (33 secciones: code quality, seguridad, workflow de merge, disciplina del orquestador). |
| `openspec/changes/` | Cambios SDD históricos y activos (config en `openspec/config.yaml`). |

---

## Licencia

Propietaria. © APAP.
