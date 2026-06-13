# Dysflow Notes

## Verified

- `dysflow setup --write-project` created `.dysflow/project.json`.
- `dysflow doctor` reports the Access path is configured and can be opened.
- Dysflow SQL/schema tools can read the backend when `databasePath` is passed explicitly.
- Dysflow object tools now resolve the project config correctly.
- `dysflow_list_objects` works for project id `apap`.
- `dysflow_export_all` works for project id `apap` and exported the Access source into `src/`.

## Resolved issue

VBA/object export-family MCP calls previously returned `CONFIG_MISSING_ACCESS_PATH`. This has been fixed; continue using Dysflow only.

## Object inventory through Dysflow

- Forms: 60
- Reports: 2 (`Subinforme TbRecomendaciones`, `Terapias`)
- Standard modules: 7
- Class modules: 14
- Document modules: 60

Note: report objects are visible through Dysflow inventory, but no `src/reports/*` files were detected after the source export. This needs a focused follow-up before treating report extraction as complete.

## Link warning

The frontend linked tables still point to an older OneDrive backend path:

`C:\OneDrive\OneDrive - Telefonica\01PERSONAL\APAP1\Registro_APAP_Alcala_datos_18.accdb`

The local backend configured for discovery is:

`C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb`

This should be handled explicitly before any write/test workflow. For read-only backend schema discovery, use explicit `databasePath` targeting the local backend.
