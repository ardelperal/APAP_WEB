# Flujo de desarrollo

[Back to Codebase Guide](CODEBASE-GUIDE.md)

> Documento en proceso de traducción al castellano. El contenido nuevo (Fase 1 — esqueleto) ya está en castellano; el contenido heredado en inglés se traducirá en una iteración posterior (issue pendiente en el roadmap).

Esta guía lleva a un nuevo desarrollador desde un clone limpio hasta un test en verde en la aplicación APAP. Es la referencia canónica para los comandos locales. El workflow de CI (entregado en una PR anterior) y el job de deploy Coolify (CD-01, issue #1) llaman a los mismos comandos: el trabajo normal integra en `staging`, y producción queda guardada por `main`.

No posee el setup por desarrollador ni la configuración de secretos LocalBackend — eso vive en [`docs/setup.md`](setup.md). No posee las decisiones de arquitectura — eso vive en [`docs/architecture/architecture-local-backend-stack.md`](../architecture/architecture-local-backend-stack.md). No posee la disciplina de proceso por issue — eso vive en [`docs/proceso.md`](proceso.md).

Para setup del entorno por desarrollador y credenciales de LocalBackend MCP, ver [`docs/setup.md`](setup.md). Para las decisiones de arquitectura que dan forma a este flujo, ver [`docs/architecture/architecture-local-backend-stack.md`](../architecture/architecture-local-backend-stack.md).

## Prerrequisitos

| Herramienta | Versión mínima | Motivo |
|---|---|---|
| Python | 3.11 | Pinneado en `pyproject.toml` (`requires-python = ">=3.11"`). Coincide con la arquitectura y FastAPI 0.137.x. |
| pip | 23.0+ | Resolver moderno. |
| Git | 2.30+ | Para trabajar con feature branches. |
| GNU Make | cualquiera reciente | Opcional pero recomendado. El `Makefile` es la entrada de conveniencia; los comandos canónicos también funcionan directamente. |
| Node.js | 18+ | Necesario para `npx @tailwindcss/cli` (build de CSS, Fase 1+). |
| Cuenta LocalBackend | free tier | Para la integración del MCP. Ver `docs/setup.md`. |

Los usuarios de Windows pueden correr los mismos comandos en PowerShell. Los equivalentes cross-platform se listan bajo cada paso.

## Paso 1 — Clonar el repositorio

```bash
git clone <repo-url>
cd APAP_WEB
```

PowerShell:

```powershell
git clone <repo-url>
Set-Location APAP_WEB
```

## Paso 2 — Crear el entorno virtual e instalar dependencias

Un entorno virtual mantiene las dependencias de APAP aisladas del Python del sistema.

```bash
python3 -m venv .venv
source .venv/bin/activate            # POSIX
# .venv\Scripts\Activate.ps1         # PowerShell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

La línea `-e ".[dev]"` instala:

- El proyecto local en modo editable (para que `import app.main` funcione).
- Los extras `[dev]`: `build`, `pytest`, `pytest-cov`, `ruff`.

Si no tienes `make`, `python -m pip install -e ".[dev]"` es el único paso de instalación necesario.

### Reinstalar después de mover un worktree

La instalación editable guarda la ruta absoluta del checkout en un archivo
`.pth` del entorno virtual. Si mueves o vuelves a crear un worktree —incluido
el esquema de este repositorio, con `00_main` y worktrees hermanos— esa ruta
puede quedar obsoleta y provocar errores de importación engañosos.

Activa el entorno virtual y reinstala desde la raíz del worktree actual:

```bash
python -m pip install -e ".[dev]"
```

El comando es el mismo en Windows y Linux. Comprueba siempre que el directorio
actual sea el worktree que vas a usar antes de ejecutarlo.

## Paso 3 — Instalar las dependencias de Tailwind v4

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

`tailwindcss/package.json` declara `tailwindcss` y `@tailwindcss/cli` como devDependencies. La build real la lanza `make css` o `make css-watch` (o el builder del `Dockerfile` en producción).

## Paso 4 — Compilar el CSS y arrancar la app

El comando canónico de "ver algo" en local es:

```bash
make run
```

Esto ejecuta, en secuencia, `make css` (compila Tailwind v4 una vez en modo minificado) y `make serve` (uvicorn en `127.0.0.1:8000` con `--reload`).

Si prefieres paso a paso:

```bash
make css       # una build minified
make css-watch # build incremental con watch (deja el proceso corriendo)
make serve     # uvicorn 127.0.0.1:8000 --reload
```

PowerShell (sin `make`):

```powershell
cd tailwindcss; npx tailwindcss -i ./styles/app.css -o ../app/static/css/output.css --minify; cd ..
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Una vez levantado, abre:

- <http://127.0.0.1:8000/> — landing con esqueleto.
- <http://127.0.0.1:8000/healthz> — JSON de health (usado por CD-02).
- <http://127.0.0.1:8000/unauthorized> — página de acceso denegado provisional.

## Paso 5 — Ejecutar la suite de tests

El comando canónico de tests es `pytest`, con los flags de deprecation strictness bakeados en `pyproject.toml`.

```bash
pytest
```

Vía `Makefile`:

```bash
make test
```

PowerShell:

```powershell
.venv\Scripts\python.exe -m pytest
```

### Regresión concurrente TOCTOU con PostgreSQL

`tests/test_voluntarios_concurrent.py` comprueba el `UPDATE` atómico con dos
conexiones reales y, por tanto, necesita PostgreSQL. La variable canónica es
`APAP_TEST_POSTGRES_DSN`: contiene un **DSN de PostgreSQL de pruebas**.
`APAP_E2E_BASE_URL` no se reutiliza porque identifica una URL HTTP del servidor
web, no una conexión a la base de datos.

Usa una base desechable o una cuenta con permisos para crear y eliminar
esquemas. Cada prueba crea su propio esquema efímero y lo borra al terminar.

POSIX:

```bash
export APAP_TEST_POSTGRES_DSN='postgresql://postgres@127.0.0.1:5432/apap_test'
python -m pytest tests/test_voluntarios_concurrent.py -v
```

PowerShell:

```powershell
$env:APAP_TEST_POSTGRES_DSN = 'postgresql://postgres@127.0.0.1:5432/apap_test'
python -m pytest tests/test_voluntarios_concurrent.py -v
```

Si la variable falta, la prueba falla de forma explícita: no hace `skip` ni
simula el bloqueo con SQLite. En CI, el job `test` aprovisiona PostgreSQL como
servicio y define el DSN automáticamente.

### Salida esperada en verde

```text
============================= test session starts ==============================
platform win32 -- Python 3.11.x, pytest-9.x.x, pluggy-1.x.x
rootdir: <repo-root>
configfile: pyproject.toml
collected 17 items

tests\test_app.py ...                                                    [ 17%]
tests\test_ci_workflow.py .....                                          [ 47%]
tests\test_config.py ...                                                 [ 64%]
tests\test_pages.py .....                                                [ 94%]
tests\test_smoke.py .                                                    [100%]

============================= 17 passed in 0.5s ===============================
```

17 tests es el estado actual: 3 de `app.core.config`, 3 del entrypoint FastAPI, 5 de páginas HTML, 1 smoke, 5 del workflow de CI. La cifra crecerá con cada fase.

### Qué significa "en verde" aquí

- Todos los tests pasan.
- `pytest` sale con código 0.
- Ningún `DeprecationWarning` ni `PendingDeprecationWarning` se imprime (porque `pyproject.toml` los promueve a error y los tests no usan APIs deprecadas).
- `StarletteDeprecationWarning` (sobre `httpx` en `starlette.testclient`) está filtrada explícitamente con un comentario que documenta el porqué. Se quitará cuando starlette migre a `httpx2`.

Una corrida no-verde es un fallo de `make test` que hay que arreglar antes de abrir PR.

## Paso 6 — Ejecutar el linter

El comando canónico de lint es `ruff check .`, ejecutado sobre todo el repositorio.

```bash
ruff check .
```

Vía `Makefile`:

```bash
make lint
```

PowerShell:

```powershell
.venv\Scripts\python.exe -m ruff check .
```

### Salida esperada en limpio

```text
All checks passed!
```

Si ruff reporta violaciones, arregla el fichero/línea indicado. La selección de reglas (`E`, `F`, `W`, `I`, `UP`, `B`) está documentada en `pyproject.toml` § `[tool.ruff.lint]`. El workflow de CI corre el mismo comando y falla el build ante cualquier violación.

## Paso 7 — Build del paquete

El comando canónico de build es `python -m build`, que produce una wheel y un sdist en `dist/`.

```bash
python -m build
```

Vía `Makefile`:

```bash
make build
```

PowerShell:

```powershell
.venv\Scripts\python.exe -m build
```

### Salida esperada en verde

```text
* Creating sdist...
* Creating wheel...
Successfully built apap_web-0.1.0.tar.gz and apap_web-0.1.0-py3-none-any.whl
```

El directorio `dist/` está en `.gitignore`. Se puede borrar entre builds; el target `make clean` lo elimina junto con los caches de herramientas.

## Paso 8 — Ejecutar la verja verde de PR

`make verify` es el comando que refleja la CI en una pull request. Corre, en el mismo orden que `ci.yml`, los trece gates del job `lint`, luego `mypy`, luego pytest con el piso de cobertura y el ratchet de CRAP:

```bash
make verify
```

Una corrida en verde, sobre una rama al día con `main`, es la señal local de que la PR está lista para revisión: la CI no tiene nada más que descubrir.

`make all` es `make css` + `make verify`, para cuando además hace falta recompilar el bundle de Tailwind.

Lo que `verify` **no** corre, porque no se puede reproducir en una máquina de desarrollo:

| Job | Por qué queda fuera | Cómo correrlo |
|---|---|---|
| `mutation` | cosmic-ray es Linux-only y tarda; corre en un schedule semanal | `make mutation` (bajo WSL) |
| `security` / `security-deep` | gitleaks y trivy corren en Docker | por CI |
| `integration` | necesita un Postgres real | `pytest -m integration` con `APAP_TEST_POSTGRES_DSN` |
| `e2e` | necesita Playwright y OAuth configurado | ver la sección de E2E más abajo |

> La lista de gates de `verify` está clavada a `ci.yml` por
> `tests/test_ci_workflow.py::test_make_verify_covers_every_ci_gate`. Agregar un gate
> al workflow sin agregarlo al `Makefile` rompe ese test. Es a propósito: es lo único
> que mantiene las dos listas iguales con el tiempo.

## Workflow de CI y futuro hook E2E

El workflow de GitHub Actions corre los mismos comandos locales en pull requests a `staging` o `main`, y en pushes a `staging` o `main`:

| Job | Comando | Propósito |
|---|---|---|
| `ci / lint` | `ruff check .` | Lint estático y orden de imports. |
| `ci / test` | `python -m pytest -W error::DeprecationWarning` | Tests unitarios/integración con deprecations promovidas a error. |
| `ci / build` | `python -m build` | Validación de build del paquete. |

El workflow también incluye un job `ci / e2e` que corre la suite Playwright (9 tests contra un Chromium headless contra `scripts/dev_server_no_lifespan.py`). El server arranca sin el bootstrap de LocalBackend (lifespan no-op) así que las rutas públicas (`/`, `/healthz`, `/unauthorized`, redirect a `/login`) sirven y se pueden validar sin backend real. Para correrlo en local:

```bash
python -m pip install -e ".[dev]"
python -m playwright install --with-deps chromium
python scripts/dev_server_no_lifespan.py &
pytest tests/e2e/ -v
```

El job `ci / deploy` solo corre en push directo a `main` (no en PRs ni en merges), preservando el modelo staging-only del proyecto.

## Estructura del repositorio y worktrees

APAP_WEB usa git-worktree. La estructura canonical es:

```
APAP_WEB/                        ← root (gitdir: 00_main/.git — NO trabajar aquí)
├── 00_main/                     ← worktree canónico (唯一的 punto de trabajo)
│   ├── app/
│   ├── migration/
│   ├── scripts/
│   └── ...
├── APAP_WEB_worktrees/         ← worktrees hermanos (uno por feature/fix)
│   ├── wt-206-e2e-coverage/
│   ├── wt-223-ci-runner/
│   └── wt-326-docstring-drift/
└── .git                        ← FILE (no directorio): gitdir: 00_main/.git
```

**Regla: siempre trabajar desde `00_main/` o desde un worktree bajo `APAP_WEB_worktrees/`.**
Nunca ejecutar comandos de desarrollo (lint, test, check_rules) desde la raíz `APAP_WEB/`.

Cuando ejecutas `python scripts/check_rules.py .` desde la raíz `APAP_WEB/`, el linter detecta
que está en el layout plano (directorio con `00_main/` como subdirectorio y `.git` como archivo)
y falla con un mensaje de error en lugar de producir violaciones falsas.

Si `git worktree list` muestra `?? wt-205c-adopciones/` (directorio huerfano, no registrado),
elimínalo con `Remove-Item -Recurse -Force wt-205c-adopciones/`.

## Build de la imagen Docker (opcional en local)

El `Dockerfile` multi-stage compila el CSS y construye la wheel en un builder con Python + Node, y copia los artefactos a una imagen runtime solo con Python. Para validar el build localmente:

```bash
docker build -t apap-web:dev .
docker run --rm -p 8000:8000 apap-web:dev
# Health check desde fuera
curl http://127.0.0.1:8000/healthz
```

Si no tienes Docker, este paso no es necesario para desarrollar; la app funciona idéntico desde `make run`.

## Nota sobre ramas y despliegue

APAP_WEB usa `staging` como rama normal de integración. Las PRs de implementación apuntan a `staging`; `main` queda reservado para promoción/producción y solo dispara el job `deploy` cuando hay un push a `main` después de que CI pase.

La transición completa a canal UAT está capturada como **CD-03** en el change `ci-cd-foundation` (`openspec/changes/ci-cd-foundation/`). La implementación de CD-03 está **diferida** hasta que la protectora adopte el MVC en producción. Hasta que ese trigger se dispare:

- Las PRs normales apuntan a `staging`.
- `main` conserva el trigger de producción por Coolify y requiere evidencia del operador antes de cerrar el change.
- Todavía no hay puerta UAT implementada; la red de seguridad actual es la verja de calidad de CI (lint, unit, integration, build) y la revisión del operador.

La sección `openspec/changes/ci-cd-foundation/design.md § Future work` lista cada ticket diferido a la transición a staging (CD-03, CD-04, ENV-01, UAT-01..03, E2E-01..06, E2E-M1..M4, WORKER-01..04). Cuando el trigger se dispare, esos seeds se convierten en el siguiente change de SDD.

## Dónde mirar a continuación

- [`docs/setup.md`](setup.md) — setup por desarrollador y credenciales LocalBackend MCP.
- [`docs/architecture/architecture-local-backend-stack.md`](../architecture/architecture-local-backend-stack.md) — decisiones de stack, política de dependencias y políticas de CI/CD y testing.
- [`docs/roadmap.md`](../docs/roadmap.md) — hoja de ruta viva del proyecto.
- [`openspec/changes/ci-cd-foundation/`](../openspec/changes/ci-cd-foundation/) — change de SDD que planifica el pipeline de despliegue completo (PR 1 = superficie local; PR 2 = CI; PR 3 = CD).
- `pyproject.toml` — configuración canónica de pytest (deprecation strictness) y ruff (reglas de lint). La verja de calidad del doc de arquitectura está codificada aquí.
- `Makefile` — atajos de los comandos documentados arriba.
- `Dockerfile` — build multi-stage para producción (Fase 2+ lo usa vía Coolify).

## Core invariants

- **`make verify` refleja CI**: la lista de targets de `verify` está pineada por `tests/test_ci_workflow.py::test_make_verify_covers_every_ci_gate` al orden de los jobs de `ci.yml`. Añadir un gate a CI sin añadirlo a `verify` rompe el test; añadirlo a `verify` sin CI lo deja como coste local sin enforcement.
- **DeprecationWarning es error**: `pyproject.toml` promueve `DeprecationWarning` y `PendingDeprecationWarning` a error en pytest. Un test que importe APIs deprecadas falla en local y en CI; el filtro `StarletteDeprecationWarning` es la única excepción documentada.
- **Cobertura `--cov-fail-under=80`**: pytest corre con `--cov-fail-under=80`, replicando el suelo de `pyproject.toml`. Una suite que pasa local sin ese flag puede pasar en local y fallar en CI; correr siempre con el flag.
- **`ruff check .` cubre `E/F/W/I/UP/B`**: la selección vive en `pyproject.toml` § `[tool.ruff.lint]`. Cambiar reglas requiere PR que actualice también este doc.
- **`make mutation` es semanal y Linux-only**: cosmic-ray no entra en `verify` por coste y portabilidad. Solo se ejecuta en el job `mutation` con schedule semanal; los workstations no lo corren por defecto.
- **E2E solo con `APAP_OAUTH_CLIENT_ID`**: el job `ci / e2e` corre Playwright solo cuando las credenciales OAuth están configuradas como variable de entorno. Sin ellas el job se salta.
- **Edición editable requiere reinstalar tras mover worktree**: `python -m pip install -e ".[dev]"` deja una ruta absoluta en un `.pth`. Mover o recrear el worktree deja esa ruta apuntando al checkout anterior; hay que reinstalar.

## Contributor checklist

- [ ] Ejecutar `make verify` antes de abrir la PR; si algún target falla, arreglarlo antes de pedir review.
- [ ] Si añade un gate a `ci.yml`, añadir también el target correspondiente al `Makefile` y listarlo en `verify`, en el mismo orden.
- [ ] Si añade una dependencia de runtime, declararla en `pyproject.toml` § `dependencies` y verificar que `make verify` la resuelve en local.
- [ ] Si añade una dependencia de dev, declararla en `pyproject.toml` § `[project.optional-dependencies]` bajo `dev`; nunca instalar con `pip install <pkg>` ad-hoc.
- [ ] Si mueve o recrea el worktree, ejecutar `python -m pip install -e ".[dev]"` desde la raíz del nuevo checkout antes de correr pytest.
- [ ] Si la PR toca `ci.yml` o `Makefile`, abrir issue contra `tests/test_ci_workflow.py` para actualizar el ratchet en la misma sesión.
- [ ] Si la PR introduce un test que requiere PostgreSQL, usar `APAP_TEST_POSTGRES_DSN` y marcar el skip en local cuando la variable no esté definida.

## Navigation

Previous: [Setup local](setup.md) | Next: [Proceso por issue](proceso.md)
