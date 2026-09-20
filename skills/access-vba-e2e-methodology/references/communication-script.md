# Communication script with the user

From observing the forms-thin-refactor session (which had timing errors). Keep messages short, sequential, and verifiable. Never batch multiple "done" claims into one message. Never say "I've applied the change" without listing files and test results — the user needs concrete numbers to verify.

## Scripted moments

- **On starting a session** (after reading `AGENTS.md` + pre-flight A/B/C): one short message.
  > "He leído AGENTS.md y hecho el pre-flight. El proyecto tiene X forms con llamadas inter-form, Y átomos en `tests.vba.json`, y el binario está [sano/roto]. ¿Sigo con [epic]?"

- **After `dysflow.import_modules` of a MODULE-ONLY change** (no forms): the agent compiles itself.
  > "Importado [module]. Compilo en Access (Debug ▸ Compile) — antes `dysflow.compile_vba` (esa tool fue removida en v1.19.0). Confirmo con el humano. Corro `dysflow.test_vba testsPath=tests/tests.<area>.json`."

- **After `dysflow.import_modules` of a change that TOUCHES FORMS**: hand off to the user.
  > "Importado [module/form]. Como toca formularios, compilá en Access VBE (Debug → Compile) y decime 'OK' o pegá el error exacto."

- **After `test_vba` returns green**: concrete numbers.
  > "25/25 átomos verdes. Sin regresiones en `tests.vba.json` (407/407). ¿Commit en `fix/<branch>` y push a `staging`?"

- **After `test_vba` returns red**: the failing atoms.
  > "X/X verdes. Fallan: [list]. Pegá el `error.details.failures[]` y lo arreglo."

- **After commit**: 
  > "Commit en [branch] con hash [sha]. No push sin tu OK."

## Silence handling

If the user is silent for more than 5 minutes after a prompt, send ONE reminder. Do not send multiple. Do not assume the user is offline — they may be compiling.
