[← Back to README](../../README.md)

# auth-cache-multi-worker.md

Este runbook cubre la evolución de la caché de autorización entre un worker único y multi-worker. Sólo se soporta `in_process`; cualquier otro valor falla en el arranque. Aplica al issue #287.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Estado actual de producción | Tabla de propiedades confirmadas del despliegue en Coolify |
| Lista de comprobación previa | Verificaciones de configuración previas al escalado |
| Pasos de despliegue | Procedimiento para uno o varios workers/replicas |
| Verificación | Señales de éxito: healthz, procesos y registros de arranque |
| Reversión | Vuelta al worker único con TTL positiva |

## Cuándo abrir este runbook

Abra este runbook en las siguientes situaciones:

- Antes de añadir `--workers N` con `N > 1`.
- Antes de incrementar el número de replicas de la aplicación Coolify por encima de uno.
- Cuando un usuario desactivado permanece autorizado en otro worker.
- Cuando se modifiquen `APAP_AUTH_CACHE_TTL_SECONDS` o `APAP_AUTH_CACHE_BACKEND`.

## Estado actual de producción

Confirmado el 2026-07-25 a partir de los detalles de la aplicación en Coolify y del Dockerfile del repositorio:

| Propiedad | Valor confirmado |
|---|---|
| Aplicación en Coolify | `apap-web` |
| Build pack | `dockerfile` |
| Override de `start-command` en Coolify | ninguno (`start_command=null`) |
| Replicas de la aplicación | 1 (`swarm_replicas=1`) |
| Comando de la imagen | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Argumento `--workers` de Uvicorn | ausente |
| Alcance efectivo de la caché de auth hoy | un proceso, una caché |

El despliegue actual, por tanto, no requiere invalidación entre workers. `invalidate_auth(email)` invalida inmediatamente la única caché local al proceso. La semántica sigue siendo local al worker: añadir workers o replicas crea cachés independientes, cada una capaz de retener un veredicto hasta que expire su TTL.

## Lista de comprobación previa

- [ ] Confirme que la aplicación Coolify en vivo sigue teniendo una sola replica.
- [ ] Confirme que ningún override de `start-command` añade `--workers`.
- [ ] Confirme que `APAP_AUTH_CACHE_BACKEND` no está fijado o es exactamente `in_process`.
- [ ] Si el destino tiene varios workers o replicas, fije `APAP_AUTH_CACHE_TTL_SECONDS=0` antes de escalar.
- [ ] Registre el número previo de workers, el número previo de replicas, el valor previo del backend y el TTL previo.
- [ ] Confirme que el aumento previsto de consultas resulta aceptable cuando el TTL es cero: una consulta `SELECT` de autorización por cada petición autenticada.

## Pasos de despliegue

### Mantener el despliegue actual de un solo worker

1. Deje el número de replicas en Coolify en uno.
2. Deje el override de `start-command` vacío para que el `CMD` del Dockerfile conserve su autoridad.
3. Retire `APAP_AUTH_CACHE_BACKEND` o fíjelo en `in_process`.
4. Mantenga el TTL elegido (300 por defecto).
5. Redespliegue y complete la verificación siguiente.

### Escalar a múltiples workers o replicas

1. Fije `APAP_AUTH_CACHE_TTL_SECONDS=0` en Coolify y guárdelo.
2. Asegúrese de que `APAP_AUTH_CACHE_BACKEND` no está fijado o vale `in_process`.
3. Redespliegue con TTL cero mientras la aplicación sigue teniendo un solo worker.
4. Incremente el número de workers de Uvicorn o el número de replicas de Coolify.
5. Redespliegue de nuevo y complete la verificación siguiente.

El TTL cero invalida cada consulta a la caché, de modo que cada petición autenticada consulta `usuarios_autorizados`. Esto preserva la revocación inmediata entre workers independientes sin reivindicar invalidación para todo el clúster.

## Verificación

1. Confirme que el despliegue está sano:

    ```bash
    curl --fail --silent https://apap.romancaba.com/healthz
    ```

2. En Coolify, confirme que el estado de la aplicación es `running:healthy`, que el número previsto de replicas está activo y que el override de `start-command` coincide con el plan.
3. Dentro del contenedor de la aplicación, inspeccione los argumentos del proceso Uvicorn:

    ```bash
    ps -ef | grep '[u]vicorn'
    ```

    Para el despliegue actual, espere un único proceso Uvicorn sin `--workers`.

4. Confirme que los registros de arranque no contienen errores de validación de Pydantic para `auth_cache_backend`.
5. Para un despliegue multi-worker, desactive un usuario de prueba y envíe peticiones autenticadas a través de conexiones repetidas con balanceo de carga. Con TTL cero, cada petición posterior a la desactivación debe denegarse tras finalizar la petición en vuelo.

Una guarda de arranque local puede comprobarse sin desplegar:

```bash
APAP_AUTH_CACHE_BACKEND=redis python -c "from app.core.config import get_settings; get_settings()"
```

Resultado esperado: salida no cero con un error de validación que nombre `auth_cache_backend`. La aplicación no debe arrancar y luego fallar con `NotImplementedError` en una petición.

## Reversión

Si el TTL cero provoca una carga de consultas inaceptable:

1. Reduzca primero el despliegue a un solo worker de Uvicorn y a una sola replica de Coolify.
2. Restaure el valor positivo previo de `APAP_AUTH_CACHE_TTL_SECONDS`.
3. Asegúrese de que `APAP_AUTH_CACHE_BACKEND` sigue sin fijarse o vale `in_process`.
4. Redespliegue.
5. Vuelva a ejecutar las comprobaciones de salud y de número de procesos.

No restaure un TTL positivo mientras varios workers permanezcan activos, salvo que la ventana de obsolescencia por worker se acepte explícitamente. No existe estado persistente de caché que limpiar; cada despliegue arranca la caché local al proceso vacía.

## Documentos relacionados

- `app/core/auth_cache.py` — caché local al worker, guarda de generación y fachadas.
- `app/core/config.py` — TTL y guarda de compatibilidad `in_process`.
- `AGENTS.md` §29 — contrato de despliegue de la caché de autorización.
- `docs/audits/auth-cache-in-process-audit-2026-Q3.md` — auditoría de seguridad del #287.
- `tests/test_auth_cache_backend.py` — contratos de backend y de configuración.
- `tests/test_lifespan.py` — rechazo en arranque para configuración Redis obsoleta.