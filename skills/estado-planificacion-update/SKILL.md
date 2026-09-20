---
name: estado-planificacion-update
description: Trigger: actualizar estado de planificación, refrescar planning status, status report, cerrar fase. Update estado-planificacion-*.html with new RAG, dates, deltas and Gantt bars in castellano de España.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.1
  last_verified: 2026-09-16
  scope: ['universal']
  auto_invoke: ['updating the planning status HTML']
  tiers: ['universal']
---

# estado-planificacion-update

## Activation Contract

Load when the user says any of: "actualiza el estado de planificación", "refresca el planning status", "status report", "estado de fases", "cerrar fase X", "marca la fase Y como hecha".

## Hard Rules

1. **Filename pattern:** `estado-planificacion-<release-objetivo>-<fecha-hora>.html`.
   - **Timezone:** `Europe/Madrid` (CET/CEST automático, según DST). El `<fecha-hora>` se genera en hora local al momento de crear el archivo. NO usar UTC ni la TZ del sistema sin conversión explícita.
   - **Sanitizer del `<release-objetivo>`:** lowercase; diacríticos stripped (`ñ` → `n`, `á` → `a`); espacios y underscores → guiones; solo `[a-z0-9-]`; longitud máx 32 chars; guiones múltiples colapsados; guiones al inicio/final eliminados. Ejemplo: `PlanHub Q3-2026` → `planhub-q3-2026`.
   - **Formato `<fecha-hora>`:** `YYYY-MM-DD-HH-MM` (e.g. `2026-09-16-14-30`).
   - **Algoritmo de colisión:** si el archivo ya existe en `docs/uat/`, append `-2`, `-3`, etc. hasta encontrar uno libre. Determinístico (basado en filesystem glob, no en reloj). NO sobreescribir.
   - NEVER overwrite: el archivo anterior queda como histórico.
2. ALWAYS read the most recent `docs/uat/estado-planificacion-*.html` first (sort by date desc). If none, bootstrap from `planificacion-uat-2026-06-25.html`.
3. Castellano de España en prosa (TÚ, no voseo). User: "Andrés" (tilde, mayúscula). No department labels in plain-language cards.
4. Reuse Telefónica brand CSS variables (`--tf-blue`, `--tf-green`, `--tf-amber`, `--tf-red`, `--tf-grey`, `--tf-violet`). Load `telefonica-brand-design` only if introducing new components.
5. **RAG:** 🟢 verde = on track or ahead; 🟡 ámbar = 2–5 days behind OR risk identified; 🔴 rojo = >5 days OR blocked. **Motivo requerido para TODO cambio de estado (🟢 incluido)**, una línea máx, en castellano.
6. **Bloqueo explícito para 🔴:** cuando el RAG pasa a rojo, exigir un campo `bloqueo` con un bloqueador concreto (link a issue/PR/tarea o descripción operacional), no genérico. Sin bloqueo explícito, el cambio a 🔴 no se persiste.
7. **Gantt re-render obligatorio ante cambio de RAG:** actualizar status table AND corresponding Gantt bar en la misma pasada. Partial-fill CSS `.bar.partial` (striped overlay) solo para estados in-progress sin cambio de RAG.
8. Gantt data rows MUST have exactly 41 day-cells (2 Jun + 33 Jul + 5 Ago + 1 Sep). Header colspan must match: 2 / 33 / 5 / 1. If broken, regenerate the entire tbody.
9. Never invent a phase that isn't in the plan fuente. If the user asks about a gap, cite the plan fuente exactly.

## Decision Gates

| Situation | Action |
|---|---|
| User gives explicit phase updates | Compute filename (sanitize release-objetivo + Europe/Madrid timestamp + collision suffix if needed). Apply to status table + fase card + Gantt in one pass. Require motivo for every status change. |
| User asks "status report" without changes | Read latest HTML, present the status consolidado table as Markdown in chat. Do NOT write a new file. |
| User says "cierra Fase X" | Update only that phase. Ask for motivo if not provided. Ask for `bloqueo` if the new RAG is 🔴. |
| User asks "full refresh" | Run `git log --since=YESTERDAY`, inspect `tests/*.json` regression, cross-reference with the HTML. Update all phases in one pass. |
| New planning source (v4, etc.) supersedes v3 | Create new HTML from scratch. Bump version in meta. Compute new filename with the same sanitizer/collision rules. |
| User asks to fix the Gantt | Regenerate tbody with exact 41 day-cells per row. Verify colspans match. |
| Release-objetivo has accents, slashes, or >32 chars | Apply sanitizer; if result is empty after sanitization, ask the user for a new name. |

## Execution Steps

1. Read latest HTML (glob `docs/uat/estado-planificacion-*.html` + sort by name desc + read). If none, bootstrap from `planificacion-uat-2026-06-25.html`.
2. Gather update input: user-provided changes, or auto-derive from `git log --since=YESTERDAY` + `tests/*.json` for full refresh.
3. Compute filename:
   - Take user's release-objetivo (or default to current plan name).
   - Apply sanitizer (lowercase, strip diacritics, spaces→hyphens, max 32 chars, collapse hyphens).
   - Compute timestamp in `Europe/Madrid`: `YYYY-MM-DD-HH-MM`.
   - Compose `estado-planificacion-<release-objetivo>-<fecha-hora>.html`.
   - Glob `docs/uat/` for existing match; if found, append `-2`, `-3`, etc.
4. Validate every change: each phase that changes state MUST have `motivo` (one line); each change to 🔴 MUST have `bloqueo` (link or concrete blocker).
5. Apply edits: meta fecha, status table row, fase card badge (incl. motivo), Gantt bar class. If RAG changed, re-render the entire Gantt tbody.
6. Save to the computed filename.
7. Open in browser: `Start-Process` on Windows.
8. Report: file path, bullets of changes, motivo and bloqueo per affected phase, browser-open confirmation, one-line next-step.

## Output Contract

```json
{
  "status": "updated|blocked|skipped",
  "filename": "estado-planificacion-<release>-<YYYY-MM-DD-HH-MM>.html",
  "filename_absolute": "<absolute path under docs/uat/>",
  "timezone": "Europe/Madrid",
  "release_objetivo_raw": "<user-provided>",
  "release_objetivo_sanitized": "<lowercased, diacritics-stripped, max 32 chars>",
  "collision_suffix": null|"2"|"3"|...,
  "phases_changed": [
    {"phase": "<name>", "rag_from": "🟢|🟡|🔴", "rag_to": "🟢|🟡|🔴", "motivo": "<one line>", "bloqueo": null|"<link or concrete blocker>"}
  ],
  "gantt_rerendered": true|false,
  "previous_snapshot": "<absolute path of the file this one supersedes>",
  "next_recommended": "browser_open|wait_user|none"
}
```

## References

- `docs/uat/planificacion-uat-2026-06-25.html` — plan fuente v3
- `docs/uat/estado-planificacion-*.html` — previous status snapshots (sanitized filename pattern applies to new files only; historical names are preserved as-is)
- `~/.config/opencode/skills/telefonica-brand-design/SKILL.md` — brand tokens (load only when introducing new components)
- `~/.config/opencode/skills/feature-acceptance-uat/references/conventions.md` — castellano de España, proper names, no department labels, no AI-tells
