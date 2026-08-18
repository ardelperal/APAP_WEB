[← Back to README](../../README.md)

# auth-email-normalization.md

Este runbook cubre la deduplicación de `usuarios_autorizados` tras `fix/issue-277-278-ghost-users`. Aplica a los issues #277 y #278.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Qué observa el operador | Síntomas y SQL de detección de duplicados |
| Lista de comprobación previa | Verificaciones previas y captura de instantáneas |
| Pasos de despliegue | Procedimiento de deduplicación sobre la base de datos |
| Procedimiento de dedupe | Reglas detalladas para resolver cada grupo duplicado |
| Verificación | Señales de éxito tras la deduplicación |
| Reversión | Recuperación desde la instantánea pre-cambios |

## Cuándo abrir este runbook

Abra este runbook:

- **Después** de desplegar `fix/issue-277-278-ghost-users` en producción.
- **Antes** de la siguiente restauración de copia de seguridad (para que el código nuevo lea datos limpios).
- Cuando un usuario reporta "no puedo iniciar sesión" y sospecha que su correo se insertó dos veces con mayúsculas distintas por la ruta de código legada.
- Como pasada de higiene única: aunque ningún usuario esté roto, las filas fantasma terminarán por aflorar como glitches de renderizado duplicado en el panel de administración (el `ORDER BY` de `LIST_USERS_SQL` muestra ambas variantes). <!-- alantyle-ignore:ALAN003 -->

Esta migración es única por entorno. Tras completarse, el nuevo código impide la creación de nuevos fantasmas.

## Qué observa el operador

El comportamiento previo al arreglo permitió que `usuarios_autorizados` acumulara filas cuyas columnas `email` diferían sólo en mayúsculas. El nuevo código las trata como duplicados de la forma canónica en minúsculas, de modo que un administrador que intente volver a añadir `John@Example.com` recibirá el flash "email already authorized" aun cuando la tabla contenga `john@example.com`.

El SQL de detección de duplicados es la forma canónica de encontrar estas filas antes de que aterrice cualquier escritura nueva:

```sql
-- Encuentra filas donde el correo en minúsculas aparece más de una vez (duplicados con mezcla de mayúsculas y minúsculas)
SELECT LOWER(email) AS normalized, COUNT(*) AS n, array_agg(email) AS variants
FROM public.usuarios_autorizados
GROUP BY LOWER(email)
HAVING COUNT(*) > 1;
```

Una tabla limpia devuelve **cero filas**. Cualquier fila devuelta por esta consulta es un grupo fantasma que el nuevo código o bien silenciará o bien rechazará en la próxima adición.

Si su rol de Postgres no dispone de `array_agg`, el equivalente sin ella es:

```sql
SELECT LOWER(email) AS normalized, COUNT(*) AS n,
       string_agg(email, ' | ' ORDER BY email) AS variants
FROM public.usuarios_autorizados
GROUP BY LOWER(email)
HAVING COUNT(*) > 1;
```

## Lista de comprobación previa

- [ ] Ha leído este runbook por completo.
- [ ] Ha notificado al equipo en `#apap-ops` que la migración de deduplicación está a punto de ocurrir; registre quién está de guardia.
- [ ] Tiene el SQL de detección de duplicados anterior listo para pegar en `psql` o en la superficie de consultas de InsForge.
- [ ] Confirma que puede leer `usuarios_autorizados` con el rol del operador que ejecutará la dedupe.
- [ ] Confirma que el commit desplegado de `fix/issue-277-278-ghost-users` incluye `f41e717` (o un sucesor) — véase `git log --oneline main`.
- [ ] Decide el renombramiento objetivo de las filas perdedoras en cada grupo de duplicados (véase paso 2 del procedimiento de dedupe).
- [ ] Tome una instantánea de la tabla antes de la dedupe para que la migración sea reversible:

      ```sql
      CREATE TABLE usuarios_autorizados__pre_email_dedupe AS
      SELECT * FROM public.usuarios_autorizados;
      ```

## Pasos de despliegue

1. **Confirme que el código ya está en `main`.** Este runbook no despliega nada; `fix/issue-277-278-ghost-users` se fusionó a `main` como PR #308 y el job de despliegue en Coolify (limitado por `ci.yml`) lo recoge automáticamente. Lo primero que espera el runbook es que el pod en ejecución ya tenga el commit `f41e717` (o un sucesor). Si no, fusione primero a través de CI:

    ```bash
    git fetch origin
    git log --oneline origin/main | head -5
    ```

    El subject del commit buscado es
    `feat(auth): normalize_email helper + add_authorized_user validation + cache case-folding + admin error rendering (issue #277, #278)`.

2. **Ejecute el SQL de detección de duplicados** (de la sección anterior) contra la tabla de producción. Capture la salida como `users_ghost_groups_pre_dedupe.csv` para el rastro de auditoría.

3. **Ejecute el procedimiento de dedupe** (sección siguiente).

4. **Vuelva a ejecutar el SQL de detección de duplicados.** Debe devolver cero filas.

5. **Verifique la aplicación** (sección Verificación).

## Procedimiento de dedupe

Para cada grupo que devuelva el SQL de detección de duplicados:

1. **Ejecute el SQL de detección de duplicados anterior** y capture la lista de grupos.

2. **Para cada grupo duplicado, decida manualmente qué fila conservar.** Heurísticas habituales, en orden de preferencia:
    - La fila que el usuario realmente utiliza para iniciar sesión (su `email` vivo).
    - La fila activa más recientemente (use `fecha_alta` y cualquier evidencia de `last_login` que exponga el panel de administración).
    - La fila más antigua si ninguno de los lados tiene señal de actividad (preserva el rastro de auditoría de quién se añadió primero).

    Documente la elección en el registro de migración para que la auditoría pueda rastrearla.

3. **Actualice el correo del perdedor** a un marcador de posición único que jamás pueda coincidir con la forma canónica:

    ```sql
    -- Para cada fila perdedora en el grupo <N>
    UPDATE public.usuarios_autorizados
    SET email = 'disabled + ' || to_char(now() AT TIME ZONE 'UTC',
                                       'YYYY-MM-DD"T"HH24:MI:SS"Z"') || '@archive.local'
    WHERE id = '<loser-uuid>';
    ```

    La forma `disabled + <timestamp>@archive.local` es deliberada:
    - `disabled + ...` mantiene la fila visible para el operador como lápida.
    - El TLD `@archive.local` garantiza que ningún cliente real pueda resolverla, de modo que la caché no pueda volver a adjuntar al perdedor a un futuro usuario vivo.
    - La marca temporal desambigua si vuelve a ejecutar la dedupe.

    Si la tabla cuenta con una restricción UNIQUE sobre `email`, el marcador de posición debe ser único por fila. La marca temporal anterior ya lo garantiza.

4. **Vuelva a ejecutar el SQL de detección de duplicados.** Debe devolver **cero filas**.

5. **Tras resolver todos los duplicados, la migración normal está completa.** El nuevo código (ya desplegado) ve ahora una tabla canónica limpia. No se requieren pasos manuales posteriores.

Si un grupo duplicado representa genuinamente a dos usuarios distintos (por ejemplo, un typo creó dos cuentas reales), conserve ambas filas y renombre al perdedor a una dirección alternativa real de la que esa persona sea titular, en lugar de la forma de lápida. El nuevo código aceptará ambas filas en tanto sus formas en minúsculas sean únicas.

## Verificación

1. **El SQL de detección de duplicados devuelve cero filas:**

    ```sql
    SELECT LOWER(email) AS normalized, COUNT(*) AS n, array_agg(email) AS variants
    FROM public.usuarios_autorizados
    GROUP BY LOWER(email)
    HAVING COUNT(*) > 1;
    ```

    Resultado esperado: 0 filas.

2. **Comprobación de salud de la aplicación:**

    ```bash
    curl --fail --silent https://apap.romancaba.com/healthz
    ```

    Resultado esperado: `{"status":"ok"}` (o la carga útil existente de `/healthz`).

3. **El panel de administración renderiza sin filas fantasma.** Inicie sesión como un usuario con rol developer, navegue a `/admin` y confirme que la tabla de usuarios muestra cada correo una sola vez en su forma canónica (en minúsculas). Si alguna fila sigue mostrando mezcla de mayúsculas, la dedupe omitió un grupo — vuelva a ejecutar el SQL de detección.

4. **Prueba de re-adición:** elija una de las filas perdedoras con lápida en el panel de administración. Confirme que el formulario rechaza volver a añadir el correo original con un flash de error (`email already authorized: <canonical>`). Confirme también que re-añadir un correo nuevo para la misma persona funciona.

5. **Comprobación rápida de la caché (opcional):** en el pod en ejecución, golpee `GET /admin/users` dos veces en rápida sucesión. Inspeccione los registros de la aplicación en busca de un `auth.cache_hit` por correo por ventana TTL. `invalidate_auth` se invocó sobre el perdedor durante la dedupe, de modo que su siguiente petición debe fallar la caché y reconsultar.

## Reversión

El cambio de aplicación es **no destructivo**: PR #308 sólo cambia cómo la aplicación *lee* y *escribe* la tabla — no muta filas existentes por sí mismo. Revertir el código deja la tabla en el estado que haya dejado la dedupe.

- **Si aún no ejecutó la dedupe:** la reversión es un no-op. Revierta el despliegue y la tabla queda intacta.
- **Si ejecutó la dedupe:** los perdedores con lápida (`disabled + <timestamp>@archive.local`) son recuperables desde la instantánea `usuarios_autorizados__pre_email_dedupe` creada en la lista de comprobación previa. La recuperación consiste en un `pg_dump`/`pg_restore` de la instantánea, o un `UPDATE` por fila si la instantánea es grande. La aplicación no necesita una reversión de código en ningún caso — tolera de forma idéntica los estados antiguo y nuevo.

Si el despliegue en sí mismo debe revertirse (poco frecuente — sólo si el código nuevo regresa en una ruta no relacionada), use el flujo estándar de redespliegue en Coolify contra el HEAD previo de `main`. El lock de migración es algo que se mantiene durante la dedupe (instantánea en la lista de comprobación previa), no durante el despliegue de código.

## Documentos relacionados

- `app/core/auth_helpers.py` — `normalize_email` (línea 14) y `validate_email_format` (única fuente de verdad, AGENTS.md §4 + §25).
- `app/core/auth.py` — pre-chequeo `add_authorized_user` y mapeo de `InsForgeError` como defensa en profundidad (issue #277) y fontanería `normalize_email` (issue #278).
- `app/core/auth_cache.py` — barrido de variantes de mayúsculas de `invalidate_auth` (`_case_variants`) y clave de caché con case-folding (issue #278).
- `app/core/admin_helpers.py` — auxiliares de mensaje flash `_pop_flash` y `_redirect_with_flash` (issue #277).
- `app/main.py` — handler `admin_add_user` con `_add_user_or_error` y la ruta de renderizado tras éxito.
- `tests/test_auth.py`, `tests/test_auth_cache.py`, `tests/test_auth_helpers.py`, `tests/test_admin.py` — red de seguridad TDD.
- `docs/audits/ghost-users-audit-2026-Q3.md` — auditoría de defectos para #277 + #278.
- `docs/runbooks/auth-cache-multi-worker.md` — runbook complementario para la semántica de caché con ámbito de worker con la que interactúa el issue #278.
- Issues: #277 (manejo parcial de excepciones — §32.P4), #278 (cegamiento del perímetro — ejemplo §32.P1).
- `AGENTS.md` §4 (una única fuente de verdad por concepto de dominio), §12 (requisito de documento de auditoría), §13 (requisito de runbook), §25 (sin funciones auxiliares duplicadas), §32.P1 (cegamiento del perímetro), §32.P4 (manejo parcial de excepciones).