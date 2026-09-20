# Helper naming, collision audit, and compile-error protocol

These rules exist because of a real failure: a helper that used generic public names (`Reset`, `RefrescarNodoRiesgoActual`, `ResolverTipoDetalle`) collided with names already in `Funciones Generales.bas` and other legacy modules. The user had to compile, hit a "nombre ambiguo" error in the VBE, and the failure looped. Do not repeat.

## Public names MUST be globally unique

Before declaring a `Public Sub`/`Public Function` in any new helper, run the collision audit:

```powershell
# From PowerShell, before writing a new .bas
$myNewNames = @("MiHelper_FuncionA", "MiHelper_SubB")   # list your public exports
Get-ChildItem -Path src\modules -Filter *.bas | ForEach-Object {
    Select-String -Path $_.FullName -Pattern '^(Public)\s+(Sub|Function)\s+(\w+)' |
    ForEach-Object { if ($myNewNames -contains $_.Matches.Groups[3].Value) { "CHOCE: $($_.FileName):$($_.LineNumber): $($_.Line.Trim())" } }
}
```

If output is non-empty, rename your exports with a per-module prefix. **Do not import a `.bas` that fails this check.** Run this audit ONCE at the start of a session; the output is a static reference of what exists. Re-run it if the session reverts + reimports.

## Use a per-module prefix on all public names

Convention: `<ModuleName>_<FunctionName>` (underscore). Examples: `EstadoRiesgosActivo_Reset`, `RefrescarRiesgo_NodoRiesgoActual`, `FormInteraction_ObtenerValorControl`. This makes collisions structurally impossible.

Sub-helpers and pre-existing `Funciones Generales.bas` names do NOT need renaming — this applies only to NEW helpers created under this skill.

## Module name ≠ public function name (VBA hard rule)

A standard module and a public function inside it CANNOT share the same name — the compiler resolves the identifier to the module and rejects the call site: *"se esperaba una variable o un procedimiento, no un módulo"*. Use a `mod` prefix or `Helper`/`Util` suffix on the module. (See `access-vba-tdd-fundamentos` §1.6.)

## Naming playbook — pick the name with this checklist IN ORDER

1. **Helper is `<Concepto>Helper.bas` exporting ONE thing** → use the conceptual name. `modNotificacionPorCorreoHelper.bas` exports `NotificarPorCorreo`. No collision risk in a focused helper.
2. **Helper exports MULTIPLE things OR is one of a family** → prefix every export with the module name. `modRiesgoRefrescoHelper.bas` exports `RefrescarRiesgo_NodoRiesgoActual` AND `RefrescarRiesgo_ArbolRiesgosScope`.
3. **Helper name clashes with a legacy public function** (`Reset`, `BuildOk`, `Save`) → the legacy wins; you rename. Do NOT rename the legacy.
4. **Tempted to call it `Helper_X` or `Utils_X`** → stop. The name describes the feature, not its role. `Helper_BuildOk` is a smell; `TestCore_BuildOk` is correct.

Bad names from real sessions (do not repeat):
- `Reset` in a singleton helper — collides with `mIndicador.bas:IndicadorState_Reset`.
- `RefrescarNodoRiesgoActual` — collides with the legacy `Form_FormRiesgosGestion.RefrescarNodoRiesgoActual` (the very thing being refactored away; the refactor must NOT keep the old name as a public export).

## Compile-error protocol — IN ORDER, no skipping

When the user reports a compile error:

1. **Stop all other work.** No next import, no new `.bas`, no `test_vba`.
2. **Ask the user for the exact error text**: (a) VBE dialog title (e.g. "Compile error: Ambiguous name detected"), (b) the ambiguous name, (c) the module locations VBA lists, (d) line number, (e) the signature VBA shows. Do NOT reproduce or guess. A description like "no compila, X es ambiguo" is not actionable.
3. **While waiting**: if `verify_code` is available, run it on the last imported module and the colliding module — this often reveals the duplicated names.
4. **Once you have the error**: identify which two+ modules export the same name. Confirm with `Select-String` over `src/`.
5. **Resolve**: rename your helper's export with a per-module prefix. If the collision is in legacy code (`Funciones Generales.bas`), do NOT touch the legacy — rename your export.
6. **Apply the fix** in the `.bas` on disk, re-import the single changed module, ask the user to compile, confirm.
7. **Document the collision in the commit message** so it does not recur in this project.
