[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Runbook — Hardening de la base de datos de producción (`#1290`, `#1291`)

Este runbook es el plan ejecutable por el operador para llevar la base de datos de producción al estado objetivo: recurso gestionado (o, en su defecto, contenedor declarado), autenticado (`scram-sha-256`), sin puerto publicado en el host, con healthcheck y política de reinicio, sin pérdida de datos. Es la remediación de los issues #1290 (incidente) y #1291 (hallazgo de seguridad). El alcance es la ventana operativa de corte; no toca código de aplicación.

**Audience**: operador con acceso admin al panel de Coolify y SSH al VPS Oracle.

**Cuándo abrir este runbook**:

- Cuando se decida ejecutar la remediación del incidente 2026-10-05/2026-10-09 (issues #1290 y #1291).
- Antes de cualquier intervención planeada sobre `apap-pg-test` que pueda tocar su volumen de datos.
- Antes del siguiente deploy que dependa de la base de datos de producción.

## What this is / is not

### What this is

| Es | Evidencia en este repo |
|---|---|
| El plan de remediación que lleva la base de datos de producción a estado gestionado, autenticado, sin puerto publicado, con healthcheck y política de reinicio. | Issues #1290 y #1291; estado previo documentado en `docs/postmortems/2026-10-05-produccion-caida-4-dias.md`. |
| Un procedimiento ejecutable por otro operador, con backup previo, dos rutas alternativas (preferida y fallback) y rollback explícito. | Secciones «Copia de seguridad previa», «Procedimiento preferido», «Procedimiento alternativo (fallback)» y «Reversión». |
| Compatible con cero pérdida de datos: backup `pg_dump` verificado antes del corte, volumen original intacto durante toda la ventana. | Sección «Copia de seguridad previa» + invariantes abajo. |

### What this is not

| No es | Use este límite |
|---|---|
| Una guía de rollback de despliegue | Ver [`deploy-rollback.md`](deploy-rollback.md). |
| Una guía de monitorización externa | Este runbook asume monitorización externa o la abre como pendiente (issue por abrir). |
| Una guía de migración de esquema | La base de datos destino recibe un `pg_dump`; no se toca el modelo de datos. |
| Una guía de despliegue inicial | Ver [`operator-deploy-2026.md`](operator-deploy-2026.md) para primer deploy y rotación. |

## Core invariants

- **Cero pérdida de datos.** El volumen `dcd09a17df1d9b437fa35d008fd4c45108c5a8f89088801acec79c1daf918c89` del contenedor actual no se modifica durante toda la ventana. Antes del primer paso, existe una copia `pg_dump` verificada.
- **El DSN de producción apunta a un nombre que el orquestador conoce.** `APAP_LOCAL_DB_URL` cambia a un DSN autenticado contra un recurso Coolify o un contenedor declarado, nunca a una dirección efímera.
- **El puerto `5432` no queda publicado en `0.0.0.0` después del corte.** El binding `0.0.0.0:5433` desaparece (proba #1291).
- **`POSTGRES_HOST_AUTH_METHOD` deja de ser `trust`.** El destino usa `scram-sha-256` con contraseña real; `pg_hba.conf` efectiva no termina en `host all all all trust` (proba #1291).
- **El healthcheck de la base de datos no es nulo tras el corte.** Una sonda `pg_isready` (o equivalente del orquestador) debe devolver 0 dentro del healthcheck configurado.
- **La fila `usuarios_autorizados` con `e2e@apap.local` / `developer` / `activo=true` se preserva** a través del `pg_dump` y el restore (la cuenta que el runbook de release necesita).

## Procedimiento

### Copia de seguridad previa

Antes de cualquier paso siguiente, genere y verifique el backup:

```bash
docker exec apap-pg-test pg_dump -U postgres -d postgres -Fc \
  -f /tmp/apap-pre-hardening.dump

docker cp apap-pg-test:/tmp/apap-pre-hardening.dump \
  /home/ubuntu/backups/apap-pre-hardening-$(date -u +%Y%m%dT%H%M%SZ).dump
```

Verifique que el archivo se generó con tamaño distinto de cero y que el volumen `dcd09a17df1d9b437fa35d008fd4c45108c5a8f89088801acec79c1daf918c89` no se modifica durante toda la ventana (no se ejecutan comandos que lo toquen).

### Procedimiento preferido — recurso Coolify gestionado

1. **Confirme que la instancia de Coolify puede crear un recurso de base de datos Postgres gestionado** asociado a una aplicación (pregunta abierta: verifique en el panel de su instancia; el comportamiento exacto depende de la versión). Si la instancia no lo soporta, vaya a «Procedimiento alternativo (fallback)».
2. **Cree el recurso de base de datos Postgres gestionado en Coolify, asociado a la aplicación `apap-web`.** Anote el DSN, el usuario y la contraseña que el panel genere.
3. **Restaure el `pg_dump` en la base de datos nueva** (mecanismo propio del panel, o `pg_restore` contra el endpoint temporal que el panel exponga).
4. **En el panel de la aplicación `apap-web`, actualice `APAP_LOCAL_DB_URL`** al DSN nuevo, autenticado (`scram-sha-256`). La conectividad esperada es por la red `coolify`; no publique el puerto.
5. **Dispare un redespliegue** desde el panel de Coolify, o vía `python scripts/coolify_webhook.py` (ver [`operator-deploy-2026.md`](operator-deploy-2026.md)).
6. **Verifique la salud** con `curl --fail --silent https://apap.romancaba.com/healthz` y la revisión esperada.
7. **Solo cuando la verificación sea correcta, detenga `apap-pg-test`** (`docker stop apap-pg-test`). Conserve su volumen durante el periodo de retención declarado (pregunta abierta: número de días, a definir por el operador).
8. **Si el contenedor original publicaba `0.0.0.0:5433`, revoque ese binding** en la configuración que lo creó.

### Procedimiento alternativo (fallback) — contenedor declarado

Si Coolify no soporta crear un recurso de base de datos Postgres gestionado, recree `apap-pg-test` como contenedor declarado fuera del estado heredado. Primero detenga y elimine el contenedor antiguo (el volumen se conserva intacto):

```bash
docker stop apap-pg-test || true
docker rm apap-pg-test || true
```

Después cree el contenedor nuevo:

```bash
docker run -d \
  --name apap-pg-test \
  --network coolify \
  --restart unless-stopped \
  -e POSTGRES_PASSWORD='<contraseña-aleatoria-≥-32-chars>' \
  -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
  -v dcd09a17df1d9b437fa35d008fd4c45108c5a8f89088801acec79c1daf918c89:/var/lib/postgresql/data \
  --health-cmd "pg_isready -U postgres" \
  --health-interval 30s \
  --health-timeout 5s \
  --health-retries 3 \
  postgres:16-alpine
```

Notas operativas:

- El puerto no se publica (`-p 5433:5432` queda explícitamente omitido).
- Sustituya `<contraseña-aleatoria-≥-32-chars>` por una cadena criptográficamente aleatoria, p. ej. `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- El volumen existente se reutiliza; sus datos se conservan.
- **El rol `postgres` no tiene contraseña en el cluster heredado.** `POSTGRES_PASSWORD` y `POSTGRES_HOST_AUTH_METHOD` solo se aplican al inicializar un volumen vacío, así que al reutilizar el volumen el cluster sigue con la `pg_hba.conf` en `trust` y sin contraseña para el rol. Antes de continuar, ejecute dentro del contenedor nuevo:

  ```bash
  docker exec -it apap-pg-test psql -U postgres -d postgres -c \
    "ALTER ROLE postgres PASSWORD '<la-misma-contraseña>';"
  ```

  y después edite `pg_hba.conf` del cluster (`host all all all scram-sha-256` en lugar de la última línea `trust`) y recargue con `SELECT pg_reload_conf();`. Si no hace esto, la verificación 3 de «Verificación» seguirá fallando y —peor— el DSN nuevo no autenticará nada: es exactamente el estado que el hallazgo #1291 describe.

Tras la creación:

1. **En el panel de Coolify, actualice `APAP_LOCAL_DB_URL`** al DSN nuevo con la contraseña real.
2. **Dispare un redespliegue** desde el panel.
3. **Verifique la salud** con `curl --fail --silent https://apap.romancaba.com/healthz` y la revisión esperada.
4. **Tras la verificación, confirme que el binding `0.0.0.0:5433` ya no existe** en la configuración que lo creaba.

### Ventana y orden recomendado

- La creación del recurso nuevo (Coolify o contenedor declarado) y la restauración del dump pueden ocurrir mientras la base de datos actual sigue dando servicio.
- El corte en sí es el cambio de `APAP_LOCAL_DB_URL` en Coolify más un reinicio de la aplicación (segundos).
- Aun así, se recomienda una ventana de bajo tráfico. La duración total estimada (con verificación) es del orden de una hora.

## Verificación

Tras el corte, valide las tres probas negativas del hallazgo #1291 y la salud de la aplicación:

1. **Sin acceso cross-project sin contraseña.** El contenedor `coolify-db` (u otro proyecto en la red `coolify`) ya no debe poder conectar al Postgres de `apap-web` sin contraseña:

    ```bash
    docker exec coolify-db psql "postgresql://postgres@apap-pg-test:5432/postgres" -tAc "select current_user"
    ```

    Debe fallar (error de autenticación), no devolver `postgres`.

2. **Sin acceso por el puerto publicado del host.** El puerto `5433` del VPS ya no debe responder:

    ```bash
    docker run --rm --network host postgres:16-alpine \
      psql "postgresql://postgres@127.0.0.1:5433/postgres"
    ```

    Debe fallar (connection refused o timeout), no conectar.

3. **`pg_hba.conf` sin líneas `trust`.** Lea la configuración efectiva del cluster:

    ```bash
    docker exec <contenedor-postgres> sh -c \
      "grep -vE '^#|^$' \$(psql -U postgres -tAc 'show hba_file')"
    ```

    Ninguna línea debe terminar en `trust` para conexiones `host`.

4. **Healthcheck no nulo.** Confirme que el healthcheck del contenedor (o del recurso Coolify) está configurado y reporta `healthy`.

5. **Aplicación sana y revisión correcta.** Confirme:

    ```bash
    curl --fail --silent https://apap.romancaba.com/healthz
    ```

    Salida esperada: `200` con cuerpo que incluye `"revision":"<sha-esperado>"`, y la fila `usuarios_autorizados` con `e2e@apap.local` / `developer` / `activo=true` preservada (consultable desde la propia aplicación).

6. **Estado residual del gate e2e.** `release/smoke-production` para `c71c1bb4eb5656f74db6a66b56c79a622620f89e` está `success`; `release/e2e-production` para ese mismo SHA está `pending`. Decisión del operador: registrar `skipped:<reason>` para ese SHA ya superado, o ejecutar el gate e2e completo de [`e2e-production.md`](e2e-production.md) contra él. Referencia: épica #909.

## Reversión

Si la verificación falla o la aplicación no arranca con el nuevo backend:

1. **Repunte `APAP_LOCAL_DB_URL`** en el panel de Coolify al DSN anterior (`postgresql://postgres:***@apap-pg-test:5432/postgres`).
2. **Arranque `apap-pg-test`** si está detenido:

    ```bash
    docker start apap-pg-test
    ```

3. **Dispare un redespliegue** desde Coolify.
4. **Verifique `/healthz`** (debe volver a 200 con la revisión anterior).

El volumen original no se modificó durante la ventana, por lo que la reversión recupera el estado previo al corte. Si en el «Procedimiento alternativo (fallback)» se detuvo y eliminó el contenedor, la reversión recrea el contenedor con el mismo nombre y volumen (`apap-pg-test` arrancado por `docker start` recupera el estado si no se eliminó el contenedor; si se eliminó, `docker run` con los flags originales y el mismo volumen restaura el cluster).

## Anti-patrones

| Síntoma | Por qué importa | Use en su lugar |
|---|---|---|
| Crear el nuevo Postgres con `POSTGRES_HOST_AUTH_METHOD=trust` para «acelerar» la migración | Reproduce exactamente el hallazgo #1291 | Crearlo con `scram-sha-256` y contraseña real desde el primer arranque |
| Publicar el puerto (`-p 5433:5432`) en el contenedor nuevo | Reproduce el hallazgo de exposición de #1291 | Crearlo en la red `coolify`, sin `-p` |
| Restaurar el `pg_dump` y luego tocar el esquema del origen | Invalida la base de la reversión | Restaurar contra el destino y no tocar el origen hasta después de la verificación |
| Eliminar el volumen `dcd09a17df1d9b437fa35d008fd4c45108c5a8f89088801acec79c1daf918c89` antes de la verificación | Pérdida irreversible del estado previo | Conservar el volumen durante el periodo de retención declarado |
| Ejecutar el corte en una ventana de tráfico alto para «aprovechar» | Aumenta el coste de cualquier fallo | Programar la ventana en bajo tráfico |

## Contributor checklist

- [ ] `pg_dump` generado y verificado (tamaño distinto de cero) antes del primer paso.
- [ ] Recurso Coolify o contenedor nuevo creado con `scram-sha-256`, sin `-p`, con healthcheck y `--restart unless-stopped`.
- [ ] `APAP_LOCAL_DB_URL` actualizado en Coolify y redespliegue disparado por el mecanismo habitual.
- [ ] Las tres probas negativas de #1291 fallan tras el corte (cross-project, puerto publicado, `trust` en `pg_hba.conf`).
- [ ] Healthcheck del contenedor o recurso Coolify configurado y reporta `healthy`.
- [ ] `/healthz` devuelve 200 con la revisión esperada y la fila `e2e@apap.local` preservada.
- [ ] Decisión registrada sobre `release/e2e-production` para `c71c1bb4eb5656f74db6a66b56c79a622620f89e` (bypass o ejecución completa).
- [ ] Plan de conservación del volumen original declarado por escrito (pregunta abierta resuelta).

## Navigation

Previous: [`e2e-production.md`](e2e-production.md) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)