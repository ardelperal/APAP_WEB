# RBAC Permissions Matrix — APAP_WEB (issue #66)

[Back to Security overview](../codebase/security.md)

Esta página posee la matriz canónica de permisos por rol en APAP_WEB. No posee la política de CSRF ni la política de logging de `auth.denied` — esas viven en [`docs/codebase/security.md`](../codebase/security.md) y en [`docs/codebase/logging-conventions.md`](../codebase/logging-conventions.md).

## Roles

| Role | Description |
|------|-------------|
| `admin` | Full system access. All permissions. |
| `voluntario` | Field volunteers. Manage animals and volunteers, read-only intake/materials. |
| `staff` | Shelter staff. Broad domain write access except user management. |

## Permission Matrix

| Permission | admin | staff | voluntario |
|------------|:-----:|:-----:|:---------:|
| `READ_ANIMALES` | ✅ | ✅ | ✅ |
| `WRITE_ANIMALES` | ✅ | ✅ | ✅ |
| `READ_VOLUNTARIOS` | ✅ | ✅ | ✅ |
| `WRITE_VOLUNTARIOS` | ✅ | ✅ | ✅ |
| `READ_ADOPCIONES` | ✅ | ✅ | ❌ |
| `WRITE_ADOPCIONES` | ✅ | ✅ | ❌ |
| `READ_ACOGIDAS` | ✅ | ✅ | ❌ |
| `WRITE_ACOGIDAS` | ✅ | ✅ | ❌ |
| `READ_CASAS_ACOGIDA` | ✅ | ✅ | ❌ |
| `WRITE_CASAS_ACOGIDA` | ✅ | ✅ | ❌ |
| `READ_ENTRADAS` | ✅ | ✅ | ✅ |
| `WRITE_ENTRADAS` | ✅ | ✅ | ❌ |
| `READ_CESIONES` | ✅ | ✅ | ❌ |
| `WRITE_CESIONES` | ✅ | ✅ | ❌ |
| `READ_MATERIALES` | ✅ | ✅ | ✅ |
| `WRITE_MATERIALES` | ✅ | ✅ | ❌ |
| `READ_SALUD` | ✅ | ✅ | ❌ |
| `WRITE_SALUD` | ✅ | ✅ | ❌ |
| `READ_REPORTES` | ✅ | ✅ | ❌ |
| `WRITE_REPORTES` | ✅ | ❌ | ❌ |
| `MANAGE_USERS` | ✅ | ❌ | ❌ |

La tabla refleja exactamente el enum `Permission` y la matriz `PERMISSIONS` de `app/core/rbac.py`; no existen permisos `DELETE_*` en el enum (los endpoints de borrado declaran permisos `write:*`).

## Legacy Role Backward Compatibility

Legacy roles (`DEVELOPER`, `KEY_USER`, `READER` from `app.core.roles.Rol`) are handled by an **explicit mapping**, not by an open fallback (issue #923, decision D-44):

- **Read permissions**: cada rol legacy recibe el conjunto explícito de `_LEGACY_READ_MATRIX` en `app/core/rbac.py` — hoy, exactamente los 10 permisos `READ_*` de la matriz (cero impacto para los usuarios actuales). No hay `read:*` genérico: un permiso de lectura nuevo no alcanza a los roles legacy hasta que se añade explícitamente al mapeo.
- **Write/Delete permissions**: solo `DEVELOPER` y `KEY_USER` pueden escribir (`_LEGACY_WRITER_ROLES`); `READER` es read-only.
- **Fail-closed**: cualquier otro string de rol no reconocido recibe 403 también en lecturas.
- **Guard test**: `test_legacy_read_matrix_covers_every_read_permission` en `tests/test_rbac.py` falla con mensaje que nombra el par (rol, permiso) si un permiso de lectura nuevo aparece sin decisión explícita para cada rol legacy.

El mapeo preserva el acceso real de los usuarios: todos los roles asignables hoy son legacy (el panel de admin construye su selector desde `VALID_ROLES`, derivado del enum `Rol`; `voluntario`/`staff` no son asignables desde ahí).

## Implementation

- **Model**: `app/core/rbac.py` — `Role` enum, `Permission` enum, `PERMISSIONS` matrix, `require_permission` dependency
- **Route protection**: All write/delete endpoints use `Depends(require_permission(Permission.<X>))`
- **Audit**: `auth.denied` log events with `reason` and `permission` fields on 403

## Notes

- Voluntario cannot write salud or reportes (clinical data and reports require staff/admin oversight)
- Staff cannot manage users (user administration is admin-only)
- Legacy roles are resolved at login and do not appear in the new `Role` enum

## Core invariants

- **Role enum cerrado**: los únicos roles válidos son `admin`, `staff` y `voluntario`. No añadir roles ad-hoc; ampliar la matriz requiere PR con justificación y prueba de cobertura en `tests/`.
- **Permission enum es la fuente**: cada endpoint de escritura o borrado declara `Depends(require_permission(Permission.<X>))`. Una ruta nueva sin esa dependencia no es apta para `main`.
- **Admin es el único con `MANAGE_USERS`**: ningún otro rol concede gestión de usuarios; staff y voluntario pierden acceso a `/admin` aunque cambien otras celdas de la matriz.
- **`voluntario` no escribe `SALUD` ni `REPORTES`**: datos clínicos e informes requieren staff o admin. La regla existe por la sensibilidad de esos datos y se mantiene aunque el equipo crezca.
- **Compatibilidad legacy solo en read o en write de `DEVELOPER`/`KEY_USER`**: el fallback no abre nuevas acciones para `READER`. Migrar sesiones legacy al enum nuevo antes de ampliar permisos. Un permiso de lectura nuevo exige extender `_LEGACY_READ_MATRIX` explícitamente; sin ello, el guard test de `tests/test_rbac.py` falla.
- **Audit trail obligatorio en 403**: todo `require_permission` que rechaza emite un evento `auth.denied` con `reason` y `permission`. Sin log no hay enforcement verificable.

## Contributor checklist

- [ ] Si añade un permiso nuevo, declararlo en `Permission` y asignar al menos un rol en `PERMISSIONS`, con cobertura en `tests/`.
- [ ] Si añade un rol nuevo, justificarlo en el PR (caso de uso, alcance, qué permisos obtiene, quién lo pierde).
- [ ] Si elimina una capacidad, migrar primero los endpoints que la usan a su permiso equivalente, luego cerrar la fila en la matriz.
- [ ] Si cambia una celda de la matriz, regenerar la tabla de este doc en la misma sesión para que la matriz humana no se desincronice del enum.
- [ ] Si modifica el fallback legacy, añadir un test que verifique que `READER` sigue sin escribir y que `DEVELOPER`/`KEY_USER` siguen pudiendo.

## Navigation

Back: [Codebase security](../codebase/security.md) | Next: [Setup local](../setup.md)
