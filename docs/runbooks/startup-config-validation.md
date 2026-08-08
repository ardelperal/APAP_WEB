[← Back to README](../../README.md)

# startup-config-validation.md

Este runbook es el procedimiento del operador para diagnosticar y recuperar un fallo de validación de configuración de inicio. El sistema valida secretos críticos en el arranque. Aplica al issue #275.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Qué observa el operador cuando falla el despliegue | Salida de registros esperada en el fallo |
| Lista de comprobación previa | Verificaciones de secretos y banderas antes del despliegue |
| Pasos de despliegue | Generación del secreto y configuración en Coolify |
| Verificación | Señales de éxito: healthz 200, ausencia de `startup.config_invalid` |
| Reversión | Restauración de valores anteriores y advertencia de seguridad |

## Cuándo abrir este runbook

Abra este runbook en las siguientes situaciones:

- Antes del primer despliegue a producción.
- Tras rotar `APAP_SESSION_SECRET` o `APAP_INSFORGE_SERVICE_KEY`.
- Cuando un despliegue falla con `StartupConfigError` en los registros de la aplicación.
- Antes de añadir `APAP_DEBUG=true` a un entorno de producción (no lo haga).

## Qué observa el operador cuando falla el despliegue

Los registros de la aplicación (JSON, stdout) contienen una entrada como la siguiente:

```json
{
  "event": "startup.config_invalid",
  "level": "INFO",
  "_caller_fields": {
    "event": "startup.config_invalid",
    "env_var": "APAP_SESSION_SECRET",
    "reason": "placeholder"
  }
}
```

seguida de un traceback de Python que termina con:

```
app.core.config.StartupConfigError: startup config error: APAP_SESSION_SECRET
is invalid (reason=placeholder); set a real value via the env var (or
APAP_DEBUG=true to bypass in local dev)
```

La aplicación no arranca. El health probe (`/healthz`) devuelve 503 o excede el tiempo de espera.

## Lista de comprobación previa

- [ ] `APAP_INSFORGE_SERVICE_KEY` está fijado al valor real del service key de InsForge (no al valor por defecto vacío).
- [ ] `APAP_SESSION_SECRET` está fijado a una cadena aleatoria de **al menos treinta y dos caracteres**.
- [ ] `APAP_DEBUG` **no** está fijado a `true` en el entorno de producción.
- [ ] Ha probado localmente el fragmento de generación de secretos de la sección siguiente.

## Pasos de despliegue

### Generar un secreto seguro

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

El comando imprime una cadena criptográficamente aleatoria de treinta y dos caracteres (256 bits). Copie la salida y asígnela como valor de `APAP_SESSION_SECRET`.

### Configurar secretos en Coolify

1. Abra el panel de la aplicación Coolify para `apap-web`.
2. Navegue a **Environment variables**.
3. Añada o actualice `APAP_INSFORGE_SERVICE_KEY` con el service key real desde el panel de InsForge.
4. Añada o actualice `APAP_SESSION_SECRET` con el secreto generado.
5. Guarde y dispare un nuevo despliegue.

## Verificación

1. Confirme que el despliegue está sano:

    ```bash
    curl --fail --silent https://apap.romancaba.com/healthz
    ```

    Resultado esperado: `{"status":"ok","app":"APAP_WEB"}` con código de salida 0.

2. Inspeccione el registro de inicio en busca del evento de validación:

    ```bash
    # Si su agregador captura el JSON de stdout:
    grep "startup.config_invalid" /ruta/a/app.log
    # Debe mostrar: env_var="APAP_SESSION_SECRET", reason="placeholder" NO presente
    ```

3. La guarda de inicio puede verificarse localmente sin desplegar:

    ```bash
    APAP_SESSION_SECRET="dev-only-change-me-in-production" \
      APAP_INSFORGE_SERVICE_KEY="ik_real_key" \
      python -c "from app.main import create_app; create_app()"
    ```

    Resultado esperado: salida no cero con `StartupConfigError: ... reason=placeholder`.

## Reversión

Si un despliegue funcional previo utilizaba `APAP_INSFORGE_SERVICE_KEY` vacío o el placeholder `APAP_SESSION_SECRET`:

1. Restaure los valores anteriores en las variables de entorno de Coolify.
2. Redespliegue.
3. Confirme que `curl https://apap.romancaba.com/healthz` devuelve 200.

> **Advertencia**: una reversión al secreto placeholder implica que cada cookie de sesión queda firmada con un valor publicado en el repositorio. Cualquier lector del repositorio podría forjar una cookie de sesión. Priorice asignar un secreto real y redesplegar antes que revertir, salvo que exista un incidente en curso.

## Documentos relacionados

- `app/core/config.py` — `StartupConfigError` (línea 40), `_validate_secrets` y `_PLACEHOLDER_SESSION_SECRET` (línea 37).
- `app/main.py` — cableado del `lifespan`: el validador se invoca entre `configure_logging` y `InsForgeClient`.
- `docs/audits/secret-startup-validation-2026-Q3.md` — auditoría de seguridad.
- `AGENTS.md` §32.P2 — anti-patrón que este runbook cierra (valores por defecto inseguros pero que arrancan).