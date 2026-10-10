# Comandos Coolify MCP para actualizar la allowlist de engram-cloud

Referencia operativa. Complementa a `engram-project-hygiene` HR-9 (no modificar `ENGRAM_CLOUD_ALLOWED_PROJECTS` sin aprobación del usuario) y a `engram-sync-doctor` HR-11 (restart manual con stop+start).

## Descubrir el servicio

```javascript
const list = await tools.coolify.list_services({});
// Buscar: { name: "engram-cloud", uuid: "<service_uuid>", status: "running:healthy" }
```

Para esta máquina: `service_uuid = "xrqwsyf1qw5mahiilmxczmf2"`, `app_uuid = "uaxm25ive3q4o37otokovj5n"`. Ajústelos a su entorno.

## Actualizar la env var

```javascript
const allowlist = [
  // 15 originales + automatizacion + 30 nuevos = 46 (verificar contra `engram projects list`)
  "brass","condor","documentacion","expedientes","gestion_riesgos",
  "hps","hps_solicitudes","no_conformidades","workflow","lanzadera",
  "agedys","dysflow","cadete","labmanager","apap","automatizacion",
  "access2web-blueprint","agent-teams-lite","antigravity",
  "aplicaciones_dys.tmetf - aplicaciones ppd","codegraph","codegraph-vba",
  "dysflow-mcp-query-backend","e2e","engram",
  "from-chat-to-cognitive-system","gentle-ai","gentle-creation",
  "gentleman-ai-installer","gentleman-guardian-angel",
  "gentleman.dots","gentleman.dots2","jira","mi-cerebro",
  "opencode-config","partner-portal","planhub","prowler-workflows",
  "salvacion","segundo-cerebro","team-skills",
  "training-document","training-materials","vba_toolkit_bench",
  "vps-oracle","wiki"
].join(",");

await tools.coolify.env_vars({
  resource: "service",
  action: "bulk_update",
  uuid: "<service_uuid>",
  data: [{
    key: "ENGRAM_CLOUD_ALLOWED_PROJECTS",
    value: allowlist,
    is_runtime: true
  }]
});
```

## Redeploy manual del container

`restart_application` frecuentemente no reinicia realmente (`last_restart_at` queda en `null`). Use stop+start para forzar:

```javascript
await tools.coolify.service({
  action: "stop_application",
  uuid: "<service_uuid>",
  app_uuid: "<app_uuid>"
});
// esperar ~12s
await tools.coolify.service({
  action: "start_application",
  uuid: "<service_uuid>",
  app_uuid: "<app_uuid>"
});
// esperar ~30-90s para que arranque
```

## Verificar que tomó la nueva allowlist

```javascript
await fetch("https://engram.romancaba.com/health");
// Esperado: { service: "engram-cloud", status: "ok" }
```

Después, probe un proyecto que antes daba 403:

```bash
ENGRAM_NO_UPDATE_CHECK=1 engram sync --cloud --project gentle-ai
# Esperado: "Created chunk ..." o "Nothing new to sync"
# NO esperado: "status 403: forbidden"
```

Si sigue dando 403, el container no tomó la env var. Repita stop+start y verifique `last_restart_at` con `list_containers`.

## Notas

- **`is_runtime: true`** marca la var como runtime-only (no buildtime). El servidor cloud la lee al arrancar el proceso, así que runtime-only basta.
- **`ENGRAM_NO_UPDATE_CHECK=1`** deshabilita la verificación de updates de GitHub al lanzar el binario (la red local no la alcanza consistentemente).
- **Las acciones de restart son manuales del usuario**, no automatizables desde MCP sin permisos elevados. Espere entre 30 y 90 segundos para que el container vuelva a estar healthy.
- **Rotación de `ENGRAM_CLOUD_TOKEN`** queda fuera de alcance de esta referencia; trate la rotación como cambio de secreto separado.