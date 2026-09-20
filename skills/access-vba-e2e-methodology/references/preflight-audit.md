# Mandatory Preflight Audit — verify before writing ANY code

**Hard gate, non-negotiable.** Before writing a single line of VBA/SQL/form-control reference in any Access/VBA project, audit the real shape of the project. **No assumptions, no inventions.** Every name, property, method, form control, and table column referenced in new code MUST be verified against the live source/binary BEFORE the code is written.

If ANY of these four audits is skipped, STOP and run it before continuing. "I'll figure it out from the compile error" is not acceptable — every compile-error round-trip wastes 5-15 minutes and corrupts the user's flow. The four audits combined take <2 minutes with `Select-String` / `get_observation` / `get_schema`.

## 1. ERD / table schema audit

Before writing ANY SQL (DAO `qdf.Execute`, `db.Execute`, `DoCmd.RunSQL`, query definitions, hard-coded column lists): read the real schema (`ERD/` folder in the repo if present, or `dysflow.get_schema` / `dysflow.list_tables` for the live backend). Confirm every table name, column name, relationship, and FK.

SQL written against an assumed schema = silent data corruption or runtime error 3061 ("too few parameters").

## 2. Entity properties audit

Before reading OR writing any property on a class instance (`pcDB.idEstadoFinal`, `vm.vm_decisionFinal`, `sol.idSolicitud`, etc.): open the `.cls` file and verify the property exists, with the exact name and type. Class properties in this stack are `Public` fields declared at the top of the class (no `Property Get/Let` unless the class uses that pattern).

Real failure: an agent wrote `pcDB.idEstadoFinal` against `DatosPCSUB.cls`; the entity had no such property → `VBA compile error: method or data member not found`, wasted session.

## 3. Form controls audit

Before referencing ANY `Me.ControlName`, `Forms("X").Controls("Y")`, `Me.Controls("Z")`, or any `<ControlName>_<Event>` handler: read the matching `src/forms/<FormName>.form.txt` and confirm `Name ="<ControlName>"` exists, AND the event property (`OnClick`, `AfterUpdate`, etc.) is wired with `[Event Procedure]` if you are keeping/adding an event handler.

```powershell
# Verify the control exists before referencing Me.<ControlName>
Select-String -Path 'src\forms\Form_<Name>.form.txt' -Pattern 'Name ="<ControlName>"'

# Verify the event property is wired when adding/keeping a handler
Select-String -Path 'src\forms\Form_<Name>.form.txt' -Pattern 'OnClick ="\[Event Procedure\]"|AfterUpdate ="\[Event Procedure\]"|OnExit ="\[Event Procedure\]"'
```

If the control does not exist with that exact name, do NOT add code that references it. Decide whether the UI needs a new/renamed control or whether the code is stale and must be removed/fallbacked.

**Do not confuse this with where code lives.** Form behavior code is edited in the form's `.cls` only. The `.form.txt` is UI/layout only (controls, captions, positions, `ControlSource`, `RowSource`, event-property wiring). Never put business logic or edited `CodeBehindForm` code in `.form.txt`; Dysflow imports overwrite embedded code-behind from the sibling `.cls`.

## 4. Method signatures audit

Before calling ANY method on any service/repositorio/helper (`WorkflowServicio.EjecutarCierreFormalizacion`, `AdjuntoRepositorio.Eliminar`, `TestHelper.BuildJsonOk`, etc.): open the implementation file and read the actual `Public Function`/`Public Sub` signature. Verify:

- (a) the method exists,
- (b) parameter count, order, and types match,
- (c) `ByRef` vs `ByVal` matches how the caller passes the argument (calling with `ByRef` against a public global from a form handler = "ByRef argument type mismatch").

Real failure: an agent called `ValidacionRevisionServicio.RevisarCierrePermitido(usuario, idSol, db)` — the method did NOT exist on the class (only RAC methods exist), causing a compile error that blocked the whole binario.

## Why this rule exists

The forms-thin-refactor and condor pcsub-coverage sessions both produced agents that wrote plausible-looking code against assumed entity shapes and got bitten by `method or data member not found` for properties/methods that did not exist. The cost of skipping the audit was always higher than the cost of doing it.
