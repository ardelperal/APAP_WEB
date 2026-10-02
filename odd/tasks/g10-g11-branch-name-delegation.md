# Tarea: mecanismos deterministas G11 + G10 + fix G9 (ci-pattern)

- **Fecha:** 2026-10-02
- **Origen:** huecos G11, G10 y G9 de
  [`odd/skill-ci-portable/portable-assets-inventory.md`](../skill-ci-portable/portable-assets-inventory.md)
  (fallos de orquestación observados en la sesión: 5× rama sin número de
  issue, repo equivocado en un encargo, superficies/SHAs/conteos prescritos
  de memoria, watch loop estancado).

## Entregado

1. **G11 — `skills/ci-pattern/assets/branch-name.sh`** (nuevo): generador y
   validador determinista de `<tipo>/<N>-<slug>`. Subcomandos `new`,
   `validate`, `slugify`, `self-test`. La regex es parámetro: `--pattern` o
   `--gate-script <check_branch_name.py>` (extracción best-effort de la
   primera cadena tras `re.compile(`); conversión documentada de grupos sin
   captura de Python a regex extendida POSIX. Slug determinista (minúsculas,
   sin acentos, guiones) y
   tope de longitud (`--max-len`, por defecto 100). Auto-test de 12 casos
   ejecutable sin el repo destino.
2. **G10 — `skills/ci-pattern/references/delegation-template.md`** (nuevo):
   plantilla canónica de encargo con 7 bloques (Repo, Base y tip, Worktree,
   Superficies de edición permitidas, Hechos en vivo a verificar, Parada,
   Plazo y progreso); cada dato exige comando + salida + `verified_at`;
   entrada que no resuelve es defecto del encargo, no errata del worker;
   sin watchers (HR-9/HR-23) y reporte de una línea por transición.
3. **G9 — corrección del esquema de política en
   `skills/ci-pattern/assets/parameters.md`**: el doc describía
   `policy_version`/`activation_snapshot`/`grandfathered_entries` (y, en la
   copia canónica, `findings_exit_code`/`relaxation`), que ningún fichero ni
   validador implementa. Esquema canónico corregido al implementado y
   validado por `scripts/preflight.py` (`ALLOWED_GATE_KEYS` =
   {`enforcement`, `reason`, `dormant_since`}, issue #1168) y
   `tests/test_ci_gate_policy.py`; las extensiones no implementadas quedan
   marcadas `documented-only` (HR-34) con aviso de que hoy invalidarían el
   fichero.
4. **Cableado en `skills/ci-pattern/SKILL.md`**: HR-35 (rama generada, nunca
   prescrita de memoria) y HR-36 (toda delegación usa la plantilla; toda
   prescripción lleva su comando de verificación), dos filas nuevas en §3
   Decision Gates, paso 2 de «Operación por unidad de trabajo», dos filas en
   §6 Anti-patterns y referencias en §8. Versión 0.3 → 0.4.

## Doble escritura

- Canónica: `~/personal-skills/personal/ardelperal/ci-pattern/`
  (repo `DysTelefonica/team-skills`, rama `main`) — edits en el árbol de
  trabajo; commit/push a cargo del orquestador.
- Consumer: `skills/ci-pattern/` de este repo — el PR debe usar `Refs`
  (no `Closes`) y rama generada con el propio `branch-name.sh`.

## Verificación

- `sh skills/ci-pattern/assets/branch-name.sh self-test` → 12 pasan, 0
  fallan (exit 0), en ambas copias.
- `--gate-script scripts/check_branch_name.py` extrae la regex real y
  valida `chore/7-runner-deploy-spof` (OK) y rechaza
  `chore/runner-deploy-spof` (exit 1 con la forma esperada).
- `check_alantyle` sobre los docs tocados: ver salida del worker.

## Riesgos / pendientes

- La copia canónica va por delante de la de este repo (HR-29–34, parámetros
  14–17, fricciones D1–D9, `assets/host-readback/`); el PR de este repo
  debe sincronizar la copia canónica completa, no solo este delta.
- El post-commit hook de `~/personal-skills` está retirado (exit 0, commit
  a065177): no propaga nada; la propagación al consumer es manual
  (`propagate-team-skills.ps1`) o vía PR como esta tarea.
