# Roadmap del ciclo `<cycle-id>`

> **Proposito.** Mapa al estado del ciclo `<cycle-id>`, no un duplicado. El estado vive en la observación de `topic_key` en engram, en los archivos de `architecture/`, en el issue tracker y en el manifiesto de tests. Este documento es el punto de entrada para quien vuelve de una pausa larga: si busca el "qué" y el "cómo está", siga los enlaces.

## Identidad del ciclo

| Campo | Valor |
|---|---|
| `cycle-id` | `<cycle-id>` |
| Compuerta actual | `intake` \| `mid_sprint` \| `uat_handoff` \| `uat_signed_off` \| `archived` |
| Estado | 🟢 verde \| 🟡 ámbar \| 🔴 rojo \| 🟣 violet (size:exception) |
| Owner | `<nombre>` |
| Topic key engram | `<cycle-id>/<gate>` |
| Fuente de intake | `<ruta o descripción de la fuente de intake>` |
| Fecha de apertura | `<YYYY-MM-DD>` |
| Próximo gate | `<YYYY-MM-DD>` |

## Resumen ejecutivo

<Una o dos frases: qué se está entregando y por qué importa ahora.>

## Donde está el detalle

Antes de empezar a leer este documento entero, sepa dónde vive el detalle real:

- **Decisiones arquitectónicas** — `docs/<project>/architecture/<topic-slug>.md`. Un archivo por decisión irreversible; status `proposed` / `accepted` / `superseded`.
- **Issue tracker** — `<url del repositorio de issues>`. Cada item del intake tiene su issue; este roadmap los referencia, no los enumera.
- **Manifiesto de tests** — `<ruta>`. La salud del código no vive en este documento.
- **Snapshots puntuales** — `archive/<cycle-id>-<YYYY-MM-DD>.<formato-de-snapshot>`. Generadas con la skill de snapshot del proyecto; son derivadas, no autoritativas.
- **Memoria persistente** — `mem_search query="topic_key=<cycle-id>"` devuelve la observación de intake y las sucesivas.

## Items del ciclo

<Una fila por item. La tabla NO duplica el detalle del issue; lo referencia.>

| ID | Título | Origen | Validador | Estado | Motivo | Issue / PR | Decisión | Último movimiento |
|---|---|---|---|---|---|---|---|---|
| `<id>` | <título corto> | `requested` \| `derived` | `user` \| `dev` | 🟢🟡🔴 | <una línea> | `<#NNN>` | `<topic-slug>.md` | `<YYYY-MM-DD>` |

## Decisiones arquitectónicas abiertas

<Una línea por decisión pendiente o recién tomada. El detalle vive en `architecture/<topic-slug>.md`.>

- `<topic-slug>` — `proposed` desde `<YYYY-MM-DD>` — vínculo: `architecture/<topic-slug>.md`.

## Decisiones arquitectónicas aceptadas

- `<topic-slug>` — `accepted` — vínculo: `architecture/<topic-slug>.md`.

## Próximos pasos

<Numerados, accionables, sin fechas relativas vagas.>

1. <Acción concreta 1>.
2. <Acción concreta 2>.

## Riesgos abiertos

- <Riesgo 1>.
- <Riesgo 2>.

## Cómo leer este documento al volver de una pausa

1. Lee el bloque "Identidad del ciclo" y "Resumen ejecutivo".
2. Si la pregunta es "qué pasa con X", salta al item en la tabla y sigue el link al issue.
3. Si la pregunta es "por qué decidimos Y", salta a `architecture/<topic-slug>.md` desde la fila correspondiente.
4. Si la pregunta es "dónde está el snapshot para el jefe", sigue el path en `archive/`.
5. Si nada de esto contesta, ejecuta `mem_search query="topic_key=<cycle-id>"` y revisa la observación pineada.

## Convenciones del archivo

- Este archivo es Markdown. Las ediciones se hacen con la misma disciplina que el resto de artefactos versionados: commit con mensaje, PR contra la rama de trabajo.
- No editar este archivo para reflejar cambios en items: regenerar desde la fuente (issue tracker + engram + architecture/) y dejar que el lector siga los links.
- Cuando el ciclo se archive, este archivo se mueve a `archive/<cycle-id>-final-<YYYY-MM-DD>.md` y se abre uno nuevo en `docs/<project>/roadmap.md`.