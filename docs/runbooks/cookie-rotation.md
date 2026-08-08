[← Back to README](../../README.md)

# cookie-rotation.md

Este runbook cubre la rotación de `APAP_SESSION_SECRET`. La rotación invalida todas las sesiones activas a la vez y es la única primitiva de cierre completo y atómico. Aplica al PR-3.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican una rotación del secreto |
| Lista de comprobación previa | Restricciones operativas antes de ejecutar la rotación |
| Pasos de despliegue | Procedimiento en staging y producción con verificación inmediata |
| Verificación | Señales de éxito: 200 en healthz, 302 con cookie pre-rotación, caída de `BadSignature` |
| Reversión | Restauración del valor anterior del secreto |

## Cuándo abrir este runbook

Abra este runbook en las siguientes situaciones:

- **Incidente de seguridad**: sospecha de compromiso del secreto o revocación urgente.
- **Rotación programada**: política periódica (por ejemplo, trimestral).
- **Post-fusión del PR-3**: tras fusionar el cambio de `payload.get("is_authorized", ...)` al valor `False`, la rotación invalida las cookies pre-fix que aún estén vigentes.
- **Rotación automática del proveedor**: si Coolify rota el secreto por política automática, trátela como una rotación normal.

## Lista de comprobación previa

Antes de ejecutar la rotación, verifique los siguientes puntos:

- [ ] Ventana de bajo tráfico confirmada (fin de semana o 03:00–05:00 CET).
- [ ] Comunicación enviada con al menos veinticuatro horas de antelación (correo electrónico y banner de estado).
- [ ] Valor actual de `APAP_SESSION_SECRET` capturado desde Coolify → Environment.
- [ ] Copia de seguridad de `usuarios_autorizados` realizada (`pg_dump` o equivalente).
- [ ] Nuevo secreto generado con el comando de la sección siguiente.
- [ ] Plan de reversión revisado: el valor anterior debe permanecer accesible.

## Pasos de despliegue

### Generar un nuevo secreto

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

La salida es una cadena de aproximadamente ochenta y seis caracteres del alfabeto `[A-Za-z0-9_-]`. Ese es el nuevo valor.

### Despliegue en staging primero

**Ejecute siempre staging antes que producción.** La rotación es destructiva.

1. Coolify → Application → Environment → editar `APAP_SESSION_SECRET`.
2. Pulse **Save** y **Redeploy** (estrategia atómica de recreación).
3. Espere al contenedor; los registros muestran `Application startup complete`.

Verifique inmediatamente:

```bash
curl -i https://staging.apap.local/healthz         # 200 OK en menos de 60 s
curl -i https://staging.apap.local/                 # 302 /login
curl -i -b "apap_session=<cookie-pre-rotacion>" \
     https://staging.apap.local/                   # 302 /login
```

Monitorice los registros durante cinco minutos. La tasa de `BadSignature` debe **picar** al principio y **decaer** a cero. Si no decae, detenga la rotación.

### Despliegue en producción

Repita los pasos anteriores en producción. Tiempo de disrupción esperado: aproximadamente treinta segundos de 503 mientras los workers se reinician. Las sesiones activas se pierden.

## Verificación

Tras la rotación, valide lo siguiente:

1. El endpoint de salud responde 200:

    ```bash
    curl --fail --silent https://apap.romancaba.com/healthz
    ```

    Resultado esperado: `{"status":"ok","app":"APAP_WEB"}` con código de salida 0.

2. La inspección de los registros de inicio muestra el evento de validación:

    ```bash
    grep "startup.config_invalid" /ruta/a/app.log
    ```

    El evento `startup.config_invalid` con `env_var="APAP_SESSION_SECRET"` y `reason="placeholder"` **no debe aparecer**.

3. La monitorización durante cinco minutos tras el reinicio muestra la curva esperada de `BadSignature` (pico inicial seguido de caída a cero).

## Reversión

Si la rotación falla o causa problemas:

1. Coolify → Environment → restaurar `APAP_SESSION_SECRET` al valor anterior capturado en la lista de comprobación previa.
2. Pulse **Redeploy**.
3. Verifique con los mismos probes de la sección de despliegue.

Efectos de la reversión: las cookies firmadas con el secreto anterior vuelven a verificar correctamente. Los usuarios que iniciaron sesión **durante** la ventana de rotación deberán volver a iniciar sesión, ya que esas cookies se firmaron con el secreto nuevo, ahora revocado. No se produce pérdida de datos.

## Documentos relacionados

- `app/core/session.py` — primitivas `read_session` y `write_session`.
- `app/main.py` — middleware `protect_user_facing_routes`.
- `app/core/auth_dependencies.py` — `require_authorized_user`.
- `AGENTS.md` §6 — seguridad por defecto restrictivo.
- `tests/test_session_rotation.py` — primitivas que el runbook aprovecha.