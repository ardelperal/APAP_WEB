# Setup local de desarrollo

[Back to Codebase Guide](CODEBASE-GUIDE.md)

> Documento en proceso de traducción al castellano. El contenido nuevo (Fase 1 — esqueleto) ya está en castellano; el contenido heredado en inglés se traducirá en una iteración posterior (issue pendiente en el roadmap).

Esta guía explica cómo preparar el entorno local para trabajar en APAP_WEB. Cubre la gestión de secretos por desarrollador y los comandos de arranque del esqueleto (Fase 1). No posee los comandos canónicos de test, lint y build — esos viven en [`docs/development.md`](development.md), que es el manual operativo canónico para esos flujos.

## Prerrequisitos

| Herramienta | Versión mínima | Motivo |
|---|---|---|
| Python | 3.11 | Pinneado en `pyproject.toml` (`requires-python = ">=3.11"`) |
| Node.js | 18+ | Necesario para `npx @tailwindcss/cli` (build de CSS) |
| npm | 10+ | Incluido con Node 18+ |
| OpenCode CLI | cualquiera reciente | Cliente de IA preferido para el proyecto |

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

### 4. Arrancar la app local

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

### 5. Verificar los tests

```bash
make test
# o directo
.venv\Scripts\python.exe -m pytest
```

Salida esperada: `17 passed` (3 de config, 3 de app, 5 de pages, 1 smoke, 5 de CI workflow).

## Por qué este patrón

- El proyecto se instala en un `.venv` local. Esto evita pisar dependencias de otras herramientas del sistema (opencode, hermes-agent) y mantiene el árbol reproducible.
- Tailwind v4 se compila a `app/static/css/output.css` antes del `serve`. En Docker la build la hace el stage de builder del `Dockerfile`; en local la hace `make css` o `make css-watch`.
- El `make run` es el atajo para el flujo local de "ver algo": compila CSS y arranca uvicorn en un solo comando.

## Core invariants

- **Python 3.11 es el piso**: pineado en `pyproject.toml` (`requires-python = ">=3.11"`). Bajar a 3.10 rompe el typecheck y el contrato con FastAPI 0.137.x.
- **`.venv` local obligatorio**: no instalar dependencias en el Python global. Mezclar con opencode o hermes-agent del sistema causa fallos de import que parecen bugs del proyecto.
- **Tailwind v4 vía npm, no CDN**: la build reproducible pasa por `tailwindcss/` + `npx`. Un `<link>` a CDN deja el bundle fuera de la cache y rompe el contrato del arnés.
- **Node 18+ requerido por el CLI de Tailwind**: `npx @tailwindcss/cli` requiere Node 18 LTS o superior; npm 10 viene incluido.

## Contributor checklist

- [ ] Verificar `python --version` devuelve `3.11.x` (o superior compatible) antes de clonar el repo.
- [ ] Crear el `.venv` desde la raíz del proyecto y activarlo en cada terminal; confirmar `which python` apunta a `.venv/bin/python`.
- [ ] Ejecutar `make css && make serve` y abrir `http://127.0.0.1:8000/healthz` para confirmar el JSON de health antes de seguir.
- [ ] Ejecutar `make test` y confirmar `17 passed` (o la cifra actual de la suite) antes de abrir una PR.
- [ ] Si trabaja en Windows PowerShell, usar siempre los bloques `powershell` listados en cada paso; los `bash` no aplican directamente.
- [ ] Si mueve o recrea el worktree, ejecutar `python -m pip install -e ".[dev]"` otra vez para refrescar la ruta absoluta del editable.

## Navigation

Previous: [Design tokens APAP actual](design-tokens-apap-actual.md) | Next: [Development workflow](development.md)
