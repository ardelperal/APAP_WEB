# Spec: RBAC-01 — Control de Acceso Basado en Roles (issue #66, task 3.9)

## Context

Issue #66. Sistema RBAC: roles (admin, operador, developer, readonly) con permisos
específicos sobre entidades y operaciones. El sistema actual tiene `authorized_users`
con allowlist de emails + rol developer hardcoded.

## Current state on main@0ab533d

**Ya existe:**
- Tabla `authorized_users` con `email`, `user_id`, `activo`.
- `require_authorized_user` middleware (autenticado = allowlist).
- `require_writer_user` dependency (todos los authenticated users pueden escribir).
- Auth cache con TTL configurable (`APAP_AUTH_CACHE_TTL_SECONDS`).

**Falta:**
- Tabla `roles` con permisos granulares.
- Asignación de roles a users (muchos-a-muchos).
- Middleware de autorización (`require_role(rol)`) que verifique rol además de auth.
- Permisos por entidad (ej. solo `admin` puede borrar; `operador` solo lee y escribe
  en ciertas entidades; `readonly` solo lee).

**Fuente:** `docs/discovery/feature-00-admin-panel.md` §RBAC.

## Required contract

### Modelo de roles

```python
class RolEnum(StrEnum):
    DEVELOPER = "developer"   # acceso total, incluido config
    ADMIN = "admin"           # acceso total salvo config de sistema
    OPERADOR = "operador"     # CRUD en entidades de negocio
    READONLY = "readonly"     # solo lectura

# En tabla authorized_users
class AuthorizedUser:
    email: str          # PK (del OAuth)
    user_id: str        # ID del OAuth provider
    rol: RolEnum
    activo: bool
    creado_en: TIMESTAMPTZ
```

### Permisos por rol

| Permission | developer | admin | operador | readonly |
|------------|:---:|:---:|:---:|:---:|
| `animales:read` | ✅ | ✅ | ✅ | ✅ |
| `animales:write` | ✅ | ✅ | ✅ | ❌ |
| `animales:delete` | ✅ | ✅ | ❌ | ❌ |
| `voluntarios:read` | ✅ | ✅ | ✅ | ✅ |
| `voluntarios:write` | ✅ | ✅ | ✅ | ❌ |
| `entradas:write` | ✅ | ✅ | ✅ | ❌ |
| `acogidas:write` | ✅ | ✅ | ✅ | ❌ |
| `adopciones:write` | ✅ | ✅ | ✅ | ❌ |
| `sanidad:write` | ✅ | ✅ | ✅ | ❌ |
| `reportes:execute` | ✅ | ✅ | ✅ | ❌ |
| `usuarios:manage` | ✅ | ✅ | ❌ | ❌ |
| `roles:manage` | ✅ | ❌ | ❌ | ❌ |
| `config:read` | ✅ | ✅ | ❌ | ❌ |
| `config:write` | ✅ | ❌ | ❌ | ❌ |

### Tablas

#### `roles_permisos` (existing extended)

Extender la tabla `authorized_users` o crear tabla `user_roles`:

| Campo | Tipo |
|-------|------|
| `email` | TEXT → authorized_users |
| `rol` | RolEnum |
| `activo` | BOOLEAN |

### Middleware

```python
def require_role(*roles: RolEnum):
    """Dependency that checks user has one of the required roles."""
    async def check_role(user = Depends(get_current_user)):
        if user.rol not in roles:
            raise HTTPException(403, "No tienes permisos para esta operación")
        return user
    return check_role
```

### Endpoints admin

```
GET  /admin/users                    # list all users with roles
POST /admin/users                    # add user to authorized_users with rol
PATCH /admin/users/{email}/rol       # change user rol
DELETE /admin/users/{email}          # deactivate user
```

## Dependencies

- Task 3.11 (UX/UI foundation) — para el panel admin de gestión de usuarios.

## Acceptance criteria

1. `require_role(ADMIN)` bloquea acceso a `OPERADOR` en endpoints de admin.
2. `DELETE /animales/{id}` bloquea para `OPERADOR` y `READONLY` → 403.
3. `GET /reportes/ejecutar` bloquea para `READONLY` → 403.
4. `PATCH /admin/users/{email}/rol` cambia el rol del usuario (admin only).
5. El rol se cachea en auth cache (mismo TTL que auth actual).
6. Cambio de rol no requiere re-login — se invalida el cache del user.
7. Logs via `log_safe("auth.role_changed", email, old_rol, new_rol, by=user_id)`.

## Out-of-scope

- Permisos granulares por entidad individual (ej. "este operador solo puede
  ver animales en estado Albergue"). Eso es un refinamiento futuro.
- Auditoría de accesses denegados (access log).
