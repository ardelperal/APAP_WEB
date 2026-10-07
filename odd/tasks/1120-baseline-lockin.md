# 1120 (tramo 2/2) — lock-in real del baseline de ruff y documentación

- **Issue:** https://github.com/ardelperal/APAP_WEB/issues/1120 (cierra aquí)
- **Rama:** `chore/1120-baseline-lockin` sobre `origin/main` @ `5f643d7` (tramo 1: PR #1166).

## Contenido

- `scripts/check_ruff_ratchet.py`: lock-in real ejecutado con `--update-baseline` sobre el árbol: 8 cambios (ARG001 31→28, C901 19→18, PLR0911 12→11, PLR0912 12→9, S101 6→4, S603 2→eliminada, SIM105 15→14, SIM108 6→4). Antes: 437 hallazgos, 8 notas de mejora activas. Después: 437 hallazgos, 0 notas. TRY003 queda pendiente (está exactamente en su baseline; no hay mejora que lockar).
- `docs/quality/ci-gate-inventory.md`: fila del gate actualizada con el flujo de lock-in y la fricción resuelta (#1120).
- `docs/quality/hardening-roadmap.md` y `odd/tasks` previstos en la superficie aprobada: `hardening-roadmap.md` no queda tocado porque la fricción F-002 (`wu5-scripts-findings.md`) nunca se versionó en el repo y el documento no rastrea este gate.

## Validación

- Suite del ratchet verde; preflight 20/20; `check_alantyle` OK sobre el doc tocado.
