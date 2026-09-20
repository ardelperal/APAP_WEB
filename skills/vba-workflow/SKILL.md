---
name: vba-workflow
description: Trigger: empezando trabajo vba, modificando codigo vba, escribiendo sql contra backend access, tocando .accdb, abriendo access repo, dysflow import modulos, dysflow export modulos, antes de pasar tests access, formularios desacoplados, generacion de ERD, sincronizando source vba. Cargue esta skill cuando una IA trabaja en un proyecto VBA / Access (.accdb/.bas/.cls/.form.txt) y necesita respetar el flujo antes de modificar el binario o de generar fixtures sin ERD. Forma parte del arnes DysTelefonica para VBA, no es para diagnostico read-only (use vba-binary-drift, vba-event-tracer o vba-sql-impact para esos casos).
license: Apache-2.0
metadata:
  author: ardelperal
  version: 0.3.0
  last_verified: 2026-09-18
  scope: ['vba', 'runtime']
  auto_invoke: ['starting vba work', 'modifying vba code', 'running access tests', 'wrote sql against backend', 'opened access repo', 'modifying .accdb', 'before passing tests in vba', 'syncing dysflow source', 'vba project workflow', 'generando OPENSPEC vba', 'form desacoplado', 'agregados en sql access', 'identidad lanzadera', 'importar modulos dysflow', 'exportar modulos dysflow', 'form code change', 'form ui change', 'edito codigo .cls', 'edito ui .form.txt']
  tiers: ['vba', 'runtime']
---

> **Dependencias externas**: esta skill asume que el consumer tiene
> `dysflow` (sync source/binario, runner de tests), `codegraph` (code
> intelligence via MCP) y `gentle-ai` (paquete de skills upstream de
> Alan). Personal-skills no las instala; cada uno lo mantiene su propio
> equipo. Si falta una de estas, el flujo documentado aqui no opera.
# VBA Workflow — gates antes de tocar

Fricciones que se repiten en proyectos VBA / Access y la manera de
evitarlas. Esta skill NO es diagnostico: es flujo de trabajo.
Si la peticion es read-only (auditoria, tracing, mapeo de blast
radius), use las skills `vba-binary-drift`, `vba-event-tracer`,
`vba-handler-backtrace` o `vba-sql-impact`; esta skill no las
reemplaza.

## Activation contract

Cargue esta skill cuando se den al menos dos de:

- El repo en uso tiene `*.accdb`, `*.bas`, `*.cls`, `*.form.txt`,
  `.dysflow/` o directorios `www/` legacy.
- La tarea pendiente es editar, generar o migrar codigo VBA o SQL
  contra el backend.
- La peticion del usuario involucra modificar el binario o
  ejecutar tests.

No carguela para: solo leer codigo, generar docs sin tocar el binario,
o responder preguntas historicas. Para esos casos use `dysflow-usage`
como punto de entrada general.

## Gate 1 — Antes de tocar nada

Antes de modificar:

- **Confirme que existe ERD del backend.** Conforme a la
  convencion de documentacion (alan-style), el ERD vive en
  `OPENSPEC/<proyecto>/ERD.md` del path del proyecto. Algunas
  variantes lo externalizan a `C:\00repos\documentacion\OPENSPEC\
  <proyecto>\`. Confirmelo contra la seccion de documentacion del
  `AGENTS.md` del proyecto. Si no existe, generelo con dysflow y
  archivelo antes de tocar SQL. No improvise fixtures contra tablas
  sin haber leido primero el ERD.
- **Revise el repo con codegraph** (herramienta nativa gentle-ai
  expuesta via MCP; carguela via `codegraph_explore`). Si
  `.codegraph/` no existe, inicialice con
  `gentle-ai codegraph init <project-root>`. No use `grep`
  directo: gasta muchos tokens y se pierde el contexto
  estructural.
- **Identifique las tablas del backend** que va a tocar. Tablas del
  back viven en el servidor; el front no las vincula, salvo la
  tabla de configuracion.
- **Cargue `dysflow-usage` y `dysflow-arnes`** antes de la primera
  invocacion de cualquier tool dysflow. El arnes y el usage son
  fuente canonica de nombres, flags, codigos de error y patrones
  de invocacion.

## Gate 2 — Al modificar codigo o SQL

- **Edite solo source.** Los `.bas` / `.cls` / `.form.txt` son la
  verdad commiteada; cualquier cambio de comportamiento pasa por
  ahi.
- **Code en `.cls`, UI en `.form.txt`.** Si cambia codigo VBA
  de un form, edite el `.cls`. Si cambia layout, controles,
  formato o cualquier UI, edite el `.form.txt`. Mezclar
  produce perdida: `dysflow.import_modules` toma la UI del
  `.form.txt` y sobreescribe la parte de codigo del binario
  con lo que diga el `.cls`. Despues de editar ambos,
  importelos con `dysflow.import_modules { moduleNames: [<el
  .cls>, <el .form.txt>], apply: true }`. Nunca omita el
  `.cls` cuando toca codigo ni el `.form.txt` cuando toca UI.
- **Wiring de eventos: manual.** Al agregar un procedimiento
  nuevo `Private Sub ControlName_<Event>` al `.cls`,
  edite el `.form.txt` y anada la linea
  `ControlName.<Event> = "[Event Procedure]"` en la seccion
  del control. Dysflow lee los bindings existentes pero no
  los crea por usted (confirmado en
  `form-ir-service.ts`: `collectFormEvents`,
  `hasEventProcedureBinding`, `hasEventProcedureBindingInTree`).
  Renombrar un control con eventos asociados se rechaza por
  convencion. Tras cualquier `Private Sub NuevoMetodo()` para un
  control existente, verifique la entrada correspondiente en
  el `.form.txt` antes de importar. Si falta el binding, el
  procedimiento queda en el binario pero no se dispara.
- **Importe solo los modulos cambiados al binario con dysflow.**
  Comando:

  ```
  dysflow.import_modules {
    projectRoot: <cwd>,
    moduleNames: [<solo los que efectivamente cambiaron>],
    apply: true
  }
  ```

  Pasar solo los modulos que cambio. Una pasada de `dysflow.sync`
  contra un `.accdb` antiguo arrastra cambios que no le pertenecen
  al PR actual y produce divergencia silenciosa.
- **Si edito un form a mano en el .accdb** (porque es mas rapido
  para un cambio puntual), sincronice source usando:

  ```
  dysflow.export_modules {
    projectRoot: <cwd>,
    moduleNames: [<el form modificado>],
    exportPath: <ruta temporal, fuera del repo>,
    mutateBinary: false
  }
  ```

  Esto extrae el modulo desde el binario al source sin re-tocar
  el binario. Confirme que la copia exportada coincide con lo
  que efectivamente hizo a mano antes de subirla al repo.
- **Antes de pasar tests, corra `dysflow.drift`**. La divergencia
  binario <-> source debe ser 0. Si drift > 0, hay cambios sin
  documentar; revise y vuelva a exportar / importar antes de
  continuar.
- **Gate humano de compilacion.** Si Access reporta errores de
  compilacion (panel VBEditor o `dysflow.verify_code`), el codigo
  todavia no corre. No avance a tests hasta resolver.
- **Antes de invocar una funcion o metodo del codigo ajeno**,
  confirme la firma con codegraph. No invoque por intuicion;
  cargue el SKILL de la concern con la firma canonica.
- **Si toca SQL**, cargue `vba-query-decoupler` antes de escribir
  strings inline. SQL contra el back no se beneficia de
  `CurrentDb`, ni de funciones agregadas: cargue la query como
  constante `qry_<purpose>` o deleguela al repository.
- **Forms son desacoplados.** No existe un form con origen de
  datos (table) ni combo / listbox con rowSource sobre una tabla.
  Cualquier dato del form pasa por repository / controller.
  `DoCmd.OpenQuery` y `DoCmd.RunSQL` quedan prohibidos dentro de
  modulos de form.

## Gate 3 — Al correr tests

Antes de declarar verde:

- **Contract del runner JSON** (ver `access-vba-tdd-fundamentos`
  HR-1): `Public Function Test_X() As String` con retorno JSON
  canonico `{ok, value, payload, error, logs}`. Tests que
  devuelven `Sub`, `Debug.Print` o `MsgBox` no son tests validos.
- **Cardinalidad** (`countBefore` / `countAfter`) en cualquier
  mutacion. Sin cardinalidad no hay evidencia del cambio.
- **Si el .accdb queda en estado inconsistente**, recuperelo del
  backup pre-modificacion (`Database.SaveCopyToPath` o copia
  local). No modifique el binario para hacer verde un test.
- **Identidad via lanzadera.** El usuario final pasa por una
  aplicacion lanzadera que inyecta el correo electronico al abrir
  Access. Ese correo es la identidad canonica de la sesion. No
  use `Environ("Username")`, no use login de Windows, no agregue
  pantalla de login: el repositorio consume una identidad ya
  validada.
- **Si la accion genera un error no controlado** (no input del
  usuario), el patron es:

  ```
  errores:
      DoCmd.Hourglass False
      If Err.Number <> 1000 Then
          m_Error = "Al <nombre_subs> se ha producido el error n: "
                  & Err.Number & vbNewLine & "Detalle: " & Err.Description
          If <existe CorreoAlAdministrador> Then CorreoAlAdministrador m_Error
          pregunta = MsgBox(m_Error, vbCritical, "Error")
      Else
          pregunta = MsgBox(m_Error, vbExclamation, "Advertencia")
      End If
  ```

  `<existe CorreoAlAdministrador>`: presente en todos los repos
  legacy del equipo menos CONDOR. La sub que invoca esta
  plantilla es siempre la "sub final" (click de menu, handler
  de boton). Cualquier sub intermedia propaga el error hacia
  arriba mediante un parametro `Optional ByRef p_Error As String`
  al final de su firma; ese parametro recibe la `m_Error` y la
  cadena se propaga hasta la primera llamada, que es la que
  dispara el bloque `errores:`.

## Hard Rules

1. **Tablas del backend viven en el servidor.** El front no las
   vincula; excepcion unica: la tabla de configuracion. Cualquier
   intento de vincular otra tabla produce divergencia silenciosa
   entre back y front.

2. **Forms desacoplados.** Ningun form tiene origen de datos
   (table), ni combos, ni listboxes con `RowSource` apuntando a
   una tabla. Todos los datos del form se obtienen via
   repository / controller. `DoCmd.OpenQuery` y `DoCmd.RunSQL`
   desde un modulo de form son antipatron.

3. **Expresiones Access-only y pass-through queries sobre
   linked tables.** Las expresiones especificas de Access (`IIf`,
   `Nz`, `Choose`, operador `\`, `--` para comentarios,
   `#MM/DD/YYYY#` para fechas) **no se traducen** al back-end
   no-Access y fallan en queries contra linked tables; las
   pass-through queries (`dbOpenSnapshot` con ODBC connect
   string) envian SQL literal al back-end, donde esas
   expresiones no existen. En esos casos use `OpenRecordset` con
   `DAO.Database` explicito o sintaxis nativa del back-end.
   `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `GROUP BY` y
   `CurrentDb()` siguen funcionando sobre linked tables: Access
   expone las vinculadas como `TableDef` ordinarios en
   `CurrentDb.TableDefs` y el motor ACE las procesa como si
   fueran locales.

4. **El ERD del backend vive en `OPENSPEC`.** Como
   `OPENSPEC/<proyecto>/ERD.md` por convencion, o el path
   alternativo que documente la seccion de documentacion del
   `AGENTS.md` del proyecto. No improvise SQL sin haber leido o
   generado ese documento.

5. **`dysflow.sync` no se usa.** Para modificar un modulo del
   binario use `dysflow.import_modules` con el `moduleNames`
   explicito de los modulos efectivamente cambiados. Para
   extraer source desde el binario use `dysflow.export_modules`
   con `exportPath` apuntando a una ruta temporal fuera del
   repo y `mutateBinary: false`. Despues de importar corra
   `dysflow.drift`; el conteo de divergencias debe ser 0 antes
   de pasar tests.

6. **CodeGraph obligatorio para orientarse.** Inicialice con
   `gentle-ai codegraph init <project-root>` si falta. Use
   `codegraph_explore` (MCP) en lugar de `grep` directo.

7. **Identidad via lanzadera.** El correo electronico del usuario
   llega inyectado al abrir Access; no use `Environ`, no use
   login de Windows, no agregue pantalla de login. El
   repositorio consume una identidad ya validada.

8. **El `.accdb` SI se commitea** como binario final del estado.
   No es editable a mano de manera libre, pero el flujo valido
   incluye edicion manual + `dysflow.export_modules`
   subsecuente para sincronizar source. Toda modificacion sin
   exportar deja source desactualizado y dispara `dysflow.drift`.

9. **Code en `.cls`, UI en `.form.txt`.** Cada form tiene dos
   artefactos en source: un `.cls` que contiene el codigo VBA
   del modulo (procedimientos, eventos, helpers), y un
   `.form.txt` que contiene la declaracion UI (controles,
   propiedades de layout, formato). `dysflow.import_modules`
   toma la UI del `.form.txt` **y sobreescribe** la seccion
   de codigo del binario con lo que diga el `.cls`. Esto
   significa: cambie codigo en el `.cls`; cambie UI en el
   `.form.txt`. Si escribe codigo VBA en el `.form.txt`, la
   siguiente importacion lo machaca con la version que diga
   el `.cls`. Y al reves: si solo edita el `.form.txt` y no
   toca el `.cls`, los cambios de UI llegan pero el codigo
   sigue siendo el viejo.

## Plantillas de referencia

### Sub final (handler de click, menu, boton)

```vba
Private Sub ComandoMenuParteProyecto_Click()

    On Error GoTo errores
    VBA.DoEvents
    DoCmd.Hourglass True
    VBA.DoEvents

    m_Error = ""
    DoCmd.OpenForm "Form0BDOpcionesParteProyectos"

    VBA.DoEvents
    DoCmd.Hourglass False
    VBA.DoEvents
    Exit Sub
errores:
    DoCmd.Hourglass False
    If Err.Number <> 1000 Then
        m_Error = "Al ComandoMenuParteProyecto_Click se ha producido"
                & " el error n: " & Err.Number & vbNewLine
                & "Detalle: " & Err.Description
        If <existe CorreoAlAdministrador> Then CorreoAlAdministrador m_Error
        pregunta = MsgBox(m_Error, vbCritical, "Error")
    Else
        pregunta = MsgBox(m_Error, vbExclamation, "Advertencia")
    End If
End Sub
```

### Sub intermedia (propaga el error hacia arriba)

```vba
Public Sub HacerAlgo(p_Param1 As String, _
                       Optional ByRef p_Error As String)

    On Error GoTo errores
    m_Error = ""
    ... cuerpo ...
    Exit Sub
errores:
    p_Error = "HacerAlgo: error n: " & Err.Number _
              & vbNewLine & "Detalle: " & Err.Description
End Sub
```

La sub que invoca a `HacerAlgo` recibe `p_Error`; si NO esta
vacio, lo concatena a su propia `m_Error` y propaga. La primera
llamada en la cadena es la "sub final" cuya `errores:` ejecuta el
bloque con `CorreoAlAdministrador` + MsgBox.

## Anti-patterns (gotchas VBA clasicos)

- **Globals de modulo definidos fuera del inicio.** VBA/Access
  rechaza la declaracion despues del primer procedimiento. Ponlos
  en cabecera, antes de cualquier `Sub`/`Function`.
- **Codigo sin formato.** Una linea por declaracion / sentencia
  en bloques `If` / `For` / `With`. "Todo en una linea" no
  aporta.
- **Llamar un metodo de clase sin instanciar.** VBA evalua la
  expresion al momento de la llamada; `obj.Metodo()` con `obj`
  nulo falla en runtime, no en compilacion.
- **`If obj Is Nothing And obj.Property`.** VBA NO garantiza
  short-circuit evaluation en todas las versiones de Access.
  Separar en dos lineas: `If obj Is Nothing Then ... Else If
  obj.Property ...`.
- **`On Error Resume Next`** salvo en bloques donde se ha
  controlado especificamente el error y se registra.
- **`DoCmd.SetWarnings False`** sin `True` en finally. Cualquier
  excepcion entre el `False` y el `True` deja las action queries
  silenciadas para el resto de la sesion.
- **Recordsets sin `Close` ni `Set rs = Nothing`.** Los cursores
  abiertos bloquean recursos hasta que Access cierre el archivo.
- **Sin `Cancel = True` en `BeforeUpdate` cuando falla la
  validacion.** El dirty state queda persistiendo hasta que otro
  evento lo corrija.
- **`Nz(x, 0)` ciego.** `Nz` reemplaza Null con un default; a
  veces el comportamiento correcto es propagar Null. Use `Nz`
  solo cuando la semantica zero o empty string es valida.
- **`DoEvents` en loops cortos.** Util en loops de miles de
  iteraciones donde la UI necesita responder; en codigo de 10
  registros es ruido.
- **`DoCmd.OpenQuery` o `DoCmd.RunSQL` desde un modulo de form.**
  La UI bindea a un controller; el data access va por
  repository, no por DoCmd.
- **`Database.SaveCopyToPath` antes de cualquier migracion
  estructural.** Sin backup, una migracion fallida deja el
  archivo inutilizable.
- **`Option Explicit`** obligatorio al inicio de cada modulo.
  Sin el, un typo de variable no declarada se vuelve bug
  silencioso en runtime.

## Procedencia

Esta skill consolida fricciones observadas en proyectos DysTelefonica
VBA/Access y reglas que ya viven en skills del catalogo:

- `access-vba-tdd-fundamentos`, `access-vba-tdd-loop`,
  `access-vba-tdd-quality`, `access-vba-tdd-sandbox`,
  `access-vba-capability-docs`, `access-vba-e2e-methodology`
  (TDD, runner contract, cardinalidad, sandbox, fixtures,
  capability docs).
- `vba-binary-sync`, `vba-binary-drift`,
  `vba-module-source-readback` (sync source-binario,
  drift, readbacks).
- `vba-toolkit-evolve`, `vba-form-repair`,
  `vba-extract-candidates`, `vba-symbol-rename`,
  `vba-control-rename-safe`, `vba-event-tracer`,
  `vba-handler-backtrace`, `vba-source-impact`,
  `vba-sql-impact`, `vba-query-decoupler` (renames,
  repair, tracing, blast radius, queries).
- `dysflow-usage`, `dysflow-arnes` (arneses Dysflow oficial).

Las reglas agregadas que NO estan literales en una sola skill del
catalogo (sintesis cross-skill mas observaciones del autor):

- Forms desacoplados (regla del modelo del equipo, no en skill).
- Identidad propagada por la lanzadera (regla del modelo del
  equipo, no en skill).
- SQL agregado y `CurrentDb` fallan contra tablas del back
  (combinacion de reglas: `vba-sql-impact` + constatacion
  practica del autor).
- `dysflow.import_modules` selectivo y `dysflow.export_modules`
  con `mutateBinary: false` para la ruta temporal de seguridad
  (lo que el autor explico durante la revision; no esta en
  ninguna skill).
- Patron de sub final / sub intermedia para propagacion de
  errores (codigo concreto del autor, vive en este skill como
  referencia de plantilla).
- `If obj Is Nothing And obj.X` (VBA no garantiza short-circuit).

Si una regla de esta skill entra en conflicto con una skill
especifica del catalogo, prima la skill especifica (siempre que
cargue el arnes correcto). Esta skill es la entrada rapida; las
otras son la fuente canonica de cada concern en detalle.
