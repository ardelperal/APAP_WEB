# D-45 — Plantillas de contrato versionadas como ficheros del repo

## Decision

Las ocho plantillas de contrato de DOC-01 (#56 / #1109) viven como
ficheros versionados en el propio repositorio, bajo
`app/modules/contratos/templates/<slug>.md`, con el formato de
texto plano y placeholders (`{{ variable }}` y `{% if %}`) que el
motor de la slice ya entiende. El acceso al cuerpo de cada
plantilla se realiza a través de un nuevo puerto hexagonal
(`ContratosPlantillaPort`) cuya única implementación
(`FilesystemContratosPlantillas`, en
`adapters/filesystem/`) carga el `.md` desde el sistema de
ficheros, valida la gramática del motor en la primera lectura y
almacena en caché por tipo.

El portado verbatim de los textos legacy (procedentes de la familia
`RellenarContrato*` del Access) no estaba disponible en este
entorno: ni los `.docx` originales ni el binario `.accdb` eran
accesibles. Para que la implementación no inventase cláusulas
legales, los ocho ficheros se crean con la línea de cabecera
`<!-- CONTRATO-PLANTILLA: TEXTO PENDIENTE DE PORTAR DEL LEGACY
(issue #1109) -->`, seguida de un esqueleto mínimo de placeholders
dotted-path (`animal.nombre`, `persona.dni`, etc.) y un bloque
`{% if %}` / `{% endif %}` balanceado. La presencia de ese
marcador está pineada por un test de parametrización sobre los
ocho `TipoContrato`, de forma que un portado futuro que retire el
marcador requiere un cambio de test explícito y trazable. Las
cláusulas reales llegan en una sesión posterior con dysflow sobre
el binario Access o con los `.docx` a mano; ese portado cerrará el
criterio de aceptación 2 de #1109, no bloquea los slices 1-3.

Este ADR codifica la decisión tomada el 2026-10-02 al abrir
#1109 (única feature de producto `status:approved`) y se
registra en `decisiones-proyecto.md` como D-45.

## Quick path

- Plantilla de contrato → fichero versionado en el repo, formato
  texto plano con placeholders.
- Puerto `ContratosPlantillaPort` (Protocol runtime_checkable) →
  implementación `FilesystemContratosPlantillas` bajo
  `adapters/filesystem/`.
- Texto legacy ausente → marcador `TEXTO PENDIENTE DE PORTAR DEL
  LEGACY` pineado por test, portado en sesión futura.
- Tipo desconocido o `.md` ausente →
  `PlantillaNoDisponibleError` (subclase de `ValueError`,
  simétrica con `PlantillaInvalidaError`).
- Plantilla con gramática rota → `PlantillaInvalidaError` en la
  primera carga (CI fail-loud).

## Problem statement

El motor de plantillas de la slice `contratos` (PR 1 de #56,
commit `28614e1`) está completo y verde: tokeniza, valida
gramática, evalúa condicionales y sustituye placeholders. Pero
las cláusulas reales — los textos legales que el legacy produce
con `RellenarContratoEntrada`, `RellenarContratoAcogida`,
`RellenarContratoAdopcion`, etc. — no tienen todavía una fuente
de verdad en el sistema nuevo. Sin D-45, el siguiente PR
(almacenamiento + ruta HTTP) emitiría PDFs a partir de textos
que aún no existen, o inventaría cláusulas en prosa, ninguna de
las dos opciones aceptable para un documento firmable.

El problema tiene tres aristas:

1. **Origen del texto.** Los textos viven hoy en `.docx` del
   Access legacy, en la máquina del operador, sin acceso desde
   este entorno.
2. **Forma del texto.** El motor de la slice solo entiende
   `{{ variable }}` y `{% if %}` — escapa HTML, no renderiza
   Markdown. Cualquier cosa más rica (Markdown, HTML, Jinja
   completo) o se renderiza como literal, o exige reescribir el
   motor, o ambos.
3. **Trazabilidad del portado.** El criterio de aceptación 2 de
   #1109 exige que el sistema nuevo emita contratos con el mismo
   texto que el legacy. Un portado silencioso (clonar a ojo,
   reescribir cláusulas) sería indistinguible del trabajo
   legítimo; el marcador pineado por test hace el portado
   verificable.

## Evidence and scope

- PR 1 de DOC-01 (`28614e1`) — motor de plantillas puro con 35
  tests verdes; pin arquitectónico en
  `tests/test_slice_contratos_architecture.py` confirma
  transport-free en `domain/`, `ports/` y `application/`.
- `app/modules/contratos/domain/plantilla.py` — modelo de
  `Plantilla(tipo, cuerpo)`; `validar_gramatica` rechaza
  bloques `{% if %}` desbalanceados y operandos izquierdos no
  placeholders.
- `app/modules/contratos/application/render_contrato.py` y
  `render_to_pdf.py` — la salida del motor es texto plano
  envuelto en HTML escapado, que el adapter de reportlab
  (`contratos_local_backend_pdf.py`) convierte a PDF; nada en
  este path renderiza Markdown.
- `docs/legacy-signed-contract-flow.md` — la familia
  `RellenarContrato*` del legacy produce ocho tipos de contrato
  (Entrada, Acogida, Acogida Judicial, Adopcion, PreAdopcion,
  Cesion, Reserva, Entrega) con mail-merge Word sobre la misma
  sintaxis `{{ }}` / `{% if %}` que el motor de la slice ya
  entiende. Los textos concretos de cada cláusula no son
  accesibles en este entorno (los `.docx` están en la máquina
  del operador; el `.accdb` no es parseable con `access-parser`
  en este checkout).
- `odd/tasks/doc-01-usable-contratos.md` — el plan de chained PR
  en tres tramos (port + adapter, composition root + ruta, E2E)
  con el portado verbatim de los textos legacy marcado como
  pendiente externo.
- Átomos de verificación: parametrización que carga los ocho
  `TipoContrato` a través del adapter; pin del marcador
  pendiente-legacy en cada cuerpo; pin de
  `validar_gramatica` sobre cada cuerpo; pin de
  `PlantillaNoDisponibleError` para tipo desconocido y para
  `.md` ausente; pin de `PlantillaInvalidaError` para gramática
  rota; pin de conformidad `runtime_checkable` entre el adapter
  y el Protocol.

## Options considered

### Opción A — Ficheros versionados en el repo + marcador pendiente (aceptada)

**A favor**: las plantillas siguen el flujo estándar de revisión
y CI del proyecto (PR + check_rules + check_layers + tests);
cero infraestructura nueva (no S3, no BD, no servicio externo);
el marcador pineado por test hace el portado futuro trazable; el
formato texto+`{{ }}`+`{% if %}` lo entiende el motor existente
sin reescritura; la separación puerto/adapter mantiene la slice
hexagonal y permite portar a otra fuente (S3, gestor documental)
en el futuro sin tocar `application/` ni `domain/`.

**En contra**: el contenido inicial es un esqueleto — los
contratos generados ahora mismo no son legalmente válidos (el
portado de los textos legacy queda como follow-up); el
mantenedor debe vigilar que el marcador se retire cuando los
textos lleguen (riesgo mitigado por el pin de test).

### Opción B — Clonar los `.docx` legacy a mano sin marcador (rechazada)

**A favor**: menos ceremonia en la primera entrega; el sistema
emite contratos "más completos" desde el día uno.

**En contra**: la clonación no es verificable — un revisor no
puede distinguir entre "portado verbatim" y "cláusulas
reinventadas"; un cambio accidental en una coma legal pasa
revisión sin que CI lo detecte; viola la regla "no se inventan
cláusulas" de la propia operator decision de #1109.

### Opción C — Cargar los textos desde una fuente externa (S3 / gestor documental) (rechazada para slice 1)

**A favor**: desacopla el contenido textual del código; permite
que el operador edite sin PR.

**En contra**: introduce una dependencia operativa (bucket,
credenciales, versionado) que no está justificada para los
primeros tres slices de #1109; los textos legacy aún no están
portados, así que la fuente externa estaría vacía igualmente;
el puerto queda abierto para una segunda implementación
(`adapters/object_storage/contratos_plantillas.py`) que cubra
esta opción más adelante, pero no es la decisión de slice 1.

### Opción D — Renderizar Markdown / HTML completo (rechazada)

**A favor**: formato más rico (negrita, listas, tablas) en los
PDFs generados.

**En contra**: el motor actual escapa HTML y no interpreta
Markdown; un cambio así es una reescritura del motor
(`render_contrato`, `render_tokenize`, `validar_gramatica`),
fuera del scope del slice 1; los textos legacy son texto plano
con `{{ }}` — añadir Markdown ahora no aporta nada hasta que
los textos estén portados.

## Goals

- Ocho `TipoContrato` con cuerpo de plantilla versionado,
  revisable y pineado por test.
- Acceso al cuerpo a través de un puerto hexagonal
  (`Protocol` runtime_checkable), con vocabulario de dominio
  (`obtener_plantilla`), sin transporte importado en
  `ports/`.
- Carga con validación de gramática fail-loud (una plantilla
  rota en el repo rompe CI, no la primera request de un
  operador en producción).
- Marcador `TEXTO PENDIENTE DE PORTAR DEL LEGACY` presente en
  los ocho ficheros, pineado por parametrización sobre los
  ocho `TipoContrato`.
- Ausencia de plantilla (tipo desconocido o `.md` borrado)
  traducida a `PlantillaNoDisponibleError`, subclase de
  `ValueError` (simétrica con `PlantillaInvalidaError` y con
  la convención de la slice).
- Cumplimiento de las HR de `apap-architecture` (Protocol en
  `ports/`, sin imports de transporte en `ports/`, presupuestos
  de 700/50 líneas sin crecimiento de `BASELINE`, pin test
  arquitectónico sigue verde).

## Non-goals

- Portar el texto verbatim de las ocho cláusulas legacy (lo
  bloquea la disponibilidad de los `.docx` y del `.accdb`; es
  un pendiente externo, no un objetivo de este ADR).
- Reemplazar el motor de plantillas por un renderizador de
  Markdown, HTML o Jinja completo.
- Cargar las plantillas desde S3, una base de datos o un
  servicio externo en este slice (queda como puerto abierto
  para una segunda implementación futura).
- Internacionalizar los nombres de campo en el diccionario de
  variables; el esqueleto usa los nombres de la familia legacy
  `RellenarContrato*` (`animal.nombre`, `animal.chip`,
  `persona.nombre`, `persona.apellidos`, `solicitud.fecha`).
- Cerrar el criterio de aceptación 2 de #1109 (que exige
  contratos con el mismo texto que el legacy). Eso depende del
  portado externo; este ADR solo establece la fuente y la
  trazabilidad para que el portado sea posible y verificable.

## Non-negotiable invariants

- Las plantillas viven en el repo, no en una base de datos ni
  en un servicio externo. Cualquier cambio en una cláusula
  pasa por PR y CI.
- El marcador `TEXTO PENDIENTE DE PORTAR DEL LEGACY` permanece
  hasta que el portado retire el esqueleto; un PR que retire el
  marcador sin haber portado el texto real falla el pin test
  de parametrización.
- El puerto es `Protocol` runtime_checkable; el adapter bajo
  `adapters/filesystem/` es la única implementación en este
  slice. La conformidad se pinea por `isinstance` en el
  adapter test.
- `domain/plantilla.py` y `ports/contratos_plantilla_port.py`
  no importan `pathlib`, `os`, `fastapi`, `app.core.local_backend`
  ni nada de transporte; el pin test
  `tests/test_slice_contratos_architecture.py` lo enforza.
- `PlantillaNoDisponibleError` es subclase de `ValueError`,
  vive en `domain/plantilla.py` y la emite el adapter cuando
  el tipo es desconocido o el `.md` está ausente. La CP-2 use
  case lo traduce a 404 / 422 en la frontera HTTP; el adapter
  no la convierte en HTTPException.
- Una plantilla con gramática rota falla
  `validar_gramatica` en la primera carga y el adapter
  propaga `PlantillaInvalidaError`; la use case NO traduce
  esta excepción (es un error de artefacto, no de entrada).

## Consequences

**Cambia**: la slice `contratos` pasa de "motor puro sin fuente
de plantillas" a "motor + puerto + adapter de ficheros con
ocho plantillas placeholder". Los slices 2 y 3 (#1109)
componen el adapter en el composition root y llaman a
`obtener_plantilla` desde el use case, sin tocar
`domain/`.

**Cambia**: el pin test arquitectónico
(`tests/test_slice_contratos_architecture.py`) sigue
verificando que `ports/` y `domain/` no importan transporte;
el nuevo puerto se ajusta a la regla sin cambios.

**Cambia**: el índice de ADRs (`decisiones-proyecto.md`) gana
una fila D-45 bajo la sección "Arquitectura y stack", con su
detalle en este archivo.

**No cambia**: el motor de plantillas (tokenización,
validación, render) ni sus tests existentes. La superficie
pública de la slice en `application/` sigue siendo
`render_contrato` y `render_to_pdf`; el puerto se consume
desde un nuevo use case del slice 2.

**No cambia**: el criterio de aceptación 2 de #1109 — sigue
pendiente del portado externo; este ADR no lo cierra, solo
establece las condiciones para que el portado sea trazable.

**Pendiente operativo**: el portado verbatim de las ocho
cláusulas se hace en una sesión futura con dysflow sobre el
binario Access o con los `.docx` a mano. Cuando se retire el
marcador, este ADR se complementa con un registro de portado
(quién, cuándo, desde qué artefacto) en una decisión sucesora
o en una entrada del CHANGELOG.

## When this changes

- Cuando los ocho textos legacy estén portados, el marcador se
  retira y se actualiza el pin test para que la parametrización
  verifique la presencia de las cláusulas reales (no del
  marcador). Esta ADR se marca como **SUPERSEDED por D-46**
  (decisión sucesora, no registrada todavía) si la retirada
  del marcador exige una decisión arquitectónica propia; en
  caso contrario, basta con un PR de portado + actualización
  del test.
- Cuando la fuente de las plantillas cambie (S3, base de datos,
  gestor documental), se añade una segunda implementación del
  puerto bajo `adapters/<nueva_fuente>/` y este ADR se
  complementa con un registro de la decisión de portabilidad
  (qué fuente, por qué, qué cambia en el composition root).
- Si el motor de la slice se reescribe para soportar Markdown
  o un mini-lenguaje más rico, el formato `.md` actual deja
  de ser el contrato; este ADR se marca como **SUPERSEDED por
  D-XX** y se documenta la nueva convención de sufijos y
  parsers.
