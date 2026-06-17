# Setup local de desarrollo

> Documento en proceso de traducción al castellano. El contenido nuevo (Fase 1 — esqueleto) ya está en castellano; el contenido heredado en inglés se traducirá en una iteración posterior (issue pendiente en el roadmap).

Esta guía explica cómo preparar el entorno local para trabajar en APAP_WEB. Cubre la configuración del MCP de InsForge, la gestión de secretos por desarrollador, y los comandos de arranque del esqueleto (Fase 1).

## Prerrequisitos

| Herramienta | Versión mínima | Motivo |
|---|---|---|
| Python | 3.11 | Pinneado en `pyproject.toml` (`requires-python = ">=3.11"`) |
| Node.js | 18+ | Necesario para `npx @tailwindcss/cli` (build de CSS) |
| npm | 10+ | Incluido con Node 18+ |
| OpenCode CLI | cualquiera reciente | Cliente de IA preferido para el proyecto |
| Cuenta InsForge | free tier | <https://insforge.app> |

## Setup único

### 1. Clonar el repositorio

```bash
git clone <repo-url>
cd APAP_WEB
```

PowerShell:

```powershell
git clone <repo-url>
Set-Location APAP_WEB
```

### 2. Crear el entorno virtual e instalar dependencias

El proyecto usa `.venv` local para no contaminar el Python global ni romper otras herramientas (opencode, hermes-agent, etc.) que viven en el sistema.

```bash
python3 -m venv .venv
source .venv/bin/activate            # POSIX
# .venv\Scripts\Activate.ps1         # PowerShell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Esto instala:

- El proyecto en modo editable (`import app.main` funciona).
- Dependencias de runtime: `fastapi`, `uvicorn[standard]`, `jinja2`, `pydantic`, `pydantic-settings`, `python-multipart`, `httpx`.
- Extras `[dev]`: `build`, `pytest`, `pytest-cov`, `ruff`.

### 3. Instalar las dependencias de Tailwind v4

Tailwind v4 se distribuye como paquete npm y se invoca con `npx`. La primera build (o el modo watch) lo descarga bajo demanda, pero es más reproducible instalarlo explícitamente:

```bash
cd tailwindcss
npm install
cd ..
```

PowerShell:

```powershell
cd tailwindcss
npm install
cd ..
```

### 4. Configurar el MCP de InsForge (opcional para Fase 1)

`opencode.json` contiene la clave de admin de InsForge, que **es un secreto**. Por eso está en `.gitignore` y se regenera desde la plantilla.

```powershell
Copy-Item opencode.json.example opencode.json
notepad opencode.json
```

Sustituir los placeholders:

| Placeholder | Reemplazar por |
|---|---|
| `ik_replace_me_with_your_insforge_admin_api_key` | Tu clave de admin de InsForge (panel → Settings → API keys) |
| `https://your-app-region.insforge.app` | URL de tu proyecto InsForge |

### 5. Arrancar la app local

Compila el CSS y levanta uvicorn en modo reload:

```bash
make run
# o paso a paso:
make css      # compila Tailwind v4 una vez (minified)
make serve    # uvicorn app.main:app --reload en 127.0.0.1:8000
```

PowerShell (sin `make`):

```powershell
cd tailwindcss; npx tailwindcss -i ./styles/app.css -o ../app/static/css/output.css --minify; cd ..
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Abre <http://127.0.0.1:8000> para ver el landing, <http://127.0.0.1:8000/healthz> para el JSON de health, y <http://127.0.0.1:8000/unauthorized> para la página de acceso denegado provisional.

### 6. Verificar los tests

```bash
make test
# o directo
.venv\Scripts\python.exe -m pytest
```

Salida esperada: `17 passed` (3 de config, 3 de app, 5 de pages, 1 smoke, 5 de CI workflow).

## Por qué este patrón

- `opencode.json` con la clave de admin **nunca se commitea** (`.gitignore`). Una clave filtrada en Git es un compromiso total de la base de datos y la autenticación del proyecto en InsForge.
- El proyecto se instala en un `.venv` local. Esto evita pisar dependencias de otras herramientas del sistema (opencode, hermes-agent) y mantiene el árbol reproducible.
- Tailwind v4 se compila a `app/static/css/output.css` antes del `serve`. En Docker la build la hace el stage de builder del `Dockerfile`; en local la hace `make css` o `make css-watch`.
- El `make run` es el atajo para el flujo local de "ver algo": compila CSS y arranca uvicorn en un solo comando.

## Relacionado

- `.gitignore` — contiene la regla que ignora `opencode.json` y `.venv/`.
- `opencode.json.example` — plantilla de la configuración de InsForge MCP.
- `docs/architecture-insforge-stack.md` — doc canónico de arquitectura.
- `docs/development.md` — guía de comandos canónicos (test, lint, build).
- `docs/roadmap.md` — hoja de ruta del proyecto (Fases 0-7 + transversales).
- `openspec/changes/ci-cd-foundation/` — change de SDD que planifica el pipeline de despliegue.
