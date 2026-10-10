# #1309 — Cloudflare R2 como almacén S3; el job e2e deja de levantar MinIO

## Goal

El job `e2e` valida hoy un backend que producción no usa: un contenedor MinIO
servido desde una réplica propia (`.github/workflows/minio-replica.yml`), porque
MinIO Community Edition pasó a distribución solo-código y sus imágenes
desaparecieron de Docker Hub, quay.io y los espejos públicos.

Los adjuntos de producción viven en Cloudflare R2 (jurisdicción `eu`), en la
cuenta que ya existe. El objetivo es que el gate valide ese backend real y que
desaparezca el aparato que ya no hace falta mantener.

En el camino hay tres defectos que el cambio debe cerrar, todos verificados:

1. `app/core/local_backend/s3.py` no normaliza el endpoint y
   `.github/workflows/ci.yml:1488` exporta
   `APAP_S3_ENDPOINT="http://127.0.0.1:${MINIO_HOST_PORT}"`. `minio-py` rechaza
   un endpoint con esquema (`ValueError: path in endpoint is not allowed`) y
   `_build_minio_client()` captura cualquier excepción devolviendo `None`. Como
   `tests/e2e_ci/test_minio_storage.py:78` exige `storage == "up"`, el job `e2e`
   está rojo en `main` hoy.
2. `app/core/local_backend/healthz.py:35` sondea con `client.list_buckets()`.
   En R2, listar y crear buckets son operaciones de cuenta: un token acotado a
   bucket recibe 403 y `/healthz` reportaría `down` con el bucket sano.
3. `tests/e2e_ci/test_minio_storage.py:29` fija `PHOTO_BUCKET = "apap-photos"` y
   la suite usa `put_object` (147) y `remove_object` (199). Apuntada a R2 sin
   cambiar esa constante, escribiría y borraría objetos de producción.

## Decisión de arquitectura (tomada, no se rediscute en este cambio)

- R2 es el almacén de adjuntos; bucket de producción y bucket de pruebas
  separados. Nada de MinIO en producción ni en CI.
- El CI usa un token acotado **solo** a `apap-e2e`. Aunque una constante o una
  variable de entorno se rompa, el token de CI no puede tocar un objeto de
  producción: la seguridad no depende de que el código esté bien escrito.
- Los objetos de prueba se escriben bajo un prefijo por corrida y una lifecycle
  rule de R2 expira ese prefijo. Sin código de limpieza y sin acumulación.
- Un fallo de R2 bloquea el release. Es el comportamiento buscado: el gate mide
  disponibilidad real en lugar de dar un verde falso.
- La jurisdicción del bucket es irreversible y debe ser `eu`.

## Acceptance criteria (del issue #1309, sin cambios)

1. El job `e2e` corre contra R2 con un token acotado a `apap-e2e` y sin service
   container de MinIO.
2. `PHOTO_BUCKET` deja de ser una constante y toma `APAP_S3_BUCKET`.
3. Los objetos de prueba quedan bajo un prefijo por corrida y la lifecycle rule
   de R2 los expira sin código de limpieza.
4. `/healthz` reporta `up` contra un bucket alcanzable con token acotado a
   bucket, y `down` sólo cuando el bucket no responde.
5. `APAP_S3_ENDPOINT` funciona con esquema y sin esquema.
6. `make e2e-local` sigue funcionando sin credenciales de R2.
7. Los tests de contrato de workflow describen la configuración nueva y el
   conjunto de tests pasa en verde.

## Scope

- `app/core/local_backend/s3.py` — normalizar el endpoint (aceptar con y sin
  esquema). El resto del cliente queda igual.
- `app/core/local_backend/healthz.py` — sondear el bucket en lugar de la cuenta.
- `app/core/local_backend/storage.py` — `GET/POST /api/storage/buckets` deja de
  asumir permisos de cuenta.
- `tests/e2e_ci/test_minio_storage.py` — `PHOTO_BUCKET` desde el entorno y clave
  bajo el prefijo de la corrida.
- `.github/workflows/ci.yml` — el job `e2e` declara R2 y no levanta el servicio.
- `tests/test_ci_workflow.py` — los tests de contrato reflejan lo anterior.
- Tests unitarios nuevos para el endpoint y la sonda de `/healthz`.
- Documentación: limpiar referencias a `minio/minio:latest` y anotar que
  `minio-replica.md` queda como herramienta local.

## Out of scope

- Eliminar `.github/workflows/minio-replica.yml` y
  `docs/operations/minio-replica.md`: quedan como herramienta del target local
  `make e2e-local` (issue #1146), que no usa R2.
- Aprovisionar el bucket de producción desde el repositorio.
- Tocar el token de restic o cualquier otro consumidor de R2.
- El contrato funcional de fotos, el esquema de PostgreSQL y la migración de
  adjuntos existentes.
- El alias `nombrefoto AS "NombreFoto"` del PR #900: se rescata en un issue
  aparte porque es ortogonal a este cambio.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `chore/1309-r2-attachments-e2e` | en curso |
| WU-2 | `s3.py` normaliza el endpoint + tests unitarios (RED→GREEN) | pendiente |
| WU-3 | `healthz.py` sondea el bucket + tests unitarios (RED→GREEN) | pendiente |
| WU-4 | `storage.py` sin permisos de cuenta | pendiente |
| WU-5 | `test_minio_storage.py`: bucket desde entorno + prefijo por corrida | pendiente |
| WU-6 | `ci.yml` contra R2 + `test_ci_workflow.py` al día | pendiente |
| WU-7 | Documentación: limpieza y nota local-only | pendiente |
| WU-8 | Cerrar PR #900 como superado; alias `nombrefoto` a issue aparte | pendiente |

## Gates

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` con exit code cero.
- `python -m pytest` del subconjunto tocado, en verde.
- `python scripts/check_workflows.py` en verde.
- `make e2e-local` en verde: prueba que el camino local no depende de R2.
- Dispatch manual del job `e2e` contra R2 real (lo dispara el operador, no el
  agente).

## Riesgos vivos

- El token acotado y el bucket con lifecycle son pasos de operador fuera del
  repositorio. Si faltan, el job `e2e` falla en lugar de saltarse: el `skip`
  está prohibido por `tests/e2e_ci/conftest.py:68-75`.
- El PR #900 está abierto y se pisa con este cambio; se cierra como superado.
