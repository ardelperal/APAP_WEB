[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Runbook — Rollback de despliegue de `apap-web`

Este runbook cubre exclusivamente el rollback de un despliegue en producción. Su objetivo es devolver `apap-web` al último digest verificado sin reabrir el código ni tocar el esquema de la base de datos.

**Audience**: operador con acceso admin a Coolify, SSH al VPS Oracle y `gh` CLI en una estación local. No toca código de aplicación.

**Cuándo usar este runbook**:

- El job `verify deployed revision` de `deploy.yml` falla y `Roll back to the previous digest` no completa automáticamente.
- Un operador recibe una alerta externa (síntomas en `/healthz`, métricas, reportes de Virginia) y necesita revertir a un digest conocido.
- Se ejecuta manualmente un rollback como medida preventiva antes de una intervención planeada.

## What this is / is not

### What this is

| Es | Evidencia en este repo |
|---|---|
| El procedimiento de rollback manual cuando `deploy.yml` no puede revertir automáticamente | [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) `Roll back to the previous digest` step documenta el flujo automático; este runbook es su contraparte manual. |
| La fuente de verdad para `ghcr.io/ardelperal/apap-web:deploy-current` | El tag `deploy-current` siempre apunta al último digest verificado y queda libre para reasignar. |
| Test-anchored: la lógica de promotion vive en `deploy.yml` y queda revisada en cada PR | `tests/test_coolify_web_yaml.py` y el contrato de `coolify/apap-web-coolify.yaml` blindan el despliegue verificable. |

### What this is not

| No es | Use este límite |
|---|---|
| Una guía de despliegue general | Ver [`operator-deploy-2026.md`](operator-deploy-2026.md) para primer deploy, redeploy automatizado y rotación de secretos. |
| Una guía de migración de base de datos | Ver [`live-migration-apply.md`](live-migration-apply.md) para reversibilidad de `apply_legacy_to_web` y `apply_web_to_legacy`. |
| Una guía de monitoreo | El único surface de observabilidad hoy son los logs del contenedor Coolify y `GET /healthz`. |

## Core invariants

- **El tag `deploy-current` es la única fuente operativa**: el recurso Coolify consume siempre esa etiqueta. El rollback manual reasigna esa etiqueta y dispara el webhook de Coolify.
- **El digest verificado lleva Provenance y la lista de materiales**: cualquier rollback conserva la cadena de auditoría porque el digest proviene del Container Registry.
- **El revision publicado en `/healthz` debe coincidir con el SHA del digest activo**: si no coincide, el rollback no terminó.
- **`APAP_SESSION_SECRET` queda intacto**: la rotación es un procedimiento separado (`cookie-rotation.md`) y un rollback no la toca.

## Procedimiento de rollback manual

### Paso 1 — Identificar el digest objetivo

El digest anterior vive en GitHub Container Registry como tag `sha-<full-sha>`:

```bash
ghcr_image="ghcr.io/ardelperal/apap-web"

# 1a. Listar los tags sha-* disponibles
gh api -H "Accept: application/vnd.github+json" \
  /users/ardelperal/packages/container/apap-web/versions \
  --jq '.[] | select(.metadata.container.tags | to_entries | map(.value) | any(startswith("sha-"))) | {id, sha: .metadata.container.tags[]}'
```

Elija el digest cuyo commit de origen sea el último conocido como saludable. Confirme el SHA con el historial de merges en `main`:

```bash
gh pr list --base main --state merged --limit 20 --json number,title,mergeCommit
```

### Paso 2 — Confirmar el digest antes de promover

Antes de reasignar `deploy-current`, compruebe que el digest se construyó y verificó correctamente:

```bash
target_sha="<full-sha-del-rollback>"
target_digest="sha256:..."

docker buildx imagetools inspect --raw \
  "ghcr.io/ardelperal/apap-web:sha-${target_sha}" \
  | jq -r '.manifests[] | select(.platform.architecture == "arm64") | .digest'
```

El digest `arm64` debe coincidir con el digest objetivo. Si no coincide, **no proceda**: el digest no está firmado por la CI y queda fuera del contrato.

### Paso 3 — Reasignar `deploy-current`

Mueva el puntero al digest objetivo con `docker buildx imagetools create`:

```bash
IMAGE="ghcr.io/ardelperal/apap-web"
DEPLOY_TAG="deploy-current"

docker buildx imagetools create \
  --tag "${IMAGE}:${DEPLOY_TAG}" \
  "${IMAGE}@sha256:${target_digest}"
```

Este paso no toca la base de datos ni el código: solo reasigna el puntero del repositorio.

### Paso 4 — Disparar el webhook de Coolify

Coolify debe redesplegar el servicio `apap-web` con la nueva etiqueta. El webhook vive en los secrets del repositorio:

```bash
export COOLIFY_WEBHOOK_URL="${{ secrets.COOLIFY_WEBHOOK_URL }}"
export COOLIFY_WEBHOOK_SECRET="${{ secrets.COOLIFY_WEBHOOK_SECRET }}"
export GITHUB_REF="refs/heads/main"
export GITHUB_SHA="${target_sha}"
export GITHUB_REPOSITORY="ardelperal/APAP_WEB"
export COMMIT_MESSAGE="manual rollback to ${target_sha:0:8}"

python scripts/coolify_webhook.py
```

El script firma la petición HMAC contra `COOLIFY_WEBHOOK_SECRET` y dispara el redeploy de Coolify. **Si el script falla, no continúe**: revise logs y secret antes de reintentar.

### Paso 5 — Verificar el deployment

Una vez Coolify complete el redeploy, valide que `/healthz` reporta la revision esperada:

```bash
export DEPLOY_HEALTH_URL="https://apap.romancaba.com/healthz"
python scripts/verify_deployment.py \
  --url "${DEPLOY_HEALTH_URL}" \
  --revision "${target_sha}"
```

Salida esperada:

```
deploy verification: ok (revision=<target_sha>)
```

Si el script falla:

| Síntoma | Causa probable | Acción |
|---|---|---|
| `revision mismatch` | Coolify no completó el redeploy | Espere 60 segundos y vuelva a correr; si persiste, revise logs de Coolify. |
| `HTTP 502/503` | El contenedor falló al arrancar | Lea logs Coolify del servicio `apap-web`; puede requerir rollback a un digest anterior. |
| `connection refused` | El servicio no está expuesto en Traefik | Verifique la configuración de dominio en Coolify. |

### Paso 6 — Anunciar el rollback

Una vez completado:

1. Publique en el canal de operaciones: SHA al que se revirtió, motivo, hora del rollback.
2. Abra una issue `type:bug` con etiqueta `incident` describiendo el síntoma que motivó el rollback.
3. Si el rollback también revierte una migración de esquema, abra una issue adicional y consulte [`live-migration-apply.md`](live-migration-apply.md).

## Rollback automático de `deploy.yml`

El step `Roll back to the previous digest` de `deploy.yml` cubre el caso más común: una verificación post-deploy falla después de la promoción. El flujo es:

1. `promote` ya movió `deploy-current` al digest actual.
2. El step `failure()` ejecuta la rama de rollback.
3. CI reasigna `deploy-current` al `previous_digest`, dispara el webhook de Coolify y verifica `/healthz` contra el SHA anterior.
4. El job queda rojo; el operador investiga la causa raíz.

Si el rollback automático falla, este runbook es el procedimiento manual de respaldo. **No use ambos a la vez**: si Coolify ya está sirviendo un digest intermedio, vuelva al Paso 1 y elija un digest distinto.

## Firma y verificación con Cosign (keyless)

Desde el hardening de cadena de suministro (#783), el job `deploy` firma y verifica el digest recién publicado antes de promoverlo, cerrando la ventana en la que un digest publicado en `ghcr.io` podría sustituirse sin detección antes del despliegue:

1. **`Install Cosign`** — instala el binario `cosign` (`sigstore/cosign-installer`, pinned por SHA) en el runner.
2. **`Sign the published digest with GitHub OIDC`** — tras el `trivy scan` y antes del smoke test, `cosign sign --yes` firma el digest recién publicado en modo keyless: intercambia el token OIDC efímero del job (permiso `id-token: write`) por un certificado Fulcio de corta vida, sin clave privada almacenada en el repositorio.
3. **`Verify the published digest is signed by this workflow`** — inmediatamente antes de `Promote the verified digest` y del webhook de Coolify, `cosign verify` comprueba la firma contra la identidad de certificado esperada (`.github/workflows/deploy.yml` en `refs/heads/main`) y el emisor OIDC (`https://token.actions.githubusercontent.com`). Si la verificación falla, el step sale con error y el job se detiene ahí — igual que un hallazgo `HIGH`/`CRITICAL` de trivy — sin promover `deploy-current` ni disparar el webhook.

**Orden elegido y motivo**: la firma corre después del `trivy scan` (no inmediatamente tras el push) para no generar un certificado Fulcio ni una entrada pública en el transparency log (Rekor) de un digest que el scan de vulnerabilidades puede rechazar y que nunca llegaría a promoverse. La verificación corre justo antes de la promoción — el último gate antes de mover `deploy-current` — para que ningún digest sin firma válida llegue al webhook de Coolify.

**Cobertura del `previous_digest` en el rollback automático**: el rollback re-promueve `previous_digest`, el digest que ya estaba activo en `deploy-current` antes de esta ejecución. Ese digest no se vuelve a verificar en el momento del rollback — el rollback reasigna un puntero, no reconstruye ni re-audita la imagen. A partir de este cambio, todo digest que llegue a ocupar `deploy-current` lo hace porque ya pasó por este mismo gate de firma/verificación en su propio deploy; un `previous_digest` promovido por un `deploy.yml` anterior a #783 no estuvo firmado, pero eso es histórico y se agota conforme rotan los despliegues.

## Anti-patrones

| Síntoma | Por qué importa | Use en su lugar |
|---|---|---|
| Reconstruir la imagen localmente y subirla al Container Registry de GitHub | Rompe la cadena de auditoría de Provenance y de la lista de materiales | Reasignar el tag `deploy-current` al digest ya publicado |
| Modificar `coolify/apap-web-coolify.yaml` durante el rollback | Mezcla rollback con cambio de contrato | Crear una issue `type:bug` y abrir un PR aparte |
| Borrar el tag `sha-<full-sha>` antes de verificar el éxito del rollback | Pérdida del digest anterior; rollback no reversible | Mantener todos los `sha-*` durante al menos 30 días |
| Cambiar `APAP_SESSION_SECRET` durante el rollback | Invalida todas las sesiones y oculta el origen del fallo | Tratar rotación como procedimiento aparte (`cookie-rotation.md`) |
| Hacer rollback sin abrir issue de incidente | El equipo pierde la trazabilidad del problema | Abrir `type:bug` con etiqueta `incident` antes de comenzar |

## Contributor checklist

- [ ] El digest objetivo se eligió de un tag `sha-<full-sha>` verificable en el Container Registry de GitHub.
- [ ] `docker buildx imagetools inspect` confirmó el digest `arm64` antes de promover.
- [ ] El webhook de Coolify se disparó con `scripts/coolify_webhook.py` (no con `curl` plano).
- [ ] `scripts/verify_deployment.py` reportó `ok` con el SHA esperado.
- [ ] Se abrió la issue de incidente con etiqueta `incident`.
- [ ] Si hubo migración de esquema, se abrió issue adicional en [`live-migration-apply.md`](live-migration-apply.md).

## Navigation

Previous: [cookie-rotation.md](cookie-rotation.md) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)
