# Catálogo de fricciones destiladas

Fuente única: épica ardelperal/APAP_WEB#935 (2026-09-29/30) y el friction log
de la auditoría de origen (fuente de trabajo de la skill, no versionada en el
catálogo). Los registros acumulativos de Engram citados abajo se perdieron por
upsert y se recuperaron como entradas nuevas (HR-12). La entrada D1 no procede
de la épica: se destila de la lectura del código del agregador de origen
(DysTelefonica/team-skills#133); la entrada D2 tampoco: se destila de la
lectura del código de origen del patrón (DysTelefonica/team-skills#134);
ambas están marcadas «derivada del código» y no se han ejercitado en vivo.
Salvo indicación
de repositorio, todo `#N` se refiere a `ardelperal/APAP_WEB`. Cada entrada: la
fricción en una línea y su antídoto, con la regla de la skill que lo codifica.

| # | Fricción (evidencia) | Antídoto |
|---|---|---|
| A9 | Vulture sin instalar imprimía «OK (0 confirmed-dead)»: el único falso verde puro del CI (ardelperal/APAP_WEB#1142) | Gate fail-loud si el herramienta no midió (HR-3); guard ardelperal/APAP_WEB#1143 |
| A11 | Slice verde en todas las matrices locales, rojo en el job e2e dockerizado sin su seed fixture (ardelperal/APAP_WEB#1138) | El fixture viaja en el slice; comprobar también los jobs que solo corren en CI (HR-15) |
| B1 | El smoke de producción recibía 403 de Cloudflare por el User-Agent de urllib (ardelperal/APAP_WEB#1134, resuelto #1135) | Ejecutar de verdad cada gate que toca producción (HR-2); User-Agent propio (parámetro 7) |
| B2 | `strict` sin cola: cada merge ajeno invalida los PR abiertos («required status checks are expected», tres veces) | Auto-merge + update-branch activados; secuencia determinista de actualización (HR-17) |
| B3 | La suite de tests local no ejecuta los pasos de lint: tres PR llegaron a CI con fallos que local no veía (ardelperal/APAP_WEB#1082, #1133, #1119) | Preflight canónico con paridad total (HR-4); `scripts/preflight.py` |
| B4 | Mensajes del gate que no dicen la causa real («missing or empty section» cuando el problema era el nivel de encabezado) | Mensajes con la causa exacta y el arreglo esperado (HR-13) |
| B11 | GitHub no registró nunca `Closes #1119` en #1145: el gate exigía algo que el cuerpo ya tenía | Verificar `closingIssuesReferences` tras crear; excepción declarada + cierre a mano auditable (HR-7, HR-13) |
| B12 | Fallo transitorio del runner confundido con fallo de código; rerun quemó ~10 min de espera | Clasificar por paso vía API antes de decidir; rerun solo para transitorios (HR-9, §3) |
| B13 | Nombre de paso truncado por un `#` sin comillas en el workflow | Drift guard / actionlint antes de confiar en nombres de paso |
| F-001 | El ratchet de ruff evalúa rulesets que el `ruff check` local no corre: rojo en CI, verde en local (ardelperal/APAP_WEB#1111) | Preflight que reproduce el job, no un subconjunto curado (HR-4) |
| F-002 | El ratchet pide «lock in the improvement» pero bajar la baseline es un edit manual | Comando de regeneración de baseline; ratchet shrink-only (HR-15) |
| F-003 | Un fallo de raíz se enmascaraba como 7 fallos del agregador `required` | Agregador que separa causa raíz de skips en cascada (HR-13) |
| F-004 | `size:exception` era una danza de etiquetas aplicadas tarde que no reevaluaba el gate | Excepción como campo de datos del cuerpo del PR (HR-1, HR-8) |
| F-005 | Reanudar una revisión interrumpida exigía hashes y tokens internos a mano | El arnés de review asume interrupciones; la skill de CI no lo disimula |
| F-006 | Entornos locales sin el intérprete de python localizado y docs con intérpretes mezclados | El preflight canónico abstrae el intérprete; un solo comando documentado (HR-4) |
| F-007 | Un worker desatendido no puede commitear: la política pide aprobación interactiva | Contrato de dos fases: worker deja staged + evidencia; el orquestador commitea tras verificar |
| — | Tres PR (#1156, #1157, #1159) llegaron a CI con el gate issue-spec en rojo por formato acortado de la issue | Contrato canónico de issue completo y etiqueta de aprobación al crearla (HR-1) |
| — | En #1145 y #1150 las etiquetas se aplicaron tras crear el PR y el gate no se reevaluó | Etiquetas en el comando de creación (HR-6) |
| — | Palabra de cierre en el título de #1138 cerró la issue antes de tiempo | Cierre solo en el cuerpo del PR punta (HR-7) |
| — | `rerun --failed` re-ejecuta el SHA original: reproduce el mismo rojo y quema un ciclo | Push dispara CI nueva; rerun solo para transitorios; `workflow_dispatch` si el workflow cambió (§3) |
| — | Dos watchers zombis con autoridad de merge sobrevivieron a su sesión (2026-09-29) | Cero vigías: auto-merge y una sonda única (HR-9) |
| — | El upsert de Engram sustituyó el registro acumulativo y perdió 10 de 11 entradas | Registros acumulativos sin clave de upsert (HR-12) |
| — | `gh pr edit` y `gh variable get` rotos en la versión instalada; PATCH de settings lee de vuelta valores obsoletos | API REST directa y lectura de vuelta antes de concluir (HR-17) |
| — | 18 fallos falsos al ejecutar los tests de main contra un deploy anterior (test-vs-deploy skew) | Batería desde worktree en la revisión desplegada; veredicto sobre el SHA de `/healthz` (HR-10) |
| — | `actionlint` cazó `services.minio.command`, clave inexistente en Actions (`ci.yml:1251`) | Drift guard mecánico del propio workflow (benchmark T3) |
| D1 | Un job cableado en `needs` y ausente del conjunto conocido del evaluador no entra en ningún cubo del informe: si falla, el agregador sale limpio; a la inversa, un job añadido al workflow sin cablear nunca se evalúa (DysTelefonica/team-skills#133; derivada del código, no ejercitada en vivo) | Paridad three-way obligatoria: `jobs(workflow) − {agregador}` = `needs` = conjunto conocido; una clave de `needs` desconocida es violación y no se ignora; la exclusión a propósito se declara como dato con su motivo (HR-29) |
| D2 | Un evento que no evalúa el PR (`push`, `workflow_dispatch`, `schedule`) publica los nombres de checks requeridos en verde sobre el mismo SHA: el job de tamaño reporta total=0 y termina con éxito, y el agregador acepta el skip de issue-spec fuera de `pull_request` (DysTelefonica/team-skills#134; derivada del código, no ejercitada en vivo) | Los nombres requeridos se publican solo desde un evento que evalúa el PR; en cualquier otro, otro nombre de contexto o fallo — nunca éxito sin evaluación; el fallback manual resuelve el PR desde el SHA o no publica nombres requeridos (HR-30, HR-17) |

Regla de lectura: una fricción solo existe con incidente citado. La segunda
ocurrencia de cualquiera de estas entradas se automatiza; no se arregla a mano
otra vez (HR-11).
