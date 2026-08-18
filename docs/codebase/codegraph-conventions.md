[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# CodeGraph conventions

Esta página posee la regla §14 de AGENTS verbatim: el índice `.codegraph/` es persistente, auto-sincronizado y nunca se reinicializa desde el agente. La regla trae ocho invariantes numerados que el reviewer debe pinear antes de aprobar un cambio en `.gitignore`, `.codegraph/` o el daemon.

## Regla 14 — Índice CodeGraph: persistente, auto-sincronizado, nunca reinicializado

Este proyecto usa **CodeGraph** (CLI `@aroman22/codegraph-vba` + MCP `codegraph_explore`) como índice persistente de inteligencia de código sobre el árbol Python/YAML. El índice vive en `.codegraph/` en la raíz del repo.

**Invariantes establecidos** (no los viole):

1. **Ya está inicializado.** `.codegraph/` existe y está trackeado en git (el `.gitignore` raíz no lo lista; el `.gitignore` interno de `.codegraph/` mantiene la SQLite DB local-only — solo se commitea el propio `.gitignore`). no ejecute `codegraph init` de nuevo. Hacerlo borraría un índice sano. Si el directorio falta tras un clon fresco, UN humano debe ejecutar `codegraph init .` una vez — nunca el agente.
2. **El daemon de auto-sync ya está corriendo.** CodeGraph v1.4+ mantiene un daemon `node` en background que vigila el sistema de archivos y actualiza el índice con un lag de ~1s. No polee, no reindexe manualmente. Confíe en el flag de frescura que devuelve `codegraph status .` (`Index is up to date` = bueno; cualquier otra cosa = sincronice una vez y vuelva a verificar).
3. **Read/Grep/Glob son el último recurso.** Antes de abrir cualquier archivo bajo `app/`, `tests/`, `scripts/`, `pyproject.toml` u otra ruta Python/YAML controlada por el código fuente, llame a `codegraph_explore` (MCP) o `codegraph explore` (shell) con los nombres de símbolo o archivo relevantes. una llamada suele devolver el texto verbatim agrupado por archivo con el call path entre ellos — ya es equivalente a Read. Solo recurra a `Read`/`Grep` para confirmar un detalle que codegraph no cubrió, o para inspeccionar archivos no indexados (configs fuera del árbol fuente, docs generados, datos de terceros).
4. **Nunca gitignore `.codegraph/` a nivel de raíz.** El `.gitignore` del repo no debe listar `.codegraph/` ni `codegraph.db`. Hacerlo rompe el invariante de "persiste entre branches" — el próximo clon en otra máquina perdería el estado de trabajo del daemon y el propio `.codegraph/.gitignore`. Si necesita silenciar un archivo untracked transitorio (por ejemplo, una caché `.codegraph-vba/`), agregue una regla narrow con scope solo a esa ruta.
5. **Checkouts de rama.** Cuando cambie de rama (`git checkout`, `git pull`, rebase, merge), el índice puede quedar stale si el diff tocó archivos indexados. Ejecute `codegraph sync .` una vez tras completar la operación y confirme `Index is up to date`. No reconstruya desde cero (`codegraph index .`) salvo que `sync` reporte drift irrecuperable — un rebuild completo son varios segundos para nada.
6. **Liveness del daemon — verifique, no asuma.** Si la respuesta de una herramienta dice que el daemon está "down" o stale, confirme contra el SO con `Get-Process -Id <pid>` (PowerShell) o `ps -p <pid>` (POSIX). La salida `codegraph daemons` de la CLI es estado actual al momento de la llamada, no caché. Para reiniciar un daemon muerto, use `codegraph init .` solo como último recurso después de que `codegraph daemons` reporte ningún daemon vivo Y un `codegraph sync .` fresco falle al generar uno.
7. **Confíe en el banner de staleness.** Cuando `codegraph_explore` devuelva un banner como `⚠️ Some files referenced below were edited since the last index sync…`, esos archivos específicos necesitan reindexado — llame a `codegraph sync .` una vez. Los archivos que no están en el banner están frescos; no los relea. Un segundo banner, más raro, `⚠️ CodeGraph auto-sync is DISABLED…`, significa que la vigilancia en vivo se detuvo por completo — diagnostique con `codegraph daemons` y re-sincronice antes de confiar en nada. <!-- alantyle-ignore:ALAN002 -->
8. **Chequeo de inicio de sesión + crecimiento del codebase.** Al inicio de cada sesión, ejecute `codegraph status .` una vez y confirme `[OK] Index is up to date` Y que `codegraph daemons` reporte un daemon vivo. Si el daemon falta, siga la regla 6 antes de confiar en cualquier resultado de `codegraph_explore`. El daemon con file-watcher auto-sincroniza archivos nuevos o modificados dentro de directorios ya vigilados con un lag de ~1s — esto cubre el crecimiento normal del codebase. El único caso que el watcher no cubre por sí mismo es un directorio top-level completamente nuevo que no existía cuando arrancó el daemon (por ejemplo, un paquete nuevo `app/core/foo/`, un árbol `tests/integration/` fresco). Cuando cree un directorio top-level, ejecute `codegraph sync .` una vez de inmediato — enseña al watcher sobre la nueva raíz. no reejecute `codegraph init` (eso borra el índice). no reejecute `codegraph index` (rebuild completo) salvo que `codegraph sync` reporte drift irrecuperable.

**Aplicación**: revisión de PR. Si un cambio en `.gitignore` silenciosamente re-ignora `.codegraph/`, el revisor debe bloquear el PR. Si la propia regla 14 de AGENTS deriva de la realidad (por ejemplo, alguien borra `.codegraph/`), la primera acción de la siguiente sesión debe ser `codegraph status .` para detectar el drift antes de confiar en cualquier resultado de `codegraph_explore`.

## Core invariants

- **Una vez y solo una**: `codegraph init .` lo ejecuta un humano, una vez por clon, nunca el agente.
- **Daemon vivo siempre**: la sesión empieza con `codegraph status .` + `codegraph daemons`.
- **`.gitignore` respeta el índice**: `.codegraph/` aparece en `git ls-files`, su `.gitignore` interno silencia la SQLite DB.
- **Sync tras checkout**: cada `git checkout/pull/rebase/merge` corre `codegraph sync .` una vez.
- **Watcher aprende**: directorio nuevo top-level → `codegraph sync .` una vez antes de continuar.
- **`codegraph_explore` primero**: nunca `Read`/`Grep`/`Glob` sin haber intentado codegraph primero.

## Contributor checklist

- [ ] `codegraph status .` devolvió `[OK] Index is up to date` antes de empezar.
- [ ] Cada cambio que toca archivos indexados va seguido de `codegraph sync .`.
- [ ] Ningún PR añade `.codegraph/` ni `codegraph.db` al `.gitignore` raíz.
- [ ] Si la sesión creó un paquete nuevo en `app/core/` o `tests/`, ejecutó `codegraph sync .` antes de la primera lectura.

## Navigation

Previous: [Security](security.md) | Next: [Architecture](architecture.md)
