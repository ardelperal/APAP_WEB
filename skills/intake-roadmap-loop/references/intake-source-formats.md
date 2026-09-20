# Fuentes de intake — cómo leer cada formato

Guía rápida para extraer items de cada tipo de fuente de intake. La skill `intake-roadmap-loop` exige clasificar cada item en los ejes `origen` y `validador` antes de empezar la especificación. Esta referencia cubre los formatos más comunes; las secciones siguientes son ejemplos, no una lista cerrada. Si tu fuente no encaja en ninguna (Jira, Linear, Notion, Confluence, spec en Markdown, etc.), aplicá los mismos principios: extraer items, clasificar `origen`/`validador`, dejar `source_ref` reproducible.

En proyectos con SDD (`openspec/changes/<change>/`), el `tasks.md` del change suele ser la fuente más fiel que el issue board; sincronizar antes de extraer.

## GitHub Issues

**Reconocimiento típico.** El intake viene del issue tracker del propio repositorio o de uno vinculado. cada issue es un item candidato. Una milestone, un label (`sprint: <cycle-id>`, `acta-calidad-2026-06-25`), un proyecto de GitHub Projects o una epic agrupa los issues del ciclo.

**Patrón de extracción.**

1. Listar issues con el filtro del ciclo (label, milestone, project board, fecha de apertura).
2. Cada issue es un item; el título es `title`, el cuerpo es la regla de negocio.
3. Clasificar `origen` por el autor del issue: cliente (rol externo) → `requested`; equipo → `derived`.
4. Clasificar `validador` por labels: `uat`, `acceptance` → `user`; `infra`, `tech-debt`, `refactor` → `dev`.
5. Si un issue referencia otro (linked, blockedBy), registrar la dependencia en el item del roadmap.

**Riesgos típicos.**

- Issues duplicados: consolidar a uno y referenciar el otro en `source_ref`.
- Issues viejos arrastrados de ciclos anteriores: filtrar por milestone o fecha.
- `openspec/changes/<change>/tasks.md` es la fuente más fiel que el issue board (los issues pueden quedar atrás). Sincronizar tasks.md ↔ issues antes de extraer.
- Issues cerrados sin commit ni PR: no son `requested` consumados; reclasificar a `derived` o exigir reabrir.

## Excel (xlsx, xls)

**Reconocimiento típico.** El cliente entrega un libro con una pestaña llamada "Tareas", "Requisitos", "Funcionalidades", "Puntos" o similar. Cada fila es un item.

**Columnas habituales.**

| Columna | Contenido esperado | Si falta |
|---|---|---|
| `ID` o `Nº` | Identificador numérico del item | Asignar al extraer, en el orden de la hoja |
| `Tarea` o `Descripción` | Texto libre con la regla de negocio | Bloquear. Sin descripción no se clasifica. |
| `Pantalla` o `Formulario` | Punto de la UI afectado | Marcar como `dev` si no aplica UI |
| `Notas` | Comentarios, excepciones, referencias | Conservar como contexto en el item del roadmap |

**Riesgos típicos.**

- Celdas fusionadas con texto que cruza varias filas: tratar la fila superior como dueña del contenido.
- Pestañas con numeración cruzada (item "1.2.3" implica dependencia de "1" y "2"): registrar la dependencia en el item hijo.
- Imágenes y capturas: extraer el texto del item, ignorar la imagen. Si la imagen es la única fuente, pedir transcripción al cliente.

## DOC / DOCX

**Reconocimiento típico.** Acta de reunión, memoria de kickoff, propuesta. Texto narrativo con bullets o un índice numerado.

**Patrón de extracción.**

1. Localizar las secciones tituladas "Tareas", "Puntos a tratar", "Acciones", "Requisitos" o equivalentes.
2. Tratar cada bullet o párrafo numerado como un item.
3. Si el DOC incluye anexos con tablas, procesarlos como si fueran Excel.

**Riesgos típicos.**

- Items implícitos en prosa ("también debería poder..."): marcarlos como `derived` con referencia al párrafo de origen.
- Numeración inconsistente entre secciones: reasignar IDs al extraer.

## Correo electrónico

**Reconocimiento típico.** Thread de reply-all con una lista adjunta o inline.

**Patrón de extracción.**

1. Identificar el correo que consolida la lista (suele ser el último del thread o el que tenga "FINAL", "vN" en el asunto).
2. Extraer los items numerados del cuerpo o del adjunto.
3. Si hay adjuntos xlsx/docx, tratarlos como su formato natural (ver arriba).

**Riesgos típicos.**

- Items debatidos y descartados en el thread: solo los que el cliente confirma al final del correo son `requested`. El resto va a `derived` con nota "descartado en thread del <fecha>".
- Decisiones tomadas en el thread (no items): bajar a ADR, no al roadmap de items.

## Transcripción de reunión

**Reconocimiento típico.** Notas de audio, transcripción automática o memoria escrita a mano.

**Patrón de extracción.**

1. Localizar las frases que indican compromiso: "queda pendiente...", "hay que...", "para la próxima...".
2. Cada compromiso hablado es un item candidato.
3. Confirmar con el cliente antes de tratarlo como `requested`. Sin confirmación, queda como `derived`.

**Riesgos típicos.**

- Frases ambiguas: "deberíamos ver cómo..." no es un item; es una señal para abrir una ADR sobre el "cómo".
- Múltiples participantes repitiendo el mismo punto: consolidar a un único item.

## Tabla resumen de extracción

Tras la lectura de cualquier fuente, el resultado mínimo es una tabla con esta forma:

| id | title | origen | validador | source_ref |
|---|---|---|---|---|
| 01 | <título corto del item> | `requested` \| `derived` | `user` \| `dev` | <ruta + sección + fila/parrafo del intake> |

`source_ref` debe ser reproducible: si la fuente cambia, otro lector llega al mismo item. Sin `source_ref`, el item no entra al roadmap vivo (HR-10).

## Anti-patternos de extracción

| Síntoma | Fix |
|---|---|
| Items inferidos del contexto sin frase literal del cliente | Marcarlos como `derived`. Si falta el nexo, no entran. |
| Mezcla de items `requested` con `derived` sin etiquetar | Bloquear; clasificar antes de seguir (HR-6). |
| `source_ref` apunta a una sección entera, no a un item | Apuntar a fila, párrafo o bullet. La referencia tiene que ser inequívoca. |
| Items duplicados entre la pestaña "Tareas" y el cuerpo del DOC | Consolidar a una única entrada; el `source_ref` cita ambas procedencias. |
| Items del intake que no son del cliente sino del equipo | Etiquetar `derived` y mover a la sección de trabajo interno, no al roadmap vivo de cliente. |