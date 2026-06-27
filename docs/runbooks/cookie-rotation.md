# Session Secret Rotation Runbook

## Purpose

Rotar `APAP_SESSION_SECRET` invalida TODAS las sesiones activas a la vez. Es
la unica primitiva que produce un force-logout completo y atomico, y la
remediacion operativa del PR-3 de hardening-2026-q2 para cookies pre-fix
(aquellas firmadas antes de que `/auth/callback` escribiera el flag
`is_authorized`).

El flip del default a `False` en `payload.get("is_authorized", ...)` (PR-3)
cierra la ventana contra futuras regresiones, pero NO remedia cookies
pre-fix ya en vuelo. Esas siguen siendo validas hasta su expiracion
(max_age = 7 dias) o hasta rotar el secret.

## When to rotate

- **Incidente de seguridad**: sospecha de compromiso del secret o
  revocacion urgente.
- **Rotacion programada**: politica periodica (e.g. trimestral).
- **Post-deploy de PR-3**: tras mergear el flip, rotar el secret invalida
  todas las cookies pre-fix restantes.
- **Rotacion automatica del proveedor**: si Coolify rota el secret por
  politica automatica, tratar como rotacion normal.

## Pre-deploy checklist

- [ ] Ventana de bajo trafico confirmada (fin de semana o 03:00-05:00 CET).
- [ ] Comunicacion enviada >=24h antes (email + status banner).
- [ ] Valor actual de `APAP_SESSION_SECRET` capturado (Coolify → Environment).
- [ ] Backup de `usuarios_autorizados` tomado (`pg_dump` o equivalente).
- [ ] Nuevo secret generado (comando abajo).
- [ ] Plan de rollback revisado (valor anterior accesible).

## Generate a new secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Salida: cadena de ~86 caracteres `[A-Za-z0-9_-]`. Ese es el nuevo valor.

## Deploy steps (staging first)

SIEMPRE staging antes que produccion. La rotacion es destructiva.

1. Coolify → Application → Environment → editar `APAP_SESSION_SECRET`.
2. Click "Save" + "Redeploy" (atomic, recreate strategy).
3. Esperar al contenedor; logs muestran "Application startup complete".

Verificar:

```bash
curl -i https://staging.apap.local/healthz         # 200 OK en <60s
curl -i https://staging.apap.local/                 # 302 /login
curl -i -b "apap_session=<cookie-pre-rotacion>" \
     https://staging.apap.local/                   # 302 /login
```

Monitorear logs ~5 min: la tasa de `BadSignature` debe ESPIGAR al
principio y DECAER a cero. Si no decae, detener la rotacion.

## Production

Repetir los pasos en produccion. Tiempo de disrupcion esperado: ~30s de
503 mientras los workers reinician; sesiones activas se pierden.

## Rollback

Si falla o causa problemas:

1. Coolify → Environment → restaurar `APAP_SESSION_SECRET` al valor
   anterior (capturado en el checklist).
2. Click "Redeploy".
3. Verificar con los probes del deploy step.

Efectos: las cookies firmadas con el secret ANTERIOR vuelven a
verificar. Los usuarios que se loguearon DURANTE la ventana de
rotacion deberan re-loggearse (esos cookies se firmaron con el secret
nuevo, ahora revocado). NO hay perdida de datos.

## Related

- `app/core/session.py` — `read_session` / `write_session` (la primitiva).
- `app/main.py` — middleware `protect_user_facing_routes`.
- `app/core/auth_dependencies.py` — `require_authorized_user`.
- `AGENTS.md` Rule 6 — defaults deny, not permit.
- `tests/test_session_rotation.py` — las primitivas que el runbook aprovecha.
