# #1146 (ítem 5) — Target `make e2e-local`: reproducir el job e2e en local

## Goal

Cerrar la fricción 5 del checklist de #1146: el job `e2e` de `ci.yml` era
irreproducible en local (Makefile sin target, servicios Postgres/MinIO de CI,
secrets `MINIO_E2E_*`, imagen réplica privada en GHCR y `docs/development.md`
sin la receta completa).

## Scope

| Área | Archivos |
|---|---|
| Target `e2e-local` + variables pineadas + help | `Makefile` |
| Receta y requisitos honestos | `CONTRIBUTING.md` §Validación local |

## Design decisions

1. **Mismo contrato de CI, verbatim**: mismas imágenes pineadas por digest
   (`postgres@sha256:742f…`, réplica MinIO `ghcr.io/ardelperal/minio@sha256:6140…`),
   mismas env vars de app (`APAP_E2E_*`, `APAP_S3_*`, `APAP_LOCAL_DB_URL`),
   mismo health-gate (Postgres 30s, MinIO 60s, app 45s) y la misma suite
   (`tests/e2e_ci/`). Solo cambian los puertos (overridables: 55432/59000/58000)
   para no chocar con nada local.
2. **Sin secrets del repo**: el auth secret se genera por corrida
   (`openssl rand -hex 32`) y MinIO usa credenciales root locales — el par
   `MINIO_E2E_*` de CI es un detalle de aprovisionamiento, no un requisito
   funcional del suite.
3. **Limitaciones documentadas dentro del target** (no en un doc aparte que
   puede quedarse rancio): la réplica MinIO vive en GHCR (pull denegado ⇒
   `docker login ghcr.io` con PAT `read:packages`; CI usa el GITHUB_TOKEN
   efímero) y es **amd64-only** — en hosts arm64 sin qemu binfmt el contenedor
   muere con `exec format error` y el target falla en el health gate de MinIO.
   Ese fallo es la señal honesta, no un bug del target.
4. **Desmontaje automático idempotente**: trap `EXIT INT TERM` que mata el
   uvicorn, elimina contenedores y red; pre-limpieza al inicio para restos de
   una corrida abortada externamente (p. ej. `timeout`/SIGKILL al grupo de
   procesos, que no ejecuta traps).
5. **`kill 0` nunca**: el cleanup condiciona el `kill` a `SERVER_PID` no vacío —
   `kill 0` señalizaría al grupo de procesos entero (make/bash incluidos).

## Verification (workstation arm64, Docker disponible)

- `make -n e2e-local` + `shellcheck`: parse limpio, script limpio.
- Corrida real: pull del digest pineado OK, Postgres ready OK, health-gate de
  MinIO falla con el mensaje honesto (`exec format error` amd64-on-arm64) y el
  desmontaje elimina contenedores y red — verificado dos veces.
- La pata Postgres/app/pytest sigue el contrato verbatim de CI y quedó
  shellcheckeada; su ejecución completa en esta estación exige binfmt amd64
  (instalarlo sería una mutación privilegiada del host, fuera de alcance).

## Progress log

- 2026-10-01: target implementado, verificado hasta el health gate de MinIO
  (limitación amd64/arm64 documentada en el propio target).
