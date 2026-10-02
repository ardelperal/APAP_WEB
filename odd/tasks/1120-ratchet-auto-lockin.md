# 1120 — ci: ratchet auto lock-in (`--update-baseline`)

- **Issue:** https://github.com/ardelperal/APAP_WEB/issues/1120 (`status:approved`, `type:chore`)
- **Rama:** `chore/1120-ratchet-auto-lockin` (PR 1, mecanismo + tests) y `chore/1120-baseline-lockin` (PR 2, lock-in real + docs), sobre `origin/main` @ `faa6c2c`.
- **Origen:** adopción del trabajo abandonado en el worktree `chore/1120-ratchet-lockin` (@ `cec3133`, sin commits). Procedimiento del handoff `odd/HANDOFF-ci-2026-09-30.md` §4.2.

## Alcance

- `scripts/check_ruff_ratchet.py`: modo `--update-baseline` shrink-only que reescribe las constantes del bloque `BASELINE` al conteo medido (nunca sube; regla a cero se elimina; regla desconocida se rechaza).
- `tests/test_ruff_ratchet.py`: tests RED/GREEN del modo (baja exacta, rechazo atómico byte-idéntico, eliminación a cero, preservación de comentarios, idempotencia, cableado CLI).
- PR 2: lock-in real de las 9 mejoras activas + documentación del flujo.

## Decisiones frente al diff abandonado

- Se re-corta el mecanismo en versión compacta en lugar de adoptar las ~350 líneas de reescritura regex: el padre autorizó simplificar. El diff abandonado, además, contradecía sus propios tests (borraba clusters de comentarios "about-rule" que un test exigía conservar verbatim).
- Regla del re-corte: las líneas de comentario del bloque `BASELINE` nunca se tocan (registro histórico); solo se reescriben valores y se eliminan entradas a cero.
- El diff abandonado no manejaba reglas medidas ausentes del `BASELINE`; el re-corte las rechaza (`UpdateRefusedError`) coherente con la rama "new rule must report zero" de `compare()`.
- Presupuesto: mecanismo + tests ≈ bajo las 400 líneas; el lock-in real + docs van en PR 2 encadenado.

## Validación

1. RED: test con baseline simulado mayor al conteo real exige reducción exacta y nunca subida.
2. GREEN: suite completa `uv run --extra dev pytest`, mypy, ruff, preflight, vulture.
3. Lock-in real `--update-baseline` y commit del diff del baseline (PR 2).
