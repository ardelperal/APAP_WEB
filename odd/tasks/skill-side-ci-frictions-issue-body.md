### Problema y contexto

Directiva permanente del operador (2026-10-02, registro Engram #8138): **toda fricción de CI genera DOS issues** — una en el repo afectado (arregla el CI) y otra en personal-skills (arregla la skill canónica). Una fricción rastreada solo en el repo deja el patrón sin corregir y el siguiente repo/IA la vuelve a pagar.

La sesión 2026-09-30/10-02 acumuló fricciones cuyas mitades repo existen en `ardelperal/APAP_WEB` (#1146, #1112, #1187, #1204, #1205, #1214, #1197, #1202) pero cuyas mitades skill-side no. Esta issue es el tracker de esas correcciones canónicas. Contexto relacionado: ola de portabilidad de `ci-pattern` en #144 (distinto alcance — S1–S13; ninguno de estos ítems coincide con esa checklist).

### Evidencia verificable

Checklist por fricción → corrección que exige la skill canónica. Cada ítem cita su evidencia (PR/issue del repo o error observado).

- [ ] **1. Whitelist de `check_alantyle` con alcance APAP** — el patrón portable no puede reutilizar el gate de estilo en otro repo (los docs de Cadete triplicaron 22 violaciones pre-existentes: PHP, UBI, PSR, FPM, PRE, PRO, PVC). Corrección: documentar en la skill que el gate de estilo necesita whitelist por repo, o excluirlo del set portable. Evidencia: ejecución real en repo Cadete. Repo: #1146 (cerrado, documentado).
- [ ] **2. B11: el retry vive dentro del gate** — la guía de `ci-pattern` debe decir: un `closingIssuesReferences` tardío NO requiere rerun (el gate re-consulta con backoff); no rerunear por eso. Evidencia: #1197 (merged). Repo: #1197.
- [ ] **3. Closing keywords en PROSA del body crean closing references reales** — regla: un PR `chain:partial` no debe contener keyword de cierre en body NI título (solo el PR tip cierra). Evidencia: el PR de #1120 cuyo cuerpo decía "close #1120" falló issue-spec. Repo: missing (adyacente #1127).
- [ ] **4. `allow_update_branch` habilita pero NO auto-actualiza** — regla: durante una ola armada el ACTOR corre `update-branch` tras cada drift de la base; los hijos apilados necesitan `PATCH base=main` ANTES de `update-branch`; un solo poll del estado armado tras armar basta. Evidencia: PRs de #1160 verdes por detrás durante 60+ min. Repo: #1148 (cerrado).
- [ ] **5. Releases: nunca seleccionar por índice de array** — regla: seleccionar objetos release/PR por `tag_name`/`databaseId`/number, jamás por posición (`.[0]`). Evidencia: un worker casi PATCHea un draft viejo vía `.[0]`; el release correcto se identificó por `tag_name`. Repo: missing (adyacente #1125).
- [ ] **6. `gh run rerun --failed` roto repo-wide en APAP** — falla con "cannot be rerun; its workflow file may be broken". Regla: el re-trigger determinista es un empty commit (`--allow-empty`) o un push fresco. Repo: documentado en #1146 (cerrado).
- [ ] **7. Docs-only fast lane como PATRÓN** — añadir a la skill: carril barato para PRs de docs; regla estricta de que TODOS los archivos cambiados sean docs; marcador fail-closed aceptado por el agregador; eventos de release inmunes. Evidencia: #1202 (merged). Repo: #1196 + #1202.
- [ ] **8. Los baselines de ratchet son invisibles a `ruff check` plano** — la disciplina pre-push de la skill debe nombrar `scripts/preflight.py` como el ÚNICO espejo local fiel (ejecuta los pasos de ratchet). Evidencia: primer push de un worker falló lint. Repo: #1119 (cerrado).
- [ ] **9. issue-spec: las 6 secciones canónicas son contrato del BODY del ISSUE también** — documentar los nombres exactos como contrato issue-side, no solo PR-side: `Problema y contexto`, `Evidencia verificable`, `Alcance y no objetivos`, `Criterios de aceptación`, `Plan de validación`, `Dependencias y riesgos`. Evidencia: una issue aprobada estilo checklist falló hasta que se aumentó el body a mano. Repo: missing (adyacentes #1184 y #1127).
- [ ] **10. Restricciones arch/Windows de la flota self-hosted** — la réplica minio es amd64-only (no arranca en runners arm64); los jobs Windows nunca se movibles. Corrección: cross-referenciar la skill `oracle-vps-github-runners` (HR-15 + receta de 7 pasos, aterrizada hoy). Repo: #1204 + #1214.
- [ ] **11. `silent no-op` en settings de pago** — PATCH devuelve 200 pero suelta el campo en una org free (`allow_auto_merge`). Regla: leer de vuelta todos los campos parcheados DOS veces + revisar el plan de la org. Repo: missing (adyacente #1148).
- [ ] **12. Envenenamiento por `.env`** — un `.env` gitignored en la raíz del repo filtró `APAP_*` a pydantic Settings → 5 rojos ambientales de test, solo locales. Regla: aislar el env de tests del `.env` de dev, o documentarlo. Repo: missing.
- [x] **13. Engram: anomalía de ruta de binario (HR-13 de `engram-project-hygiene`)** — VERIFICADO en vivo (2026-10-02): `go list -m -versions github.com/Gentleman-Programming/engram/v2` → última **v2.2.1**; **existe `engram/v3`** con **v3.0.0**; el binario local reporta `2.2.2-0.20261001201631-a43183c22445` (pseudo-versión /v2 sobre main tras v2.2.1). Conclusión: la línea `/v2` de HR-13 SIGUE siendo la actual; el binario `3.0.1` pre-existente no corresponde a ningún tag publicado (v2 → 2.2.1, v3 → 3.0.0), así que vino de otra ruta o de un build local. Corrección: HR-13 mantiene `/v2` y añade la nota de procedencia del binario (verificar `engram --version` contra tags publicados). Repo: none needed (solo skill-side).
- [ ] **14. OBSERVACIÓN DE HARNESS (sin fix de skill)** — 3 workers murieron en vuelo con "process cleanup unconfirmed after 1000ms; capacity quarantined": cuarentena de capacidad del harness. No es CI ni skill; se registra para el operador. Repo: none needed.
- [ ] **15. REGLA DE DOBLE ISSUE en el Protocolo de mejora continua de `ci-pattern`** — incorporar como paso 5-bis del bucle: "todo fix de CI tiene su contraparte en la skill" (directiva permanente 2026-10-02, registro Engram #8138). Evidencia: esta misma sesión — las mitades repo existían (#1146/#1112/#1187) y las skill-side no, que es exactamente por lo que esta issue se está creando. Repo: none needed (esta issue ES la contraparte).

### Alcance y no objetivos

Alcance: correcciones documentales en las skills canónicas del catálogo (`ci-pattern`, `engram-project-hygiene`, referencias/porting) según la checklist de arriba. No objetivos: código de CI de consumers, cambios de runtime, ni la distribución de skills (eso va por sus issues/PRs propios, p. ej. la ola #144). El ítem 14 queda expresamente fuera de alcance de skill.

### Criterios de aceptación

- Cada ítem de la checklist se cierra con un PR sobre la skill afectada, citado en el ítem.
- El ítem 13 solo se edita tras re-verificar los tags con `go list -m -versions` el día del cambio.
- El ítem 15 añade la regla como paso explícito del Protocolo de mejora continua, con la cita de la directiva y del registro Engram #8138.
- El ítem 14 no genera cambio de skill; permanece como observación operator/harness.

### Plan de validación

- Cada corrección aterriza como PR sobre la skill canónica con CI verde y se marca en esta checklist con su número de PR.
- Al graduar `ci-pattern` (#143 / ola #144), confirmar que los ítems 2, 4, 5, 6, 7 y 15 quedaron absorbidos o referenciados en la skill graduada.

### Dependencias y riesgos

- Cross-referencias repo-side de la sesión: ardelperal/APAP_WEB #1146, #1112, #1187, #1204, #1205, #1214 (higiene del pool), #1197, #1202.
- Cross-ref de skill: DysTelefonica/team-skills #144 (ola de portabilidad de `ci-pattern`; distinto alcance).
- Riesgo de etiquetado: este repo no tiene label `chore`/`type:chore`; se usa `documentation` como más cercana a la convención observada.
- Riesgo: los ítems marcados `missing` en repo (3, 5, 9, 11, 12) no tienen mitad repo aún; si el operador quiere la doble vía, hay que abrirlos en APAP_WEB.
