# Copia local de Access para pruebas de migración

Este directorio contiene las copias de Access autorizadas para las pruebas locales de migración. El remoto es privado y se ha aceptado expresamente la permanencia de estos datos en el historial de Git.

## Ubicación de los archivos

| Ruta | Contenido local | Estado en Git |
|---|---|---|
| `frontend/APAP_Alcala.accdb` | Copia autorizada del frontend | Versionable |
| `backend/Registro_APAP_Alcala_datos_18.accdb` | Copia autorizada del backend con datos legacy | Versionable |
| Cualquier otro archivo bajo `frontend/` o `backend/` | Locks, copias alternativas y artefactos temporales | Ignorado |

Los archivos `.gitkeep` conservan la estructura. Solo se pueden versionar los dos nombres exactos indicados en la tabla.

## Core invariants

- **Solo copias**: copie el frontend y el backend de producción; nunca abra ni use los originales desde este directorio.
- **Backend aislado**: vuelva a vincular el frontend local únicamente contra la copia de `backend/` antes de ejecutar pruebas.
- **Allowlist exacta**: no fuerce la inclusión de otros `.accdb`, `.mdb`, locks, copias ni archivos temporales colocados bajo `frontend/` o `backend/`.
- **Sandbox obligatorio**: ejecute las pruebas contra una copia desechable o un sandbox. Nunca escriba en el backend productivo.
- **Datos sensibles**: trate las copias autorizadas como información sensible. No las publique fuera del remoto privado ni las incluya en artefactos de CI, logs o evidencias compartidas.

## Preparación local

1. Cierre Microsoft Access y obtenga copias consistentes del frontend y del backend de producción.
2. Coloque las copias con los nombres exactos indicados en la tabla.
3. Cree una copia de trabajo desechable para cada ejecución que pueda escribir datos.
4. Configure los vínculos del frontend de trabajo para que apunten exclusivamente al backend de trabajo.
5. Verifique que solo los dos binarios autorizados sean versionables y que los demás archivos permanezcan ignorados.

Este directorio no sustituye a `tests/migration/fixtures/`: esa ubicación está reservada para fixtures sintéticos, deterministas y sin PII descritos en `docs/quality/migration-e2e-plan.md`.

## Contributor checklist

- [ ] El frontend y el backend utilizados son copias, no archivos productivos.
- [ ] Los vínculos del frontend apuntan a un backend de sandbox.
- [ ] `git status` solo muestra como candidatos los dos binarios autorizados por su nombre exacto.
- [ ] La evidencia de prueba no contiene rutas sensibles ni PII.

## Navigation

Back: [Plan E2E de migración](../../../docs/quality/migration-e2e-plan.md)
