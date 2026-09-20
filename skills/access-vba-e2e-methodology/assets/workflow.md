# Detailed 7-step E2E workflow (Access/VBA)

Referenced from the main SKILL.md. Read this when executing the methodology in a real project.

## Step 1 — Map the workflow

For the request type(s) in scope (PC, CDCA, CDCASUB, PCSUB), read `src/classes/DatosXxxServicio.cls` and enumerate every workflow step:

```text
- AltaSolicitud            → DatosXxxServicio.AltaSolicitud()
- AsignarTecnico           → DatosXxxServicio.AsignarTecnico()
- GuardarDatosGenerales    → DatosXxxServicio.GuardarDatosGenerales()
- CrearPropuesta           → DatosXxxServicio.GuardarPropuesta()
- AprobarPropuesta         → DatosXxxServicio.AprobarPropuesta()
- CrearImpacto             → DatosXxxServicio.GuardarImpacto()
- AprobarImpacto           → DatosXxxServicio.AprobarImpacto()
- GuardarDictamenRAC       → DatosXxxServicio.GuardarDictamenRAC()
- GuardarDecisionFinal     → DatosXxxServicio.GuardarDecisionFinal()
- GuardarAprobacionSuministrador → DatosXxxServicio.GuardarAprobacionSuministrador()
- Cierre                   → DatosXxxServicio.Cerrar()
```

Workflow method names ARE atom name anchors. Keep this list handy for the whole methodology.

## Step 2 — Audit forms in scope

For each `.cls` form in scope (e.g., `Form_frmDatosPCSUB.cls`, `Form_subfrmDatosPCSUB_DictamenRAC.cls`, `Form_frmAltaSolicitud.cls` only the PC_SUB branch):

```text
Form: Form_subfrmDatosPCSUB_DictamenRAC.cls
Event: cmdGuardar_Click
Lines: 145-218
Logic: reads controls, builds dict, calls servicio.GuardarDictamenRAC, shows MsgBox "Datos guardados"
Issue: business logic inline (the validation chain, the dict construction, the MsgBox trigger) is not testable from COM
Target helper: DictamenRACHelper.GuardarDictamenRAC(dict, db) → returns prompt result code
```

Output: list of (form, line range, event, logic, target helper module).

## Step 3 — Extract helpers (TDD rojo-primero)

For each audit item:

1. Write atom in `Test_<Feature>_Strict.bas` that describes the CURRENT behavior (e.g., "when cmdGuardar is clicked with valid data, the row is inserted and the success message is shown"). The atom must FAIL because the helper doesn't exist yet.

2. Refactor the form's event handler to call the helper instead of running inline logic. The atom now PASSES.

3. Assert behavior preservation: same DB state, same MsgBox outcome.

```vb
' Helper signature (MsgBox seam so tests can assert without modal)
Public Function GuardarDictamenRAC(ByVal p_Dict As Object, _
                                   Optional ByRef db As DAO.Database = Nothing, _
                                   Optional ByRef p_PromptResult As Long = vbOK) As Boolean
    ' ... extracted logic ...
End Function
```

## Step 4 — Write UAT-oriented atoms

For each workflow step, write atoms in 4 scenario classes:

| Class | Question | Example atom name |
|---|---|---|
| Happy | "Normal user fills all fields correctly → expected outcome?" | `Test_PCSUB_GuardarDictamenRAC_PersistsValidRAC` |
| Sad | "User leaves required field blank → expected error?" | `Test_PCSUB_GuardarDictamenRAC_BlankDecision_ReturnsValidationError` |
| Edge | "User enters max-length string / special chars / negative number?" | `Test_PCSUB_GuardarDictamenRAC_MaxLengthTruncates` |
| Adversarial | "User double-clicks save / opens same record twice / closes mid-save?" | `Test_PCSUB_GuardarDictamenRAC_DoubleSave_Idempotent` |

Each atom MUST be:
- Schema-first (read ERD before INSERT — see `access-vba-tdd-fundamentos` §1.3)
- Cardinalidad before/after for mutations (§4.5)
- Sandbox-safe (no production writes — §3, §7)
- JSON contract (`{ok, value, payload, error, logs}` — §2)

## Step 5 — Build UAT scenarios

For each UAT-visible rule (NOT each technical step), generate a card:

```text
UAT-2 (BR-RAC-001)
Título: "Dictamen RAC exige racDecision"
DADO: una solicitud PCSUB con racCodigo y racNombre llenos pero racDecision vacío
CUANDO: el usuario hace clic en "Guardar" en el subform de Dictamen RAC
ENTONCES: aparece un mensaje indicando "El campo racDecision es obligatorio"
Esperado: el sistema NO marca el dictamen como completo y NO persiste los datos
pasos:
  1. Abre una solicitud PCSUB existente
  2. Navega al subform "Dictamen RAC"
  3. Completa "Código RAC" con "RAC-001" y "Nombre RAC" con "Juan Pérez"
  4. Deja "Decisión" en blanco
  5. Pulsa "Guardar"
ref: commit bd319a2 → Test_PCSUB_GuardarDictamenRAC_BlankDecision_ReturnsValidationError
```

Each card follows the `feature-acceptance-uat` shape: `pasos` (click-by-click), `esperado` (user-visible outcome), `ref` (commit + atom, audit only — NOT shown in user-facing card).

## Step 6 — Verify all green

```bash
dysflow test_vba testsPath=tests/tests.pcsub.json
# Esperado: ok=true, X/Y pass, 0 failures
```

If any atom is red, the workflow is NOT ready for UAT. Fix and re-run. UAT goes out only when 100% green.

## Step 7 — Generate UAT HTML

Use `feature-acceptance-uat` skill. Classify every change on both axes FIRST, then generate the matching web(s):

- **`usuario` cases** (observable through the UI) → **user web** at `docs/uat/uat-staging-<YYYY-MM-DD>.html`.
- **`desarrollo` cases** (infra / not user-observable: performance, migration, indexes, encoding, cache, sync) → **developer validation web** at `docs/uat/uat-dev-<YYYY-MM-DD>.html`. This is its OWN signed instrument (same shape: `pasos` + `esperado` + PASA/FALLA + checksum-signed record), NOT a flat markdown file. Promotion to production requires BOTH records closed when both axes are present.

Both webs are generated from `assets/uat-acceptance-web.template.html` (set `audience`), self-contained (one `.html`, no server, no external deps), Telefónica-branded, with DADO/CUANDO/ENTONCES criteria, multiple signers, a download button → checksum-signed record (freezes the version), and a pre-filled `mailto:`.

Do NOT put internal TDD atom names or jargon in either web's case bodies — they belong in the traceability `ref` inside the signed record.

## Traceability

The full 6-column table (workflow step / TDD atom / UAT card ref / commit / cap-doc §5 row / # correlativo) is the source of truth. See `assets/tdd-uat-traceability-template.md` for the template. Update at every change. Cap-doc §5 ledger is updated at sign-off and on production release.