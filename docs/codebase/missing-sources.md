# Missing sources

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee los subsistemas que el lector podría esperar y no existen en el repositorio. La página existe porque el silencio es lo que una IA rellena inventando, y en APAP_WEB esa suposición produce código que viola §32.P1 (perimeter blindness) o §33 (slice location). No posee reglas operativas — esas viven en [AGENTS.md](../../AGENTS.md). <!-- alantyle-ignore:ALAN004 -->

## Core invariants

- **Ausencias explícitas**: cualquier subsistema que un contribuidor pudiera razonablemente esperar debe aparecer aquí, con su `What exists instead`.
- **No inventar**: si la fila dice «Not found.», abra un issue antes de añadir código; el slice necesita specs en [`openspec/specs/`](../../openspec/specs/) antes de aterrizar.

## Expected vs actual

| Expected area | Status in this repository | What exists instead |
|---|---|---|
| Dashboard o panel de BI | Not found. | Vistas por módulo en [`app/modules/<slice>/routes.py`](../../app/modules/). Cada página es HTML server-rendered; no hay agregaciones cross-módulo. |
| API REST pública para terceros | Not found. | El producto es server-rendered para usuarios autenticados. JSON solo donde la UI lo exige (HTMX, `/healthz`). |
| Webhook handler genérico | Not found. | Solo el callback OAuth en [`app/main.py`](../../app/main.py) (`/auth/callback`). No hay endpoint público para webhooks externos. |
| WebSocket / Server-Sent Events | Not found. | InsForge expone realtime por MCP, pero el producto no lo consume. Las notificaciones son recargas de página o HTMX. |
| Background job queue (Celery, RQ) | Not found. | Tareas puntuales vía Coolify scheduled tasks (scripts en Coolify, no en el repo). El flujo pesado es el reconcile CLI ([sync and cloud](sync-and-cloud.md)). |
| Cron interno (APScheduler) | Not found. | `scripts/synology-webdav.ps1` existe pero es solo para backups del lado del operador. Sin scheduler in-process. |
| SDK publicable | Not found. | El repo no expone paquete distribuible. `pyproject.toml` no declara `packages` ni entry points; el código se consume ejecutando la app. |
| Mobile app | Not found. | La UI es web server-rendered; sin cliente nativo ni PWA registrada. |
| Internacionalización (i18n) | Not found. | Copy en castellano peninsular embebido en plantillas; sin sistema de extracción de strings. |
| API versioning (`/v1/`, `/v2/`) | Not found. | Una sola versión por ruta; los breaking changes entran por el flujo de release. |
| Rate limit por usuario | Not found. | Hay rate limit global en middleware ([`app/core/rate_limit_middleware.py`](../../app/core/rate_limit_middleware.py)); no hay cuota por identidad. |
| Observability stack (Sentry, OTel) | Not found. | Solo logs estructurados con [`app/core/logging.py`](../../app/core/logging.py) y redacción PII (§9). Sin trazas distribuidas ni APM. |
| Feature flags service | Not found. | Sin servicio externo; los flags viven en `Settings` o en el código. |
| Test suite del binario Access legacy | Not found. | Dysflow MCP lee el `.accdb` bajo demanda (P2 en [proceso.md](../proceso.md)). No hay tests automatizados contra el legacy; las verificaciones son manuales en sesiones de discovery. |
| Cola de mensajes (Kafka, RabbitMQ) | Not found. | El único flujo cross-proceso es el reconcile CLI ([sync and cloud](sync-and-cloud.md)). |
| Storage público sin auth (S3-style) | Not found. | Los buckets de InsForge usan RLS vía JWT; no hay endpoint público de lectura de archivos. |
| Admin web de base de datos | Not found. | El MCP `insforge` provee `run-raw-sql` para el mantenedor; no hay UI web de admin de DB. |
| Sistema de notificaciones (email, push) | Not found. | No se envía nada al usuario fuera del log estructurado. La comunicación sigue siendo presencial o por el panel admin. |

## Cuándo crear una nueva entrada aquí

Si está a punto de añadir un subsistema nuevo y este no aparece en la tabla, no dé por hecho que «no existe, lo creo». En su lugar:

1. Busque en [`openspec/specs/`](../../openspec/specs/) y [`openspec/changes/`](../../openspec/changes/) si ya hay una propuesta previa.
2. Si la hay, cite el change y abra la tarea siguiente. Si no la hay, cree el change SDD (`openspec/changes/<name>/proposal.md`).
3. Solo entonces implemente, siguiendo el flujo de [maintainer playbook](maintainer-playbook.md).

## Contributor checklist

- [ ] Si descubre que un subsistema «esperado» no existe y va a implementarlo, abra un change SDD primero y cite esta página en el `proposal.md`.
- [ ] Si implementa un subsistema nuevo, retire la fila correspondiente de esta página en el mismo PR (la página solo documenta ausencias).
- [ ] Si el subsistema nuevo toca un path sensible (auth, secretos, PII), cree o actualice un doc en [`docs/audits/`](../../docs/audits/) según §12 y agregue el runbook correspondiente si exige acción manual (§13).

## Navigation

Previous: [Reference map](reference-map.md) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)