# Autenticación y autorización

> Feature fundacional de APAP_WEB. Todo lo demás (animales, voluntarios,
> entradas, etc.) asume que esta capa está en su sitio. Sin login, la
> aplicación no es utilizable.

## 1. Alcance

Esta feature cubre el camino completo desde que un usuario pulsa
"Login" hasta que tiene una sesión activa y puede usar la aplicación,
más el panel de administración que gestiona quién puede acceder.

**Incluye:**

- Login con Google OAuth vía InsForge (con PKCE nativo, sin secreto
  del cliente en el código).
- Verificación de que el email del usuario está en la lista de
  autorizados (`usuarios_autorizados`).
- Emisión de una cookie de sesión firmada (URL-safe, sin estado en
  servidor).
- Logout que invalida la cookie.
- Página `/unauthorized` amigable para emails no autorizados.
- Panel `/admin` (solo para `rol = 'developer'`) con la lista de
  usuarios autorizados y el alta/baja de nuevos.
- Bootstrap en el startup: crea la tabla si no existe y siembra el
  admin inicial a partir de la variable de entorno
  `APAP_INITIAL_ADMIN_EMAIL`.

**No incluye** (queda fuera de esta feature, en otras):

- La lógica de qué puede hacer cada rol dentro de los módulos
  (animales, voluntarios, etc.). Esta feature solo distingue entre
  "logueado y autorizado" y "no logueado o no autorizado".
- El RBAC fino (lectura vs escritura, scope por módulo). Eso es la
  feature RBAC-01 (#66).

## 2. Criterios de aceptación

- Un usuario con email autorizado puede hacer login con Google y obtener
  una sesión activa.
- Un usuario con email no autorizado ve la página `/unauthorized` y no
  recibe sesión.
- La cookie de sesión es `HttpOnly`, `SameSite=Lax`, `Secure` en
  producción, y está firmada con `APAP_SESSION_SECRET`.
- La cookie expira (TTL configurable, default 7 días).
- El panel `/admin` lista todos los usuarios autorizados (activos e
  inactivos), ordenados por fecha de alta descendente.
- Solo `rol = 'developer'` puede ver `/admin`, añadir usuarios o
  desactivarlos.
- Desactivar un usuario (`activo = false`) le quita el acceso
  inmediatamente, preservando el historial de FKs.
- El bootstrap en startup es idempotente: la app puede reiniciar
 无数次 sin duplicar la fila del admin.

## 3. Decisiones de arquitectura

| Decisión | Elección | Alternativa | Por qué |
|---|---|---|---|
| Proveedor de identidad | Google OAuth vía InsForge | Auth propia, OAuth directo con Google | InsForge ya tiene el cliente de Google configurado y verificado; reusar evita mantener el flujo OAuth. |
| Mecanismo de sesión | Cookie firmada con `itsdangerous` | Sesión server-side con Redis | Sin estado en servidor, no hay queprovisionar Redis. La cookie es suficiente porque la única carga útil es `email` + `rol` + `user_id`. |
| PKCE para OAuth | Nativo, sin secreto del cliente en el código | Implicit flow | El estándar para SPAs y apps sin backend confidencial; InsForge lo soporta. |
| Lista de autorizados | Tabla propia `usuarios_autorizados` en InsForge | Reusar el usuario de Google como autorización | Permite gestión fina (roles, activar/desactivar) sin tocar Google Workspace. |
| Modelo de roles | Enum fijo: `developer`, `admin`, `key_user`, `reader` | RBAC dinámico con tabla de permisos | Para el MVP un enum es suficiente; el RBAC dinámico es la feature RBAC-01. |
| Nombres del schema | CamelCase Spanish, exactos del legacy | snake_case English | Consistencia con el resto de tablas de migración (TbFichaAnimal, TbVoluntarios, etc.); ver `docs/architecture/decisiones-proyecto.md` § "Migración y convivencia con legacy". |
| Soft-delete | Columna `activo BOOLEAN NOT NULL DEFAULT true` | DELETE físico | Preserva las FKs históricas; un usuario que tuvo rol `developer` y fue desactivado sigue apareciendo en auditoría. |
| Identificadores | UUID PK con `gen_random_uuid()` | INT autoincrement | Permite generación client-side, no expone el orden de creación, portable entre entornos. |

## 4. Contratos de interfaz

### 4.1 Schema SQL

```sql
CREATE TABLE IF NOT EXISTS usuarios_autorizados (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('developer', 'admin', 'key_user', 'reader')),
    anadido_por UUID,
    activo BOOLEAN NOT NULL DEFAULT true,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now()
)
```

El seed del admin se hace con esta query idempotente:

```sql
INSERT INTO usuarios_autorizados (email, rol, activo)
SELECT $1, 'developer', true
WHERE NOT EXISTS (
    SELECT 1 FROM usuarios_autorizados WHERE rol = 'developer'
)
```

Si no existe ningún `developer`, crea la fila. Si ya existe, no hace
nada. Esto permite re-ejecutar el seed en cada arranque sin duplicar.

### 4.2 Funciones Python (`app/core/auth.py`)

| Función | Firma | Propósito |
|---|---|---|
| `ensure_schema_and_seed` | `(client, settings) -> None` | Crea la tabla (idempotente) y siembra el admin si `settings.initial_admin_email` está configurado y no existe un developer previo. |
| `get_user_by_email` | `(client, email) -> dict \| None` | Devuelve la fila activa con ese email, o `None` si no existe o está inactivo. |
| `list_authorized_users` | `(client) -> list[dict]` | Devuelve todos los usuarios (activos e inactivos), ordenados por `fecha_alta DESC`. Usado por el panel admin. |
| `add_authorized_user` | `(client, email, role, added_by) -> dict` | Inserta un nuevo usuario. Valida que `role` esté en `VALID_ROLES`. Devuelve la fila insertada. |
| `deactivate_authorized_user` | `(client, user_id) -> dict \| None` | Marca `activo = false`. no hace DELETE físico. Devuelve la fila actualizada, o `None` si el id no existe. |

La constante `VALID_ROLES = frozenset({"developer", "admin", "key_user", "reader"})`
es la fuente de verdad de los roles permitidos.

### 4.3 Rutas HTTP (`app/main.py`)

| Ruta | Método | Auth | Propósito |
|---|---|---|---|
| `/login` | GET | Pública | Inicia el flujo OAuth. Si Google no está configurado, devuelve 503. |
| `/auth/callback` | GET | Pública (con PKCE cookie) | Intercambia el `code` por JWT de InsForge, verifica el email contra `usuarios_autorizados`, y emite la cookie de sesión. |
| `/logout` | GET | Pública | Invalida la cookie de sesión. |
| `/unauthorized` | GET | Pública | Página amigable para emails no autorizados. |
| `/admin` | GET | `rol = 'developer'` | Lista de usuarios autorizados. |
| `/admin/users` | POST | `rol = 'developer'` | Alta de nuevo usuario. |
| `/admin/users/{user_id}/deactivate` | POST | `rol = 'developer'` | Desactivación (soft-delete). |

### 4.4 Payload de sesión

La cookie `apap_session` contiene un dict firmado con
`itsdangerous.URLSafeTimedSerializer`. El payload:

```python
{
    "email": "user@example.com",
    "rol": "developer",      # o "admin", "key_user", "reader"
    "user_id": "<uuid>"
}
```

El TTL es configurable vía settings (default 7 días). La firma usa
`APAP_SESSION_SECRET`; cualquier cambio en el secret invalida todas
las sesiones existentes (feature para emergencias).

## 5. Modelo de datos

Diagrama entidad-relación simplificado (solo esta feature):

```
┌─────────────────────────────┐
│   usuarios_autorizados      │
├─────────────────────────────┤
│ id              UUID PK      │◄──── anadido_por (FK self, NULL)
│ email           TEXT UNIQUE  │      si es el primer developer
│ rol             TEXT         │
│ anadido_por     UUID (FK)    │
│ activo          BOOLEAN      │
│ fecha_alta      TIMESTAMPTZ  │
└─────────────────────────────┘
```

`anadido_por` referencia la propia tabla (self-FK). Es NULL para el
primer developer (el sembrado en bootstrap); para los demás, apunta al
`id` del developer que los dio de alta. Esto permite auditoría: "quién
dio de alta a quién y cuándo".

## 6. Plan de tests

Cubierto por `tests/test_auth.py`, `tests/test_auth_flow.py`,
`tests/test_admin.py`, `tests/test_session.py` y `tests/test_lifespan.py`.
Total: 38 tests en esta capa, todos en verde.

| Capa | Qué cubre |
|---|---|
| `test_ensure_schema_creates_usuarios_autorizados_table` | El SQL del CREATE TABLE tiene los campos correctos en español. |
| `test_ensure_schema_seeds_initial_admin_when_configured` | Cuando `APAP_INITIAL_ADMIN_EMAIL` está configurado, se ejecuta el INSERT. |
| `test_ensure_schema_skips_seed_when_no_initial_email` | Si no hay email configurado, no se ejecuta el INSERT. |
| `test_get_user_by_email_returns_row_when_active` | `get_user_by_email` devuelve la fila si existe y está activa. |
| `test_get_user_by_email_returns_none_when_not_found` | Devuelve `None` cuando no hay fila. |
| `test_list_authorized_users_returns_all_rows` | El SELECT devuelve todas las filas, ordenadas. |
| `test_add_authorized_user_inserts_with_anadido_por` | El INSERT incluye los 3 parámetros correctos. |
| `test_deactivate_authorized_user_returns_updated_row` | El UPDATE marca `activo = false`. |
| `test_callback_issues_session_cookie_and_redirects_home` | El flujo OAuth completo emite la cookie con el payload correcto. |
| `test_callback_with_unauthorized_email_redirects_to_unauthorized` | Email no en la tabla → redirect a `/unauthorized`. |
| `test_admin_redirects_to_login_when_not_authed` | Sin sesión → redirect a `/login`. |
| `test_admin_redirects_to_unauthorized_when_rol_not_developer` | Sesión pero sin `rol = 'developer'` → redirect a `/unauthorized`. |
| `test_admin_renders_user_table_for_developer` | Developer ve la tabla de usuarios. |
| `test_admin_add_user_inserts_and_redirects` | POST `/admin/users` añade y redirige. |
| `test_admin_deactivate_user_updates_and_redirects` | POST `/admin/users/{id}/deactivate` desactiva y redirige. |
| `test_lifespan_calls_ensure_schema_and_seed_on_startup` | El startup ejecuta el bootstrap. |

## 7. Historia de migración

**Esta tabla no es target de migración desde el Access legacy.** Es una
tabla nueva, creada para la app web. La autenticación en el Access
legacy es completamente independiente (login de Windows + control de
acceso por formulario VBA).

Durante el periodo de coexistencia (web + Access legacy operando en
paralelo), el modelo de autorizados es solo para la app web. El Access
legacy sigue usando su propio control de acceso. Esto es intencional:
los dos sistemas tienen usuarios diferentes (mientras se hace la
transición) y consolidarlos requiere un plan separado (issue #29 +
feature RBAC-01).

## 8. Notas operacionales

### Cómo añadir un nuevo usuario autorizado

1. Entrar como developer a `https://apap.romancaba.com/admin`.
2. Rellenar el formulario "Añadir usuario" con email y rol.
3. El sistema crea la fila en `usuarios_autorizados` con
   `activo = true` y `anadido_por = <id del developer actual>`.

Alternativa para el seed inicial sin tener que entrar a la app:

```bash
psql $DATABASE_URL -c "INSERT INTO usuarios_autorizados (email, rol) VALUES ('nuevo@example.com', 'key_user');"
```

### Cómo desactivar un usuario

1. Entrar como developer a `/admin`.
2. En la fila del usuario, pulsar "Desactivar".
3. La fila pasa a `activo = false`. El historial de FKs se preserva
   (no se borra nada).

### Cómo rotar el `APAP_SESSION_SECRET`

Cambiar el valor en Coolify y reiniciar. advertencia: invalida todas
las sesiones existentes — todos los usuarios tendrán que hacer login
de nuevo. Útil en caso de compromiso.

### Diagnóstico

Si un usuario reporta que no puede entrar:

1. Verificar que su email está en la tabla:
   ```sql
   SELECT email, rol, activo FROM usuarios_autorizados WHERE email = 'user@example.com';
   ```
2. Si `activo = false`, rehabilitar:
   ```sql
   UPDATE usuarios_autorizados SET activo = true WHERE email = 'user@example.com';
   ```
3. Si no existe, añadirlo desde el panel `/admin` (o vía INSERT directo).

## 9. Diagrama de secuencia — Login exitoso

```
Usuario           Browser          APAP_WEB           InsForge         Google
  │                 │                 │                  │               │
  │  GET /login     │                 │                  │               │
  ├────────────────►│                 │                  │               │
  │                 │  GET /login     │                  │               │
  │                 ├────────────────►│                  │               │
  │                 │                 │ start_google_oauth()            │
  │                 │                 ├─────────────────►│               │
  │                 │                 │◄──── authUrl ────┤               │
  │                 │◄─── 302 ────────┤                  │               │
  │◄────────────────┤  Location: authUrl + PKCE cookie │               │
  │                 │                 │                  │               │
  │ (redirige a Google, hace login, vuelve con code)   │               │
  │                                                              ───────►│
  │◄──────────────────────────────────────────────────────────────  │
  │  GET /auth/callback?code=...  (con PKCE cookie)    │               │
  ├────────────────►│                 │                  │               │
  │                 │  GET /auth/callback                │               │
  │                 ├────────────────►│                  │               │
  │                 │                 │ exchange_google_oauth_code()    │
  │                 │                 ├─────────────────►│               │
  │                 │                 │◄── token + user ─┤               │
  │                 │                 │                  │               │
  │                 │                 │ get_user_by_email()               │
  │                 │                 ├─────────────────►│               │
  │                 │                 │◄── {rol, activo} ─┤               │
  │                 │                 │                  │               │
  │                 │                 │ (write session cookie)           │
  │                 │◄── 302 ────────┤                  │               │
  │◄────────────────┤  Location: /   │                  │               │
  │                 │  Set-Cookie: apap_session=...       │               │
  │                 │                 │                  │               │
  │  (sesión activa)                 │                  │               │
```

## 10. Referencias

- `app/core/auth.py` — schema, seed, CRUD helpers.
- `app/core/insforge.py` — cliente REST de InsForge.
- `app/core/session.py` — firmado y lectura de cookies de sesión.
- `app/core/pkce.py` — generación del par PKCE.
- `app/main.py` — rutas `/login`, `/auth/callback`, `/logout`, `/unauthorized`, `/admin`.
- `tests/test_auth.py` — schema + helpers.
- `tests/test_auth_flow.py` — flujo OAuth completo.
- `tests/test_admin.py` — panel de administración.
- `tests/test_lifespan.py` — bootstrap en startup.
- `docs/architecture/decisiones-proyecto.md` — decisiones de producto sobre usuarios autorizados.
- `app/core/config.py` — `APAP_INITIAL_ADMIN_EMAIL`, `APAP_SESSION_SECRET`.
