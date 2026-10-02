# Veredicto de gates del inventario de CI

Modelo de salida del paso de auditoría (§4 de la skill): cada gate del
inventario recibe un veredicto con la evidencia que lo sostiene. Veredictos
posibles: **se queda**, **se refuerza**, **se duerme** (HR-18, R15), **se
retira** (solo con medición que pruebe que no hay candado que conservar).
Desde HR-32, cada control registra además **el test que lo ve fallar**: la
prueba de que ejecuta su lógica contra un fixture que viola la regla y observa
su veredicto. Un control sin fixture violador no se declara como control: se
clasifica `documented-only` hasta tenerlo.

Estado: auditoría inicial de `ardelperal/APAP_WEB` (2026-09-30); lo no
verificado se marca. Las fricciones citadas se detallan en
`references/fricciones.md`.

| Gate | Veredicto | Test que lo ve fallar | Base |
|---|---|---|---|
| `required` (agregador) | Se queda, reforzado | Suite de paridad del asset (`assets/required-jobs/`) | Falla cerrado con matriz de skips esperados; causa raíz separada de skips en cascada (F-003, ardelperal/APAP_WEB#1118) |
| `pr-size` | Se queda, reforzado | Sin verificar | Excepción como campo de datos del cuerpo, no etiqueta (ardelperal/APAP_WEB#1141; R2) |
| `branch-name` | Se queda | Sin verificar | Deriva la issue del nombre de rama; base del trazado determinista (ardelperal/APAP_WEB#1111) |
| `issue-spec` | Se queda, mensaje a mejorar | Sin verificar | Trazabilidad determinista rama + etiquetas + cierre (B4, B11) |
| `integration` (Postgres real) | Se queda | Sin verificar | Verifica comportamiento que el mock no cubre |
| `security` (pip-audit, gitleaks, trivy config) | Se queda | Sin verificar | Corre en GitHub-hosted, no en la flota self-hosted |
| `lint` + `ruff`/`mypy` | Se queda | Sin verificar | Con paridad de preflight (ardelperal/APAP_WEB#1145) y actionlint pendiente de añadir |
| Cobertura | Se refuerza | Sin verificar | Solo unit con dobles; 85 % sobre `app` y `migration` |
| e2e de PR | Se refuerza | Sin verificar | Seis tests, ninguno envía formularios aún |
| `mutation` / `security-deep` | Se refuerza (dormible) | Sin verificar | Solo en tag o cron; candidatos al policy file de HR-18 |
| `check_vulture_guard` | Se queda (arreglado) | Sin verificar | Fail-loud desde ardelperal/APAP_WEB#1143 (A9 cerrado); baseline shrink-only (HR-15) |
| `check_mutation_sites` | Se duerme (R15) | Sin verificar | BASELINE 464 y subiendo, sin defecto real cazado; dormido en la era #1167 |
| `check_crap` | Se duerme (R15) | Sin verificar | Informativo sin defecto real cazado; dormido en la era #1167 |
| `check_alantyle` | Se duerme (R15) | Sin verificar | Bloqueante de estilo de docs; falló por una palabra en mayúsculas (ardelperal/APAP_WEB#1133); informativo #1151 |
| Docstrings (balance/cobertura) | Se duerme (R15) | Sin verificar | Informativos, sin defecto real cazado |
| `test_ci_workflow.py` | Se simplifica | Subcadenas del fuente: no cuenta como test (HR-32) | El fichero más editado del repo por cambios de workflow |
| `actionlint` en `lint` | Falta | — | Cazó `services.minio.command`, clave inexistente en Actions (`ci.yml:1251`) |
| Job de preflight en CI | Falta | — | El preflight existe (#1145); falta el paso que lo reproduce en el job |

## Nota sobre R15 (dormir, no retirar)

La corrección de la épica: un gate pasado a informativo sin policy file pierde
el candado construido. El patrón dormant conserva el motor probado y hace de la
re-activación un cambio de datos con review. Regla R15 destilada en la
auditoría de origen (la fuente de trabajo de la skill no se versiona en el
catálogo); forma del policy file en
`assets/parameters.md`; origen del patrón en
`references/benchmark-gentle-ai.md` (idea T1).

## Criterio de decisión

Un gate se retira solo cuando una medición prueba que no cazó ningún defecto
real **y** no conserva candado ninguno que valga la pena dormir. Si duda,
duerma el gate (HR-18): el coste de un gate dormido es una línea de policy; el
coste de reconstruir un gate retirado es un PR entero.
