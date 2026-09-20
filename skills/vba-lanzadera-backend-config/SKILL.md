---
name: vba-lanzadera-backend-config
description: "Trigger: configurar entorno Lanzadera, auditar TbConfiguracionBackends, refactorizar setup VBA. Aplica convención filesystem-driven."
license: Apache-2.0
metadata:
  author: "ardelperal"
  version: "1.0"
---

# vba-lanzadera-backend-config

## Activation Contract

Load when configuring/auditing/refactoring a Telefónica Dys VBA/Access tool in the Lanzadera ecosystem (NO_CONFORMIDADES, GESTION_RIESGOS, EXPEDIENTES, CONDOR, Concesiones) AND the change touches `TbConfiguracionBackends`, `EVE`, `m_NombreCarpeta`, or the `URL*` chain. Skip for non-Lanzadera tools or web stacks.

## Hard Rules

1. `m_NombreCarpeta = fso.GetBaseName(m_RutaDirectorioAplicacion)` — NEVER `IIf(EnPruebas, ...)`, `IIf(BackendActivo, ...)`, or a `CarpetaAplicacion_*` column.
2. `m_URLRutaAplicacionesRemotas = fso.GetParentFolderName(...)` — NEVER manual parsing.
3. `URLDirectorioAplicaciones` returns `m_URLRutaAplicacionesRemotas` always — NEVER branch on `EsBackendLocal()`.
4. `URLDirectorioLocal` = `Environ$("APPDATA") & "\Aplicaciones DYSN\"` + `m_NombreCarpeta`. Resources do NOT live here.
5. `Application.TempVars("EnPruebas")` queried ONLY in notification lifecycle (`Form_FormCorreo`, `HtmlCabeceraPruebas`, `ResolverDestinatariosNotif`, `Form_Form0BD*` cosmetic, `Entorno.TituloUsuarioConectado` cosmetic, `Funciones Generales.bas:1246` locked).
6. `EnDesarrollo` MUST NOT exist as published TempVar or consumed column. Drop the line.

## Decision Gates

| Question | If YES | If NO |
|----------|--------|-------|
| Tool reads routes from a table? | Use `TbConfiguracionBackends.RutaDirectorioAplicacion_*` | Reject this skill |
| Tool writes outputs to user profile? | Apply Lanzadera `%APPDATA%\Aplicaciones DYSN\` prefix | Adjust `URLDirectorioLocal` elsewhere |
| `m_NombreCarpeta` set by `IIf`? | **Refactor** to `fso.GetBaseName(...)` | Skip |
| `URLDirectorioAplicaciones` branches on `EsBackendLocal()`? | **Refactor** to drop the branch | Skip |
| `Application.TempVars("EnDesarrollo")` published? | **Drop** the line | Skip |

## Execution Steps

1. **Schema** — `dysflow.get_schema` for `TbConfiguracionBackends`. Required columns: `BackendActivo`, `BackendProduccion`, `BackendSandbox`, `BackendTest`, `PasswordBackend`, `RutaDirectorioAplicacion_PROD`, `RutaDirectorioAplicacion_LOCAL`, `EnPruebas`. Ignore legacy `CarpetaAplicacion_*` / `EnDesarrollo` if present.
2. **Audit greps** in `src/` — all MUST be zero: `IIf.*BackendActivo.*No Conformidades`, `IIf.*EnPruebas.*No Conformidades`, `Application.TempVars("EnDesarrollo")`, `getRutaAplicacionesLocal`.
3. **`?EVE()` in VBE** — expect `"Variables establecidas correctamente en : <n>"`. Inspect: `URLDirectorioAplicaciones` (parent), `URLDirAplicacion` (full), `URLDirectorioLocal` (`%APPDATA%\Aplicaciones DYSN\<subfolder>\`), `Application.TempVars("EnDesarrollo")` (must be `Empty`).
4. **Refactor** per Anti-patterns if any audit failed.
5. **Smoke-test** — switch `BackendActivo` between `PROD` and `SANDBOX`; parent follows the table route, `URLDirectorioLocal` keeps the Lanzadera prefix.

## Output Contract

Per tool audited, return: `BackendActivo` + row path; grep counts; `?EVE()` result + four inspected values; findings table `Location | Severity | Issue | Fix`; per-Hard-Rule confirmation; if refactor applied, files changed + diff stat.

## Anti-patterns

| Symptom | Fix |
|---------|-----|
| `m_NombreCarpeta = IIf(EnPruebas = "Sí", ...)` | `= fso.GetBaseName(m_RutaDirectorioAplicacion)` in `LeeConfiguracionLocal` |
| `URLDirAplicacion = ... & IIf(BackendActivo = "PROD", ...)` | `& m_NombreCarpeta & "\"` |
| `URLDirectorioAplicaciones` branches on `EsBackendLocal()` | Drop the branch; always `m_URLRutaAplicacionesRemotas` |
| `Application.TempVars("EnDesarrollo")` published | Drop the line; column was removed |
| `getRutaAplicacionesLocal` calls OneDrive lookups | Delete the function; convention is `%APPDATA%\Aplicaciones DYSN\` |
| `Environ$("APPDATA") & "\Aplicaciones DYSN\"` used for resources | Wrong — prefix is for outputs only |

## References

- `docs/architecture/lanzadera-backend-config.md` — two-route diagram.
- `docs/architecture/local-app-folder-vs-remote-app-folder.md` — discovery that formalized the split.
- `odd/tasks/fix-config-env-fso-subfolder.md` — ODD tracking (NC-009-05).
- `src/modules/Variables Globales.bas` — `LeeConfiguracionLocal`, `EVE`, `ResetGlobals`.
- `src/classes/Entorno.cls` — `URLDirectorioAplicaciones`, `URLDirAplicacion`, `URLDirectorioLocal`.
- `src/modules/Test_EntornoCargarConfig.bas` — atoms covering parent derivation and filesystem subfolder.
