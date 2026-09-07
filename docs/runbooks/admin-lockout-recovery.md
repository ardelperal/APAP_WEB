[← Back to README](../../README.md)

# admin-lockout-recovery.md

Este runbook es el procedimiento del operador para recuperar una tabla `usuarios_autorizados` sin desarrolladores activos. Aplica al issue #279.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Qué observa el operador | Síntomas visibles en la aplicación ante la falta de desarrolladores |
| Lista de comprobación previa | Verificaciones previas a tocar la base de datos |
| Pasos de despliegue | Inserción manual del desarrollador de recuperación |
| Verificación | Señales de éxito: fila presente, panel accesible, guarda activa |
| Reversión | Corrección puntual de email o rol en la fila insertada |

## Cuándo abrir este runbook

Abra este runbook cuando los datos locales sean lo único que se interponga entre los operadores y una tabla `usuarios_autorizados` sin desarrolladores:

- El único desarrollador activo se ha desactivado (por ejemplo, clic accidental en el panel de administración antes de que el arreglo llegara a producción).
- `ensure_schema_and_seed` ya no re-siembra porque la fila de desarrollador inactiva satisface el antiguo predicado `WHERE rol = 'developer'` (el único caso que el nuevo filtro `activo = true` aborda, pero del que **no recupera**). <!-- alantyle-ignore:ALAN003 -->
- La base de datos es accesible, pero `GET /admin` devuelve 403 o redirige a `/unauthorized` para cada correo de operador.
- La variable de entorno `APAP_INITIAL_ADMIN_EMAIL` está fijada en Coolify pero ninguna fila de desarrollador activo existe con ese correo.

No use este runbook para problemas a nivel de aplicación (CSRF, sesión, OAuth): esos cuentan con sus propios runbooks.

## Qué observa el operador

Dos síntomas, ambos provocados por la misma causa raíz (ningún desarrollador activo):

1. **En `/admin`**: el botón de desactivación aparece en gris para el último desarrollador (la guarda `DEACTIVATE_USER_SQL` de este PR). Una vez que el último desarrollador desaparece, la página deja de renderizarse para cualquier operador porque `require_developer_user_redirect` rechaza todo rol distinto de `developer`, y `GET /admin` redirige a `/unauthorized`.
2. **En toda la aplicación**: los puntos de acceso exclusivos para desarrolladores (panel de administración, asignación de roles, todo lo protegido por `require_developer_user_redirect`) resultan inalcanzables. Los lectores y administradores conservan su acceso; sólo se pierden las rutas restringidas al rol `developer`.

## Lista de comprobación previa

Antes de tocar la base de datos, confirme lo siguiente:

- [ ] Ha leído este runbook por completo.
- [ ] Dispone del valor de `APAP_INITIAL_ADMIN_EMAIL` (el correo del operador configurado en Coolify).
- [ ] Tiene acceso administrativo de shell a LocalBackend/Postgres (mediante las herramientas MCP `run-raw-sql`/`get-table-schema`, o una conexión `psql` directa con las credenciales almacenadas en Coolify).
- [ ] El despliegue Coolify en vivo está en `main` y es accesible. El SQL de recuperación apunta a la misma base de datos con la que habla la aplicación en ejecución.
- [ ] Ningún otro operador ejecuta un bootstrap paralelo (no debe ocurrir: el arranque está limitado por el filtro de desarrollador activo; aún así, conviene confirmar que el contenedor no está en medio de un reinicio).
- [ ] Ha tomado una copia de seguridad de la tabla `usuarios_autorizados` antes de ejecutar el INSERT manual (`SELECT * FROM public.usuarios_autorizados` a un archivo). <!-- alantyle-ignore:ALAN003 -->

## Pasos de despliegue

El arreglo incluido en este PR es la salvaguarda preventiva. El SQL manual siguiente es el camino del operador para una base de datos ya bloqueada. La redeploy no forma parte de la recuperación: el código en producción sólo necesita ejecutarse con la nueva `DEACTIVATE_USER_SQL` si desea que la guarda siga disparándose tras la recuperación (lo hará, dado que el nuevo código viaja en `main` y el INSERT manual ocurre contra la misma tabla).

No se requiere redespliegue ni reinicio para que el INSERT manual sea visible. La siguiente petición autenticada desde el desarrollador recuperado verá la nueva fila; el fallo de la caché de autorización forma parte del camino normal de invalidación (issue #143, §29).

### SQL de recuperación manual

Conéctese a la base de datos Postgres de producción (LocalBackend) y ejecute el siguiente INSERT. El esquema utiliza **nombres de columna en castellano**: `anadido_por` (no `added_by`), `fecha_alta` (no `created_at`). Usar el nombre de columna equivocado hará que el INSERT introduzca silenciosamente `NULL` o que la sentencia falle.

```sql
INSERT INTO public.usuarios_autorizados
  (id, email, rol, activo, anadido_por, fecha_alta)
VALUES
  (gen_random_uuid(), '<APAP_INITIAL_ADMIN_EMAIL>', 'developer', true, 'recovery', now());
```

Sustituciones:

- `<APAP_INITIAL_ADMIN_EMAIL>` — reemplace por el valor de `APAP_INITIAL_ADMIN_EMAIL` desde Coolify. Mantenga el correo exacto (sensible a mayúsculas en el SQL aunque la aplicación normalice en lectura — issue #278 — así que cópielo tal cual desde la variable de entorno).

Tras el INSERT, **reinicie la aplicación** para que el bootstrap reevalúe. Ambas condiciones importan:

- El nuevo filtro de `SEED_ADMIN_SQL` (subconsulta `activo = true`) garantiza que el desarrollador activo insertado no provoque un seed duplicado.
- Si el nuevo desarrollador es el único desarrollador activo y el operador lo desactiva más adelante, el bootstrap re-sembra sólo si la fila inactiva se elimina (la fila dormida sigue en la tabla). El camino de recuperación no es para uso repetido: es el descongelador de un solo paso.

El re-seed del bootstrap se omite automáticamente cuando existe cualquier desarrollador activo, por lo que el reinicio es seguro de ejecutar varias veces.

## Verificación

1. Confirme que la fila recuperada está presente:

    ```sql
    SELECT id, email, rol, activo, anadido_por, fecha_alta
      FROM public.usuarios_autorizados
     WHERE email = '<APAP_INITIAL_ADMIN_EMAIL>';
    ```

    Esperado: una fila con `rol = 'developer'`, `activo = true`, `anadido_por = 'recovery'`.

2. Acceda al panel de administración como el desarrollador recuperado:

    ```bash
    curl --fail --silent https://apap.romancaba.com/admin
    ```

    Esperado: 200 OK con la tabla de usuarios renderizada. Si devuelve 302 hacia `/unauthorized`, la cookie de sesión no se emite o la normalización del correo diverge del valor en base de datos (issue #278 — vuelva a comprobar el correo contra la forma canónica).

3. Confirme que la guarda sigue activa: intente desactivar a otro desarrollador con `actor = recuperado`. La interfaz debe mostrar el error flash `cannot deactivate the last active developer` porque la fila recuperada es el único desarrollador activo (`/admin/users/<id>/deactivate` devuelve 200 con el mensaje de error, no 302).

4. Añada un segundo desarrollador desde `/admin` y desactive uno de los dos. La desactivación debeucceedir y el desarrollador restante debe seguir accediendo a `/admin`. Esto demuestra que la guarda distingue correctamente entre "último desarrollador" y "no-último desarrollador".

5. Inspeccione los registros de la aplicación en busca del evento de desactivación — `log_safe` emite `auth.user.deactivated` sin PII (la lista de redacción del issue #287 cubre el campo `email`).

## Reversión

No existe camino de reversión. El SQL de recuperación es puramente aditivo (inserta una fila de desarrollador nueva). El nuevo desarrollador puede desactivarse después por un desarrollador existente, devolviendo el sistema a "sólo existe un desarrollador" pero nunca a "no existe ningún desarrollador".

Si el INSERT se ejecutó con un correo equivocado:

1. Ejecute un UPDATE dirigido para corregir el correo:

    ```sql
    UPDATE public.usuarios_autorizados
       SET email = '<correct_email>'
     WHERE anadido_por = 'recovery' AND activo = true;
    ```

2. Vuelva a ejecutar el bloque de verificación anterior.

Si el INSERT se ejecutó con un rol equivocado (por ejemplo, `reader` en lugar de `developer`):

1. Haga UPDATE de la fila existente a `rol = 'developer'` — no inserte una segunda fila de recuperación:

    ```sql
    UPDATE public.usuarios_autorizados
       SET rol = 'developer'
     WHERE anadido_por = 'recovery' AND activo = true;
    ```

2. Vuelva a verificar.

## Documentos relacionados

- `app/core/auth.py` — `DEACTIVATE_USER_SQL`, `SEED_ADMIN_SQL`, `deactivate_authorized_user`, `ensure_schema_and_seed` (migrated: las consultas SQL residen ahora en `app/core/adapters/local-backend/auth_local_backend_queries.py`; el contrato público no cambia).
- `app/main.py` — ruta `admin_deactivate_user` que captura `ValueError` y re-renderiza `admin.html` (issue #279).
- `templates/admin.html` — renderizado del mensaje flash para `error_message`.
- `tests/test_auth.py` — cinco casos nuevos: bloqueo del último desarrollador, autodesactivación OK, SEED cuando sólo existen desarrolladores inactivos, ámbito de rol (reader/admin/key_user no afectados).
- `tests/test_admin.py` — un caso nuevo: la ruta renderiza el mensaje flash cuando se dispara la desactivación del último desarrollador.
- `AGENTS.md` §13 — obligación de runbook para caminos de recuperación del operador.
- `AGENTS.md` §6 — seguridad por defecto restrictivo.
- `AGENTS.md` §32.P1 — cegamiento del perímetro (la guarda reside en la frontera SQL; la interfaz expone el camino de migración).
- `app/core/auth_cache.py` — `invalidate_auth(email)` invocado tras una desactivación exitosa (issue #143, §29).