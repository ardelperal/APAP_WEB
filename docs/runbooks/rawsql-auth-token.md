[← Volver a la guía del código](../CODEBASE-GUIDE.md)

# Token del endpoint raw SQL

El endpoint `POST /api/database/advance/rawsql` ejecuta SQL con los permisos del
proceso LocalBackend. Solo se monta en `app.core.local_backend.app:create_app`;
`app.main` no expone esta ruta ni necesita su secreto.

## Contrato operativo

- LocalBackend exige `APAP_RAWSQL_AUTH_TOKEN` al arrancar.
- El token debe tener al menos 32 caracteres.
- Cada petición debe enviar `Authorization: Bearer <token>`.
- Un token ausente, mal formado o incorrecto recibe el mismo `401` genérico.
- La comparación usa `hmac.compare_digest` y precede a cualquier consulta SQL.

La CLI de migración usa `LocalPostgresExecutor` directamente. No necesita este
token mientras no invoque el endpoint HTTP.

Los verificadores automáticos de fallback que levantan LocalBackend generan un
token efímero y lo comparten únicamente entre sus subprocesos. No requieren
provisionar un secreto persistente en CI.

## Provisionar

Genere el secreto fuera del repositorio y guárdelo en el almacén de secretos del
servicio LocalBackend:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Configure el resultado como `APAP_RAWSQL_AUTH_TOKEN`. No lo añada al proceso
`app.main` salvo que ambos procesos compartan deliberadamente el mismo entorno.

## Verificar

Arranque LocalBackend sin el token. El lifespan debe fallar antes de servir
tráfico:

```bash
unset APAP_RAWSQL_AUTH_TOKEN
uvicorn app.core.local_backend.app:create_app --factory
```

Con un token válido, una petición sin credenciales debe devolver `401` y no debe
explicar si el token falta, es débil o no coincide:

```bash
curl -i -X POST \
  http://127.0.0.1:8000/api/database/advance/rawsql \
  -H 'Content-Type: application/json' \
  -d '{"query":"SELECT 1","params":[]}'
```

La misma petición con `Authorization: Bearer <token>` debe ejecutar la consulta.

## Rotar

1. Genere un token nuevo.
2. Actualice el secreto de LocalBackend y sus consumidores como una unidad.
3. Reinicie LocalBackend.
4. Verifique primero un `401` sin credenciales y después una petición autorizada.

No existe una ventana con dos tokens válidos.

## Rollback seguro

No restaure el endpoint abierto. Si la rotación impide operar, detenga
LocalBackend, restaure el token anterior y reinicie. Si no dispone de un secreto
válido, mantenga el servicio detenido: el fallo cerrado es el comportamiento
previsto.

## Referencias

- `app/core/local_backend/app.py` — validación y cableado durante el lifespan.
- `app/core/local_backend/rawsql.py` — autenticación y ejecución del handler.
- `tests/test_rawsql_auth.py` — pruebas de arranque y contrato HTTP.
- `docs/audits/rawsql-auth-gate-audit-2026-Q3.md` — evidencia de seguridad.
