# 1163 — chore(deps): subir virtualenv a 21.14.1 (PYSEC-2026-4011/4012/4013/4014 en 21.7.9)

- Issue: https://github.com/ardelperal/APAP_WEB/issues/1163 (type:chore)
- Origen: job `security` de CI rojo en base `main` — pip-audit reporta virtualenv 21.7.9 con PYSEC-2026-4011 (fix 21.7.12), PYSEC-2026-4012 (fix 21.7.11), PYSEC-2026-4013 (fix 21.7.13) y PYSEC-2026-4014 (fix 21.7.12). Evidencia: run 36747068968 del PR #1151 (`Found 4 known vulnerabilities in 1 package`). Es la segunda ocurrencia del patrón en el día (la primera fue urllib3 en #1156); todo PR abierto pasa rojo sin culpa propia.
- Rama: `chore/1163-virtualenv-21-14-1` en worktree `/home/ubuntu/repos/apap-app-worktrees/chore-1163-virtualenv-21-14-1`.
- Superficies: solo `uv.lock` (bump quirúrgico vía `uv lock --upgrade-package virtualenv`; `pyproject.toml` no cambia — virtualenv es transitivo de `pre_commit`). El diff añade dentro de la entrada de virtualenv su nueva dependencia upstream `packaging`; ningún otro paquete del lock se mueve.
- Validación: `uv run --extra dev pytest` (5233 passed, 21 skipped), `uv run --extra dev python -m mypy` (0 en 377 ficheros), `uv run --extra dev ruff check .`, `.venv/bin/python scripts/check_vulture_guard.py` (baseline 5), `.venv/bin/python scripts/preflight.py` (19/19). Diff de `uv.lock`: 4+/3−, solo la entrada de virtualenv (versión 21.7.9 → 21.14.1, hashes y dependencias upstream).
- Cierre: PR con `Closes #1163`; el job `security` del PR debe quedar verde, probando que las 4 advisories desaparecen.
