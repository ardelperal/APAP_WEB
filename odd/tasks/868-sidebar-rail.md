# #868 — Shell con riel izquierdo que sustituye la barra de navegación del header

## Goal

Sustituir la barra de navegación horizontal del `<header>` por un **riel izquierdo** que exprese la jerarquía del dominio APAP. Las nueve entradas actuales se agrupan en cinco de primer nivel, con control de despliegue **sólo** donde hay hijos reales (`Entradas`, `Acogida`).

Issue: `#868` (epic `#817`). Supersede a `#809`, cerrada como `not_planned`.

## Decisión de diseño (cerrada)

Aprobada por el usuario. El mockup `v4` es la referencia visual:

| Aspecto | Decisión |
|---|---|
| Contenedor | Riel izquierdo sobre `--color-surface`, borde derecho |
| Marca | Mark + `wordmark` + subtítulo **apilado** («Panel de gestión») |
| Entradas de primer nivel | `Animales`, `Entradas`, `Acogida`, `Voluntarios`, `Configuración` |
| Control de despliegue | Sólo en `Entradas` y `Acogida` |
| Estado activo | Píldora rellena con `--color-primary-dark`. **Cero tokens nuevos** |
| Profundidad del activo | Mismo tratamiento en primer nivel y anidado |
| Grupo con el activo | Se renderiza desplegado (el activo nunca queda oculto) |
| Pie del riel | «Ver la web» → `https://www.apap-alcala.org/` |

**Descartado explícitamente** (estaba en la referencia, no entra): búsqueda global (no hay endpoint), campana de notificaciones y botón de ayuda (sin funcionalidad), token navy (es la identidad de la referencia, no la de APAP_WEB).

## Criterios de aceptación

Los once criterios viven en el cuerpo de `#868`. Resumen operativo:

1. Un solo riel; ninguna barra horizontal en el `<header>`.
2. ≤ 5 entradas de primer nivel.
3. Control de despliegue sólo en entradas con hijos.
4. Exactamente un `aria-current="page"`, siempre en una hoja.
5. Activo visualmente idéntico a cualquier profundidad.
6. El grupo con el activo arranca desplegado.
7. Despliegue operable sólo con teclado; `aria-expanded` sincronizado.
8. El enlace de salto sigue siendo el primer enfocable y apunta a `<main>`.
9. La tabulación no recorre destinos dos veces.
10. «Ver la web» con `rel="noopener"`.
11. Ningún token nuevo.

## Troceado en PRs encadenados

**Ajuste sobre lo escrito en `#868`.** La issue proponía (1) layout, (2) grupos, (3) a11y+e2e. Se cambia el orden para que **cada PR quede verde**: si el PR 1 cambia el DOM, deja los cuatro archivos e2e en rojo hasta el PR 3, y el verde de los PRs intermedios sería engañoso.

| PR | Alcance | Deja `main` |
|---|---|---|
| **1** ✅ | `app/core/nav.py` — modelo de agrupación (`NavGroup`, `NAV_ENTRIES`, `NAV_ITEMS` derivado plano) + unit tests. **Sin tocar templates.** | 🟢 verde — PR **#869** abierto |
| **2** | Riel en `base.html` (**desktop**) + `nav_entries` en el context processor + estilos de componente + bundle regenerado + e2e que asumen el header. | 🟢 verde |
| **3** | Riel fuera de lienzo en `base_mobile.html` (**móvil**, UA-based) + adaptación del controlador del burger (`#820`) + re-verificación a11y de la Fase A. | 🟢 verde |

**Por qué el troceado cambió de nuevo.** `base.html` y `base_mobile.html` son **dos plantillas base independientes** (cada una con su propio `<!doctype html>`), y `app/core/middleware.py` elige una u otra por **user-agent**. No es una que extiende a la otra, así que el layout de escritorio y el de móvil se pueden entregar por separado sin dejar un estado intermedio incoherente: ningún usuario ve los dos. Y los e2e de nav no fijan user-agent, así que ejercitan `base.html` — de ahí que su actualización viaje con el PR 2.

## Invariante del PR 1

`NAV_ITEMS` **se mantiene plano y completo**: los mismos 9 `href`, en el mismo orden. Se deriva de `NAV_ENTRIES`. Esto no es cosmético — es lo que mantiene sin cambios:

- `resolve_active_nav_href` y `nav_items_for_role`.
- `tests/test_nav_labels_sync.py` (exige los 9 href en `NAV_ITEMS` y en el mapa e2e).
- La paridad de sprites de `tests/test_nav.py`.
- La allowlist de atributos URL de `tests/test_xss_audit.py`, que está keyed por expresión exacta (`item.href`, `item.icon`, `item.title`).

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` — exit 0.
- `python scripts/check_rules.py .` — exit 0.
- `python -m mypy` — sin errores.
- `pytest tests/test_nav.py tests/test_nav_labels_sync.py tests/test_xss_audit.py tests/test_pages.py -q` — verde.
- `pytest tests/e2e/test_nav_*.py -q` bajo chromium (auto-skip si no hay server) — verde a partir del PR 2.
- Issue-spec del PR contra `#868` — **requiere `status:approved` en #868**, hoy pendiente.
- Presupuesto ≤ 400 líneas por PR. Si un PR lo excede, se parte.

## Legacy fidelity (P1)

N/A — sólo toca el shell web (templates, helper de nav, CSS, JS de burger). Sin backend y sin puente legacy.

## Riesgos

1. **Presupuesto.** El PR 2 concentra el riesgo: toca dos templates, CSS, el bundle generado y cuatro archivos e2e. Verificar el conteo antes de abrir.
2. **Línea base a11y.** `#812` y `#813` se validaron con el header arriba. El cambio de orden de DOM puede romper el destino del enlace de salto y el `aria-labelledby`; se reverifica en el PR 3.
3. **Bundle CSS generado.** `app/static/css/output.css` se recompila con `make css`. Un cambio de tokens o clases puede inflar el diff; revisar que no arrastre ruido.
4. **Contratos e2e engañosos.** Cuatro archivos fijan hoy hijos directos de `#nav-main`. Actualizarlos sin reexpresar el contrato con claridad puede convertir un rojo real en un verde falso.
5. **Controlador del burger.** `app/static/js/nav-burger.js` asume la navegación dentro del `<header>`; la trampa de foco y el cierre por cambio de ruta deben adaptarse al riel.

## Decisiones de implementación del PR 2 (fijadas)

- **El cálculo de apertura va en Python, no en la plantilla.** El context processor expone `nav_entries` (el registro agrupado, sin filtrar por rol, exactamente como hoy expone `nav_items`); la plantilla filtra por rol inline como ya hace, y marca `open` el grupo que contiene `nav_active_href`.
- **Se preservan los dos bloques de `base.html`**: `{% block title %}` y `{% block content %}`. Las páginas extienden con `{% extends base_template %}`.
- **Labels largos**: el v4 aprobado usa «Listado de entradas», «Entrada en lote», «Casas de acogida», «Configuración». Adoptarlos obliga a resincronizar `tests/test_nav_labels_sync.py`, el mapa `EXPECTED_ACTIVE_LABEL` del e2e y a reexpresar `tests/e2e/test_nav_no_multiline.py`, cuyo motivo de ser (el ancho de la barra horizontal de #806) desaparece en un riel. No es un «arreglo de tests»: es un contrato que cambia de fundamento.
- **`output.css` es un artefacto generado** (una sola línea minificada, ~30 KB). El Dockerfile lo recompila; ningún check lo vigila. Se regenera para no romper el desarrollo local, y el cuerpo del PR debe avisar al revisor de que no lo revise a él sino a `tailwindcss/styles/app.css`.

## Estado de tareas

| # | Tarea | Estado |
|---|---|---|
| 1 | Worktree `868-sidebar-rail` desde `origin/main` + este documento | ✅ |
| 2 | PR 1 — `NavGroup` + `NAV_ENTRIES` + `NAV_ITEMS` derivado + unit tests | ✅ PR #869 |
| 3 | PR 2 — riel desktop en `base.html` + CSS + e2e | en curso |
| 4 | PR 3 — riel móvil en `base_mobile.html` + burger + a11y Fase A | pendiente |
| 5 | Agregar el mockup v4 al repo como artefacto de diseño | pendiente |
| 6 | `status:approved` en `#868` | ✅ aplicada; `issue-spec` en verde |

## Decision log

- **2026-09-22** — El usuario aprueba el mockup `v4`. El estado activo usa `primary-dark`; se descarta introducir navy.
- **2026-09-22** — `#809` se cierra como `not_planned`: su objetivo se cumple dentro del riel, y un desplegable en el header sería trabajo que el riel borra.
- **2026-09-22** — Se reordena el troceado para que cada PR quede verde (el modelo de nav va primero, sin tocar el DOM).
