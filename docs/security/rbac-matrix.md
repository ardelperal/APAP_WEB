# RBAC Permissions Matrix — APAP_WEB (issue #66)

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
| `DELETE_ANIMALES` | ✅ | ✅ | ❌ |
| `READ_VOLUNTARIOS` | ✅ | ✅ | ✅ |
| `WRITE_VOLUNTARIOS` | ✅ | ✅ | ✅ |
| `DELETE_VOLUNTARIOS` | ✅ | ✅ | ❌ |
| `READ_ADOPCIONES` | ✅ | ✅ | ❌ |
| `WRITE_ADOPCIONES` | ✅ | ✅ | ❌ |
| `DELETE_ADOPCIONES` | ✅ | ❌ | ❌ |
| `READ_ACOGIDAS` | ✅ | ✅ | ❌ |
| `WRITE_ACOGIDAS` | ✅ | ✅ | ❌ |
| `DELETE_ACOGIDAS` | ✅ | ❌ | ❌ |
| `READ_CASAS_ACOGIDA` | ✅ | ✅ | ❌ |
| `WRITE_CASAS_ACOGIDA` | ✅ | ✅ | ❌ |
| `DELETE_CASAS_ACOGIDA` | ✅ | ❌ | ❌ |
| `READ_ENTRADAS` | ✅ | ✅ | ✅ |
| `WRITE_ENTRADAS` | ✅ | ✅ | ❌ |
| `DELETE_ENTRADAS` | ✅ | ❌ | ❌ |
| `READ_MATERIALES` | ✅ | ✅ | ✅ |
| `WRITE_MATERIALES` | ✅ | ✅ | ❌ |
| `DELETE_MATERIALES` | ✅ | ❌ | ❌ |
| `READ_SALUD` | ✅ | ✅ | ❌ |
| `WRITE_SALUD` | ✅ | ✅ | ❌ |
| `DELETE_SALUD` | ✅ | ❌ | ❌ |
| `READ_REPORTES` | ✅ | ✅ | ❌ |
| `WRITE_REPORTES` | ✅ | ❌ | ❌ |
| `READ_CESIONES` | ✅ | ✅ | ❌ |
| `WRITE_CESIONES` | ✅ | ✅ | ❌ |
| `DELETE_CESIONES` | ✅ | ❌ | ❌ |
| `MANAGE_USERS` | ✅ | ❌ | ❌ |

## Legacy Role Backward Compatibility

Legacy roles (`DEVELOPER`, `KEY_USER`, `READER` from `app.core.roles.Rol`) are handled by a fallback:

- **Read permissions**: Any authenticated legacy role can read.
- **Write/Delete permissions**: Only `DEVELOPER` and `KEY_USER` can write; `READER` is read-only.

The fallback preserves pre-RBAC auth behavior while new sessions use the `admin`/`voluntario`/`staff` roles.

## Implementation

- **Model**: `app/core/rbac.py` — `Role` enum, `Permission` enum, `PERMISSIONS` matrix, `require_permission` dependency
- **Route protection**: All write/delete endpoints use `Depends(require_permission(Permission.<X>))`
- **Audit**: `auth.denied` log events with `reason` and `permission` fields on 403

## Notes

- Voluntario cannot write salud or reportes (clinical data and reports require staff/admin oversight)
- Staff cannot manage users (user administration is admin-only)
- Legacy roles are resolved at login and do not appear in the new `Role` enum
