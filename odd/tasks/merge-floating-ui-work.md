# merge-floating-ui-work — aterrizar trabajo UI flotante (#901 + #823 a11y)

## Contexto
Main ya contiene el stepper #821 (64e042e, 9880ebe), el wizard #823 (19acb2e, 0686cc5) y la
death-date fix (PR #985). Quedan dos piezas genuinamente sin aterrizar y worktrees residuales.

Política: push directo a main prohibido (§15.5); standing auth §15.6 cubre merge de PRs con
CI verde; merge --no-ff; rama remota se conserva; worktree local se poda.

## Tareas

### 1. fix #901 — burger móvil (branch bugfix/901, dirty, sin PR)
- Renombrar a `fix/901-burger-hidden-class` (bugfix no es tipo válido).
- Los cambios dirty (nav-burger.js toggle class hidden + test e2e) van sobre base vieja
  (b4f7246); reaplicar sobre origin/main verificando que el markup de #868 sigue igual.
- Commit convencional, PR `Closes #901`, CI verde, merge --no-ff con run URL.

### 2. feat/823-wizard-a11y-layout — layout sidebar + E2E
- El tip a11y-layout/e2e-stepper-tests (árboles idénticos) es stale: merge completo
  revertiría trabajo ya en main (close_all_on_death, check_crap, etc.). NO mergear la rama.
- Extracto genuino (461 líneas > 400 → size:exception con justificación):
  - app/templates/animales/form.html (layout sidebar, 41 líneas con css)
  - tailwindcss/styles/app.css + app/static/css/output.css (generado)
  - tests/e2e/test_animales_new_stepper.py (420 líneas, nuevo, NO está en main)
- form-stepper.js es idéntico main↔tip (diff vacío) — sin riesgo de JS.
- Rama nueva desde origin/main, aplicar extracto, correr tests localmente, PR, CI, merge.

### 3. Podar worktrees muertos
- feat/823-animal-create-wizard (mergeado vía PR #984), feat/823-stepper-animales-new
  (tip = 90eeb3c, ya en main), tips a11y/e2e tras extraer, 914/915 (mergeados #982/#983),
  chores 968-971 (mergeados), chore-967-gitleaks (en main).
- `git worktree remove` + `git worktree prune`; ramas locales `git branch -d`;
  refs remotos SE CONSERVAN.

## Evidencia
- Tarea 1 (#901): rama fix/901-burger-hidden-class, commit 2796105, PR #989, CI verde
  (run 36178786508; re-run tras update-branch), merge --no-ff 63c6b2b. make verify local:
  4730 passed / 19 skipped / 1 xfailed.
- Tarea 2 (#823 a11y): rama feat/823-wizard-a11y-layout, commit bf171a6, PR #990 con
  size:exception (525 líneas, justificada en el body), CI verde (run 36234304230),
  merge --no-ff 9080065. extracto verificado: form-stepper.js idéntico main↔tip;
  output.css superset estricto (0 clases perdidas, 5 nuevas).
- Tarea 3: podados 16 worktrees + ramas locales; refs remotos retenidos. Se preservaron
  task docs untracked (821, 823-stepper) copiándolas a odd/tasks/. Se respetaron los
  worktrees de la ola CI (894, 902, 929, 933, 956, 957, 973) y el WIP de #914.
- Nota: la otra sesión mergeó PR #994 (mismo test E2E, byte-idéntico) en paralelo;
  convergencia sin conflicto. main @ 9080065.
- Blocker local documentado: e2e locale degradado (test_landing 9/10 fallan en main sin
  parche); los 6 skips del suite nuevo requieren APAP_E2E_AUTH_SECRET (solo CI).
