# Post-mortem — producción caída del 2026-10-05 al 2026-10-09

Post-mortem blameless del incidente de indisponibilidad de producción en la ventana 2026-10-05/2026-10-09. El alcance es la cadena de dependencias, configuración y entrega que llevó a cuatro días sin servicio en `https://apap.romancaba.com`. Causas de sistema, nunca de personas (HR-21). Cubre los issues #1290 y #1291.

## Timeline (UTC)

1. 2026-10-04 — **Último despliegue correcto en producción.** Etiqueta de imagen publicada: `c71c1bb4eb5656f74db6a66b56c79a622620f89e`. Disparado por el webhook de Coolify.
2. 2026-10-05 19:40:02 — **El host VPS se reinició.** `uptime -s` devuelve `2026-10-05 19:40:02`; kernel `7.0.0-1012-oracle`.
3. 2026-10-05 (tras el reinicio) — `apap-postgres` (stack compose de desarrollo, política de reinicio `unless-stopped`) volvió por sí solo. `apap-pg-test` (política de reinicio `no`) no volvió.
4. 2026-10-05 (tras el reinicio) → 2026-10-09 (~12:25 UTC) — **El contenedor de la aplicación de producción entró en crash-loop.** `ExitCode=3`, `Restarts=5215`.
5. 2026-10-09 — **Diagnóstico y mitigación; servicio recuperado.**

## Impact

- Aplicación de producción no disponible (HTTP 503, cuerpo `no available server`) durante ~4 días.
- 74 commits ya mergeados a `main` no llegaron a producción. La producción siguió sirviendo la revisión `c71c1bb` desde 2026-10-04.
- Sin pérdida de datos de negocio: la base de datos de producción contiene 27 tablas con `animales=0`, `entradas=0`, `usuarios_autorizados=2`. Una de esas filas es la cuenta `e2e@apap.local` / `developer` / `activo=true` que el runbook de release necesita.
- El piloto no tiene registros de protectora.

## Root cause

Tres causas de sistema, sin las cuales el incidente no se materializa en cuatro días:

1. **La base de datos de producción se creó fuera de todo orquestador.** El contenedor `apap-pg-test` (imagen `postgres:16-alpine`, volumen de datos `dcd09a17df1d9b437fa35d008fd4c45108c5a8f89088801acec79c1daf918c89`) no pertenece a ningún proyecto compose ni a ningún recurso de Coolify. Vive en la red Docker `coolify`, con política de reinicio `no`, sin healthcheck y sin política de backup. Su nombre contiene la palabra `test` mientras sirve producción. `APAP_LOCAL_DB_URL` apunta a ese nombre y el servidor corre con `POSTGRES_HOST_AUTH_METHOD=trust` (la contraseña del DSN se ignora).
2. **Tras el reinicio del host, la dependencia crítica desapareció y la aplicación no se recuperó.** El 2026-10-05 a las 19:40:02 UTC el VPS se reinició. `apap-postgres` (compose de desarrollo, `unless-stopped`) volvió; `apap-pg-test` (`no`) no. El nombre `apap-pg-test` dejó de resolver dentro del contenedor de la aplicación y el arranque falló con la traza `app/main.py:179` → `lifespan` → `ensure_schema_and_seed` → `app.core.local_backend.db.DatabaseError: failed to resolve host 'apap-pg-test'`, seguida de `Application startup failed. Exiting.` Sin backend sano, Traefik devolvió 503 (`no available server`) en `https://apap.romancaba.com/healthz`.
3. **El freeze de entrega no produjo señal fuera del job rojo.** El `release-e2e-gate` de `deploy.yml` resolvió la revisión que sirve tráfico desde ese mismo endpoint de health; ante el 503 rehusó avanzar («the health endpoint did not answer; refusing to guess the serving revision») y el job `deploy` quedó `skipped` en cada merge desde 2026-10-05 (#1273, #1275, #1277, #1280, #1288, #1287). No existe monitor de `/healthz` entre despliegues: el único smoke corre tras un deploy, y Coolify reportó `unhealthy_applications: 0` mientras la aplicación estaba en estado `restarting:unknown`.

## What worked

- **El gate fail-closed hizo lo que se diseñó para hacer.** El `release-e2e-gate` rehusó adivinar en lugar de desplegar sobre una revisión no verificada (#1082, #1131). El freeze fue consecuencia del comportamiento del gate, no de un fallo del gate.
- **El camino de diagnóstico fue reproducible.** Con `docker inspect` se obtuvo el código de salida (`ExitCode=3`) y el contador de reinicios (`Restarts=5215`); con `docker logs --tail` se obtuvo el traceback de `app/main.py:179`; con `uptime -s` se identificó el momento del reinicio del host; con `docker ps -a` filtrado por el uuid de Coolify (`cxm5x2f489eos8nr8e1qv1c6`) se acotó el universo de contenedores.
- **La mitigación fue una sola acción reversible.** `docker start apap-pg-test` seguido de `docker update --restart unless-stopped apap-pg-test`. Tras la acción, el contenedor de la aplicación pasó a `Up (healthy)` y `/healthz` devolvió 200 con `{"status":"ok","app":"APAP_WEB","revision":"c71c1bb4eb5656f74db6a66b56c79a622620f89e","storage":"unconfigured"}`.

## What failed

- Una dependencia de producción se creó a mano, fuera de cualquier orquestador, con política de reinicio `no`, sin healthcheck y sin backup. Su nombre dice «test» mientras sirve producción.
- No hay alerta externa sobre la liveness de producción entre despliegues.
- Un gate fail-closed convirtió un corte de infraestructura en un freeze total de entrega sin emitir señal fuera del job rojo.

## Action items (como issues)

Cada action item se materializa como issue de GitHub con owner (HR-21); este documento no los sustituye.

1. **Ejecutar el runbook `docs/runbooks/production-db-hardening.md`** para llevar la base de datos de producción a estado gestionado (recurso Coolify), autenticado (`scram-sha-256`), sin puerto publicado, con healthcheck y política de reinicio, con cero pérdida de datos. Issues #1290 y #1291. Cubre las causas 1 y 2.
2. **Añadir monitor/alerting externo sobre `/healthz` entre despliegues.** Pendiente de abrir issue (no existe todavía en el catálogo). Cubre la causa 2 en lo que toca a la detección.
3. **Emitir señal fuera del job rojo cuando un gate fail-closed detiene la entrega por una causa de infraestructura**, para que un fallo de infra no se confunda con un fallo de feature. Cubierto por el endurecimiento de veredicto de despliegue (#1123, #1124, #1125). Cierra la causa 3 en lo que toca a la entrega.
4. **Resolver el estado pendiente de `release/e2e-production` para `c71c1bb4eb5656f74db6a66b56c79a622620f89e`.** `release/smoke-production` está `success`; `release/e2e-production` está `pending`. Dos opciones: registrar un bypass `skipped:<reason>` para ese SHA ya superado, o ejecutar el gate e2e de release completo de `docs/runbooks/e2e-production.md` contra él. Decisión del operador. Épica de referencia: #909.