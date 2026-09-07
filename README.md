# APAP_WEB

> Reescritura web server-rendered del Access/VBA de APAP para gestión de animales, voluntarios y operaciones del refugio; FastAPI + Jinja2 + LocalBackend, desplegada en Coolify.

![build](https://img.shields.io/github/actions/workflow/status/ardelperal/APAP_WEB/ci.yml?branch=main&label=build)
![license](https://img.shields.io/badge/license-proprietary-blue)
![python](https://img.shields.io/badge/python-3.11%2B-blue)

## Navegación rápida

| Sección | Para qué |
|---|---|
| [Inicio rápido](#inicio-rápido) | Clonar, venv, Tailwind, dev server. |
| [¿Qué es APAP_WEB?](#qué-es-apap_web) | Producto, anclas y audiencia. |
| [Estado del proyecto](#estado-del-proyecto) | Lo que corre en `main` y el roadmap abierto. |
| [Documentación](#documentación) | Dónde mirar para cada pregunta. |
| [Próximos pasos](#próximos-pasos) | Qué hacer después de leer este README. |

## Inicio rápido

```bash
git clone https://github.com/ardelperal/APAP_WEB.git
cd APAP_WEB

python -m venv .venv
source .venv/bin/activate               # o `.venv\Scripts\Activate.ps1` en PowerShell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cd tailwindcss
npm install
npx @tailwindcss/cli -i ./styles/app.css -o ../app/static/css/output.css --minify
cd ..

cp opencode.json.example opencode.json # o `Copy-Item` en PowerShell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Abra `http://127.0.0.1:8000/healthz` para el JSON health probe.
Para llegar a `/login` configure primero las variables `APAP_GOOGLE_*` listadas en [DOCS.md → Variables de entorno](DOCS.md#variables-de-entorno).
El setup completo — MCP de LocalBackend, gestión de secretos, atajos `make` — vive en [docs/setup.md](docs/setup.md).

## ¿Qué es APAP_WEB?

APAP_WEB es la reescritura web de la herramienta interna que APAP usa para operar el refugio de animales.
La versión legacy corre en Microsoft Access / VBA sobre un único puesto.
Esta reescritura conserva cada capacidad legacy o la reemplaza por un equivalente documentado, y se sostiene sobre tres anclas:

1. **Superset funcional del legacy (premisa P1).**
   Cada capacidad del Access usada por el equipo se conserva o se documenta como divergencia en [docs/architecture/decisiones-proyecto.md](docs/architecture/decisiones-proyecto.md).
   Las brechas se tratan como `type:bug gap:legacy`, nunca como omisión silenciosa.
2. **Acceso allowlisted por Google OAuth.**
   La autenticación delega en Google (proxy OAuth de LocalBackend).
   La autorización es una allowlist en `usuarios_autorizados`, revalidada por request con caché TTL configurable (`APAP_AUTH_CACHE_TTL_SECONDS`, 300 por defecto).
3. **Server-rendered, JS mínimo, auditable.**
   Plantillas Jinja2, Tailwind v4 CSS-first, cliente `httpx` por request hacia LocalBackend.
   Cada POST pasa por el middleware CSRF, y toda emisión de log usa `log_safe(...)` con redacción automática de doce campos de PII.

## Estado del proyecto

Los features vivos en `main` y el roadmap abierto por fase viven en [docs/roadmap.md](docs/roadmap.md).
El estado por módulo — auth y sesión, animales, voluntarios, intake, foster, acogidas, adopciones, sanidad, cesiones, catálogos y panel admin — se referencia desde dos páginas radiales:

- [docs/CODEBASE-GUIDE.md](docs/CODEBASE-GUIDE.md), hub navegable del repo.
- [docs/codebase/repository-map.md](docs/codebase/repository-map.md), ownership por paquete.

## Documentación

Cada documento ocupa un único rol.
Para superficies técnicas (rutas HTTP, env vars, status matrix) consulte [DOCS.md](DOCS.md).
Para reglas operacionales del repo lea [AGENTS.md](AGENTS.md).

| Doc | Audiencia | Léalo cuando |
|---|---|---|
| [AGENTS.md](AGENTS.md) | IAs | Necesita saber qué skill cargar para una tarea. |
| [DOCS.md](DOCS.md) | Humanos técnicos, IAs | Busca referencia técnica completa. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribuidores externos | Va a abrir un PR o reportar un issue. |
| [CHANGELOG.md](CHANGELOG.md) | Usuarios | Quiere saber qué cambió entre versiones. |
| [SECURITY.md](SECURITY.md) | Reportadores externos | Va a disclose una vulnerabilidad. |
| [CODEOWNERS](CODEOWNERS) | Bots de GitHub | Necesita saber quién revisa qué path. |
| [docs/CODEBASE-GUIDE.md](docs/CODEBASE-GUIDE.md) | Mantenedores | Necesita entender dónde vive cada responsabilidad. |
| [docs/proceso.md](docs/proceso.md) | Mantenedores | Va a llevar una issue de open a closed con evidencia. |
| [docs/roadmap.md](docs/roadmap.md) | Mantenedores | Quiere ver el estado por fase y por área. |
| [docs/architecture/decisiones-proyecto.md](docs/architecture/decisiones-proyecto.md) | Mantenedores | Busca una decisión arquitectónica formal (D-01…). |
| [docs/codebase/repository-map.md](docs/codebase/repository-map.md) | Mantenedores | Necesita saber qué paquete posee qué comportamiento. |
| [docs/codebase/merge-workflow.md](docs/codebase/merge-workflow.md) | Mantenedores | Necesita el detalle del pipeline CI/CD y la política de merge. |

## Próximos pasos

1. Configure las variables de entorno listadas en [DOCS.md → Variables de entorno](DOCS.md#variables-de-entorno) antes del primer arranque.
2. Ejecute la suite local con `pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py` y `ruff check .`.
3. Lea [AGENTS.md](AGENTS.md) si va a operar el repo con una IA; revise [docs/proceso.md](docs/proceso.md) si va a abrir una issue.
4. Para divergencias con el legacy Access, consulte [docs/architecture/decisiones-proyecto.md](docs/architecture/decisiones-proyecto.md) antes de cambiar comportamiento.

[← Repo root](README.md) · [Technical reference →](DOCS.md)

## Licencia

Propietaria. © APAP.
