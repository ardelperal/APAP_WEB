# Informe de investigación 2 — segunda pasada sobre el CI de `Gentleman-Programming/gentle-ai`

> **Propósito:** continuar la ingeniería inversa iniciada en `odd/skill-ci-portable/gentle-ai-ci-research-report.md` (en adelante **Informe 1**) buscando **lo que el Informe 1 no vio**, y cerrar la lista de siete puntos que el propio Informe 1 dejó en "Sin verificar". El entregable son **deltas deduplicados**: toda idea ya presente en T1-T9, COL1-COL5 o NC1-NC6 del Informe 1 se omite o se marca explícitamente como *refinamiento*.
>
> **Fecha de corte:** 2026-09-30. HEAD de `gentle-ai` = `4de74bd`. El clon shallow del Informe 1 se reutilizó y se profundizó: `git fetch --deepen 1000` lo llevó de 256 a **3910 commits** y de 9 a todos los tags históricos (`v1.0.4` en adelante).
>
> **Método y sus límites.** Corpus en `/tmp/gentle-ai-research`. Toda la investigación es **read-only** sobre `gentle-ai`: no se abrieron issues, PRs, estrellas ni comentarios; las llamadas `gh api` consultaron metadatos públicos (workflows, rulesets, labels, runs, workflows por rama). No se ejecutaron los comandos destructivos prohibidos. CodeGraph **no** se inicializó porque el clon vive en un directorio temporal, y la política de la herramienta prohíbe indexar allí; se usó lectura de ficheros, `git` y `gh`. Cada afirmación lleva `fichero:línea` o URL de commit/run, y se distingue **verificado leyendo** de **verificado ejecutando**. Lo ejecutado aparece con el comando exacto.
>
> **Convención:** castellano peninsular formal (usted), tercera persona del agente.

---

## Resumen ejecutivo

La segunda pasada encuentra **28 deltas** y **cierra los 7 puntos pendientes** del Informe 1 (uno de ellos sólo parcialmente, y se dice por qué). Los hallazgos se agrupan en cinco familias:

1. **El contrato del proveedor de review tiene contenido, no sólo un número de versión.** El Informe 1 lo trató como "un fichero `CONTRACT_SEMVER` que el release lee" (IDEA T8, marcada "hoy no transferible"). La realidad es un **bundle de datos generado y verificado** por `internal/providercontractbundle` con inventario cerrado, hashes SHA-256 por fichero, vectores canónicos derivados del propio esquema, rechazo de claves JSON duplicadas, validación de cabeceras tar crudas antes de extraer, y **reglas de compatibilidad por SEMVER** que excusan de un campo a los contratos anteriores a su introducción. Además conviven dos familias: el bundle de proveedor (v1.2.0) y el contrato de integración `review-integration/v1` (congelado, no borrado, con horizonte de soporte declarado sin resolver) y `/v2` (vivo). Esto sí es transferible, y de forma barata.

2. **El bench es la pieza más transferible del repo, y su mecanismo de cobertura por fin está verificado.** 48 journeys core (no 57: el README está desactualizado), un **manifiesto ordenado de IDs** que sustituyó a un contador entero tras un incidente medido, dos tests de meta-cobertura (colisiones de ID con ambos ofensores nombrados; `journeySources` ↔ `Journeys()`), un `validateCorpus` que obliga a declarar la precondición de review de cada journey, y fixtures que **prueban su propio edge case** antes de confiar en el resultado. El CI ejecuta el corpus entero y después afirma con `jq` que 13 journeys concretos terminaron exactamente una vez.

3. **Hay 3 ejes (`axis`) registrados, no 4, y dos de los que documenta el README ya no existen.** Verificado ejecutando: `unknown axis "damaged-store" (registered: compatibility, model-picker, transition, or ``all``)`. `axis_real_world.go` quedó reducido a un stub de una línea y `axis_damaged_store.go` conserva 1.614 líneas compiladas pero inalcanzables. Es una divergencia doc-código real en un repo que hace de la honestidad su tesis.

4. **El repo se prueba a sí mismo por encima del CI:** tests Go que **leen `.github/workflows/*.yml`** y afirman invariantes estructurales (ningún job requerido puede saltarse el guard de formato; todo test de Windows está reclamado por exactamente un shard; el pin de OpenCode aparece una sola vez), y tests que **ejecutan los scripts de release con `gh` y `minisign` falsos** en un PATH temporal, afirmando la superficie exacta de llamadas y el fail-closed. Es el patrón de mayor relación "genio por línea".

5. **La filosofía de test de runtimes de IA está escrita y es la cosa más copiable del repo:** *"keep the runtime real, replace only its reasoning"* — un `httptest` que habla el protocolo OpenAI como provider local, con `edit: deny` para forzar que toda mutación pase por el CLI, y un fixture que **inspecciona la petición entrante** y falla si la evidencia llega fuera de orden.

Se cierran además, con datos: la tasa real de fallo de `ci.yml` (92/100 en `main`, 24 % en PRs), el motivo exacto del desdoblamiento de la suite Windows (un timeout de job de 30 min rodeando un step de 35), la inexistencia de automatización de etiquetas (`type:*` y `status:approved` son humanas), y el uso real de `promote-stable-rc.yml` (4 ejecuciones en total).

---

## 1. Deltas encontrados

Cada delta lleva: qué es, evidencia, y veredicto de transferibilidad. Los que además son ideas copiables se desarrollan en §3; aquí sólo se enuncian.

### Familia A — El contrato del proveedor de review (contenido, no sólo versión)

#### D1. El bundle del contrato de proveedor es generado, cerrado y verificado contra el registro canónico — **verificado leyendo**

`contracts/review-provider-contract/CONTRACT_SEMVER` contiene `1.2.0` (una línea, un `MAJOR.MINOR.PATCH`, terminada en `\n`; `ReadContractSemver` rechaza cualquier otra cosa, `internal/providercontractbundle/bundle.go:230-241`). El bundle lo produce `providercontractbundlecmd generate --out <dir>` (`internal/providercontractbundlecmd/main.go:31-47`) y se empaqueta como meta-archivo GoReleaser (`gentle-ai-review-provider-contract-{{ .Env.PROVIDER_CONTRACT_SEMVER }}`, `.goreleaser.yaml:44-73`). Lo importante no es el número, es **lo que se promete dentro**:

- **Tres roles cerrados** con esquema de resultado y prompt propios: `lens`, `refuter`, `targeted-validator` (`internal/reviewerprovider/contract.go:12-16`, `:151-176`). El host recibe sólo un `Invocation` opaco: *"Hosts receive only an opaque Invocation; they cannot select a role, schema, capability, or storage slot"* (`contract.go:8-10`).
- **Un rol puede tener prompt largo y verificado.** El prompt del validador (`targetedValidatorPromptInstruction`) es de ~40 líneas y su comentario explica dos incidentes reales (#3380, #4266). El bundle comprueba además que `orchestration/pi.md` **contiene literalmente** ocho frases del ciclo de vida y **no contiene** ninguna ruta cruda `gentle-ai review ` salvo el kill switch (`bundle.go:196-215`). Es decir: el texto del contrato se valida contra el texto del skill que el instalador reparte.
- **Inventario cerrado y hasheado.** `bundleFixedFileCount = 8` (README, manifest, y los pares esquema/vector de los tres roles) más un fichero por runtime de orquestación cerrado (`orchestrationRuntimeIdentities = ["pi"]`, `bundle.go:100-108`). El manifiesto lleva `sha256` de cada fichero y `Generate` vuelve a leer los mismos bytes que `Verify` (`canonicalOrchestrationEntries`, `bundle.go:158-193`): *"the shipped bytes cannot drift between generation and verification"*.
- **El vector canónico se extrae del propio esquema.** `canonicalVector` toma `examples[0]` del JSON Schema, lo compacta y lo escribe como `vectors/<rol>.json` (`bundle.go:369-389`). Un esquema sin ejemplo es un refuso, no un test.
- **Verificación paranoica antes de extraer.** `VerifyArchive` valida tamaño, tipo de fichero (nada de symlinks), que el gzip no tenga datos de cola, las **cabeceras tar crudas** (dos bloques cero de terminador, sin datos detrás, tipo regular, tamaño octal, sin exceder el número máximo de entradas) y sólo entonces lee el tar (`bundle.go:390-500`). El manifiesto se decodifica con rechazo de claves JSON duplicadas y `DisallowUnknownFields` (`bundle.go:641-707`).
- **Reglas de introducción de campos por SEMVER.** El campo `runtimes` aparece en `1.1.0` y `orchestration` en `1.2.0`. `contractSemverAtLeast` es la única comparación: un bundle anterior al campo queda **excusado** de la comprobación de igualdad exacta, y un bundle que declare el campo siendo anterior falla (`bundle.go:86-104`, `:565-575`, `:610-640`). El comentario distingue explícitamente "vacío por compatibilidad" de "vacío por corrupción" (#3249/#3256, #4056).
- **Fail-closed sobre la versión del entorno.** Si `PROVIDER_CONTRACT_SEMVER` está definida y no coincide con el fichero, `generate` falla (`providercontractbundlecmd/main.go:33-36`).

*Transferibilidad:* alta y barata para nosotros, aunque hoy no tengamos API pública. Lo copiable es la **forma**: fichero de versión versionado + generación + verificación que relee los mismos bytes + regla de introducción de campos por versión. Aplicable, por ejemplo, al JSON que devuelven nuestros propios scripts de CI (`check_release_evidence.py`) o a cualquier contrato interno que un consumidor lea.

#### D2. `contracts/review-integration/v1/FREEZE.md` — congelar, no borrar, con horizonte de soporte declarado y sin resolver — **verificado leyendo**

El fichero declara la congelación de 51 ficheros (27 fixtures + 24 esquemas) con tres piezas notables (`contracts/review-integration/v1/FREEZE.md`):

1. **"Frozen, not deleted"** por decisión D3 con alternativa rechazada explícita: *"A pinned adapter release (e.g. a version-pinned gentle-pi) may still call v1 mid-upgrade. Deleting v1 in this wave would break such a consumer without warning."*
2. **La retirada requiere un cambio separado y fechado**, nunca se empaqueta en la ola que borra código: *"Deletion requires a SEPARATE, later, dated change once the support horizon below is proven satisfied — never bundled into this deletion wave."*
3. **El horizonte de soporte queda explícitamente sin resolver**, citado como pregunta abierta de diseño. El documento no lo finge resuelto.
4. **Evidencia de salida concreta y comprobable:** hash de contenido sin cambios desde el commit de congelación (`git diff --stat` contra ese commit) y ningún fichero nuevo de `internal/` importándolo para el linaje nuevo.

*Transferibilidad:* alta. Es el hermano mayor de nuestro `BASELINE` shrink-only: un documento que congela bytes con **criterio de salida verificable** y deja el horizonte abierto en lugar de inventarlo.

#### D3. Dos familias de contrato conviven con versiones independientes — **verificado leyendo**

No hay un "contrato", hay dos con ciclos de vida distintos: `review-provider-contract` (SEMVER propio, 1.2.0, bundle firmado, lo que un host externo firma) y `review-integration/{v1,v2}` (v1 congelado, v2 vivo, empaquetado dentro de los archivos del binario y verificado por `scripts/test-review-contract-package.sh`, que además comprueba que ningún archivo de release pierda ficheros de contrato ni cambie su hash). El contrato de proveedor se publica **aparte** del binario; el de integración viaja **dentro** de él. *Transferibilidad:* media; el principio "distinguir contrato externo publicado de contrato interno empaquetado" sí es útil.

### Familia B — El bench: corpus, cobertura y ejes

#### D4. Cubrimiento del bench resuelto: manifiesto, colisiones y precondición obligatoria — **verificado leyendo y ejecutando**

El mecanismo de cobertura que el Informe 1 dejó "sin verificar" existe y es de tres capas:

1. **`validateCorpus`** (`bench/runner.go:781-800`) rechaza el run entero, antes de conducir nada, si algún journey no declara `Review: reviewOptedIn | reviewUntouched`. El comentario explica el coste de no tenerlo: el corpus medía el ciclo de review "sólo porque el default del producto decía que sí", y el día que cambió *"those journeys did not fail — they quietly measured a different flow"*.
2. **Manifiesto ordenado de IDs** (`bench/testdata/journeys.manifest`, 48 líneas) con `TestRegisteredJourneysMatchTheManifest` (`bench/journeys_manifest_test.go:44-103`). Sustituyó a un contador entero por un motivo **medido**: el 2026-08-11 los PR #3037 y #3038 movieron ambos el contador 93→94 y `main` quedó rojo en 95 con baseline 94; casi vuelve a pasar el mismo día. El test documenta un experimento de merge a tres bandas: dos ramas que añaden journeys cuyos IDs ordenan separados mergean limpiamente; IDs adyacentes **conflictúan**. *"the manifest does not always merge cleanly, and claiming otherwise would be wrong. What it always does is refuse to be silently wrong."*
3. **Colisiones de ID nombrando ambos ofensores** (`bench/journeys_id_collision_test.go`): un ID duplicado y un **prefijo numérico** compartido (`j110-alpha` vs `j110-beta`) fallan citando los dos ficheros `journeys_*.go`. Además `TestJourneySourcesCoverTheWholeCorpus` ata la tabla `journeySources()` a `Journeys()`: un fichero nuevo no registrado hace fallar el test, para que no burle el chequeo de colisiones.

Complementos: `TestRetiredSDDJourneysAreAbsent` fija 18 IDs retirados que no pueden reaparecer; `TestCoreJourneysAvoidRetiredWorkflowCommands` recorre también los `Requires.Verb` de los composites.

*Verificado ejecutando:* `cd bench && go test -run TestRegisteredJourneysMatchTheManifest -count=1 .` → `ok ... 0.013s`; `go test -count=1 .` → `ok ... 4.786s`; `go vet ./...` → exit 0.

*Transferibilidad:* **alta**. Ver §3, idea N1.

#### D5. El CI conduce el corpus entero y luego **afirma por nombre** 13 journeys — **verificado leyendo**

`ci.yml:99-150` construye el binario y corre `gentle-ai-bench run --binary ... --out ...` **sin `--only`**: ejecuta los 48 journeys core. Después, un `jq -e` con una función `completed_once($id)` exige que 13 IDs concretos (`j51`, `j59`, `j60`, `j75`, `j89`, `j104`, `j110`, `j111`, `j113`, `j114`, `j116`, `j123`, `j4435`) aparezcan **exactamente una vez** y con `status == "completed"`. Luego tres runs adicionales con `--axis transition` (afirma `tr09` y que sólo haya una fila `tr*`), `--only j105` con el binario normal (completed) y `--only j97` con y sin `-tags bench_fixture`: **sin** el tag el journey debe reportar `unsupported`, **con** el tag debe `completed`. Es un test que afirma que el binario de producción **no puede** completar un journey que depende de un hook de fixture.

*Transferibilidad:* alta y directa (§3, N2).

#### D6. Los ejes: seam, propiedades impresas y declaración de "no black-box" — **verificado leyendo**

`bench/axis.go:1-80` define un `Axis` con `Name`, `Title`, `BlackBox bool`, `Properties []string`, `Review` y `Journeys`. Reglas del seam: nada corre salvo que usted lo nombre; un nombre desconocido es error duro; el core **no depende de ningún eje** (borrar el fichero de un eje deja el corpus compilando e informando exactamente los mismos números); y las `Properties` del eje se imprimen **en el informe del run**, no sólo en el README: *"A property a reader has to come and find is a property that gets missed"* (`bench/README.md`, entrada 11 del contrato de honestidad).

*Transferibilidad:* alta como patrón de "extensión opcional que declara su propio coste" (§3, N3).

#### D7. Sólo hay 3 ejes registrados; dos de los documentados ya no existen — **verificado ejecutando**

```
$ cd bench && go build -o /tmp/gab .
$ /tmp/gab run --axis damaged-store --binary /bin/true --out /tmp/dsx.json
unknown axis "damaged-store" (registered: compatibility, model-picker, transition, or `all`)
$ /tmp/gab run --axis real-world --binary /bin/true --out /tmp/rwx.json
unknown axis "real-world" (registered: compatibility, model-picker, transition, or `all`)
```

El commit `838977fd` (2026-08-23, *"refactor(review)!: close on the last causal event"*, cierra #3587) **borró 1.203 líneas de `axis_real_world.go`** dejando un stub de una línea (`package main`) y recortó `axis_damaged_store.go`, pero **no actualizó `bench/README.md`**, que sigue titulando las secciones *Opt-in axes → `damaged-store`* y *`real-world`* como vivas (el README no se ha tocado desde `c75a9c14`, el commit que creó los ejes). Consecuencias medibles:

- `axis_real_world.go`: 1 línea.
- `axis_damaged_store.go` (1.614 líneas) + `axis_damaged_store_closure.go` (832 líneas): se compilan dentro del módulo `bench`, pero **nada los referencia** (`grep damagedStore` fuera de esos ficheros no devuelve nada). Un `journeys_atomic_review_test.go:130` los conserva sólo como **fixtures de texto** ("no contengan `review finalize`").
- El comentario de `axis.go:91` sigue diciendo `"45 journeys" and "45 journeys plus a damaged-store axis"`.

*Valor:* hallazgo negativo y **advertencia**: el propio repo que predica "declare sus límites" mantiene 2.446 líneas de eje muerto y un README que describe ejes inexistentes. Debe pesar al copiar la idea: el seam del eje es bueno, su **disciplina de baja** no lo es.

#### D8. El corpus core son 48 journeys, no 57 — **verificado ejecutando**

`bench/testdata/journeys.manifest` tiene 48 líneas no vacías, y `TestRegisteredJourneysMatchTheManifest` pasa, luego `Journeys()` == 48. El README dice `"57 core journeys"` en dos sitios (`bench/README.md:391`, `:629`) y `axis_compatibility.go:24` dice `"~57 journeys and 4 prior axes"`. La causa es la retirada de SDD/OpenSpec (`e219644b`, 2026-09-25, *"retire SDD and OpenSpec in favor of ODD"*). Es una divergencia doc-código del mismo tipo que el propio repo persigue en su premisa de "los documentos reflejan el código".

#### D9. Eje nuevo `compatibility` (mayor de edad, no parche de regresión) — **verificado leyendo**

`bench/axis_compatibility.go:9-49`: el eje nace de un **punto ciego nombrado** (#2447): el corpus core y todos los ejes previos conducían exclusivamente el ciclo **negociado** (`review status --next-transition`), nunca las superficies directas/manuales que el contrato mantiene vivas. *"A direct `review start --base-ref ... --committed-only` could create a lineage no reviewer lens could ever complete, and NOTHING in ~57 journeys and 4 prior axes would have noticed."* El eje incluye un párrafo que **nombra explícitamente lo que excluye y por qué** (`review-resume`, `review-bundle-export`, `review-bundle-import`, `review-validate`, `review-step`), algo que un eje honesto debe hacer.

*Transferibilidad:* alta como disciplina de "auditoría de puntos ciegos con nombre" (§3, N4).

### Familia C — Tests que gobiernan el CI y el release

#### D10. Tests Go que leen `.github/workflows/*.yml` y afirman la estructura del CI — **verificado leyendo**

`internal/assets/formatter_ordering_test.go` y `internal/update/release_security_test.go` contienen el patrón:

- `TestRequiredChecksFailClosedWhenFormatFails` (líneas 34-105): corta `ci.yml` en secciones por nombre de job y exige, para cada job requerido, `needs: go-format`, `if: always()`, el step literal `Require successful Go format` con `run: exit 1`, y que **ningún step caro posterior tenga `if:` ni el job `continue-on-error:`**. El comentario explica que la lista de jobs debe estar completa porque *"a job this list does not know about gets swallowed into its predecessor's section, and its own guard step then reads as the predecessor bypassing the format gate"*.
- `TestWindowsFullSuiteShardsCoverEveryTestName` (líneas ~250-340): lee **los selectores de shard directamente de la matriz del YAML**, compila cada uno como regex `-run`, ejecuta `go test <pkg> -list '^Test'` **contra el inventario real** y exige que cada test de nivel superior esté reclamado por **exactamente un** shard; además que cada shard reclame ≥1 test y que el inventario no esté vacío. El comentario documenta la evolución: los shards eran rangos de letras A-Z verificados por álgebra, *"cheap to verify but impossible to balance"* (`TestReview*` = 423 de 649 `TestR*` en `internal/cli`); ahora son regex arbitrarios y la cobertura se prueba contra el inventario real, *"strictly stronger than the range check"*.
- `TestOrganicRuntimeE2EUsesInstalledOpenCodePin`: el pin `opencode-ai@<versions.OpenCode>` debe aparecer **exactamente una vez** en `ci.yml`.
- `TestWindowsReleaseBlockerCannotSkipOwnerRebinding`: el workflow debe contener el env var de guardia y **no** debe contener un paquete retirado (`internal/deliveryadmission`), y el test nativo debe leer ese env var.
- `TestArchOpenCodeProvisioningRunsPublishedRepairBeforeVersionCheck`: asserta el texto exacto del `Dockerfile.arch`.

*Transferibilidad:* **máxima** (§3, N5).

#### D11. Tests que ejecutan los scripts de release con `gh` y `minisign` falsos — **verificado leyendo**

`internal/update/release_security_test.go` es el patrón más rentable del repo:

- **`gh` falso y `minisign` falso** escritos a un directorio temporal, antepuestos al `PATH`, y `scripts/verify-release-assets.sh` ejecutado de verdad. El doble de `gh` **registra cada llamada** y el test afirma que sólo hubo **dos**, ambas dentro de la superficie read-only aprobada (`TestReleaseAssetVerifierPreservesReadOnlyRotationVerification`). Tres casos: tag de promoción explícito gana sobre el ref `main`; ref de tag nativo sigue funcionando; tag explícito vacío **falla cerrado** con `RELEASE_VERIFICATION_TAG is empty`.
- **`TestRequireCISuccessSelectsNewestExactCommitRun`**: seis escenarios sobre `scripts/require-ci-success.sh` con `gh` falso, incluyendo "el run más nuevo está `in_progress`" y "el run más nuevo falló aunque haya uno antiguo con éxito". La regla de selección es **por `created_at` con el ID de run como desempate determinista**, porque *"API order is not a contract"* (`scripts/require-ci-success.sh:44-47`).
- **`TestCanonicalReleasePublicKeysControlRealLinkerBuild`**: construye el binario de verdad y prueba que `MINISIGN_PUBLIC_KEYS` con `\n-X <target>=<override>` (inyección de linker), con ` -X ...` en la misma línea, con coma final o con espacio inicial **no produce binario**; y que la clave canónica sí queda embebida y el override rechazado no.
- **`TestReleaseSecurityScriptsAreSyntacticallyValidAndFailClosed`**: para cada script, exige substrings concretos **y** `bash -n`.
- **`TestReleaseWorkflowUsesFailClosedLeastPrivilegeGates`**: `permissions: contents: read` por defecto; `MINISIGN_SECRET_KEY_BASE64` aparece **exactamente una vez**; `persist-credentials: false` aparece **exactamente 3 veces**; cada `uses:` casa con el regex `[0-9a-f]{40}`; sin versión flotante de GoReleaser; el ancla canónica no se persiste por `GITHUB_ENV`.
- `TestStablePromotionWorkflowUsesBoundSourceAndProtectedPublication` prohíbe `git push` desde un shell step y prohíbe tocar `GITHUB_REF_NAME`, y exige `recovery_state`, `verify-existing`, el `--method DELETE` del restaurador de policies, etc.

*Transferibilidad:* **máxima** (§3, N6).

#### D12. El guard de drift de Darwin tenía un bug de `pipefail` documentado — **verificado leyendo**

El commit `99bfa8a3` (2026-07-29) documenta: `printf '%s\n' "$listed" | grep -qx "$name"` bajo `set -o pipefail`. Cuando `grep -q` encuentra pronto, sale, `printf` recibe SIGPIPE y sale 141, y `pipefail` propaga eso en lugar del éxito de `grep`, reportando **MANIFEST DRIFT** de un test presente. Sólo dispara cuando el listado supera el buffer del pipe (creció con la suite) y cae sobre las entradas que van primero en el listado, por eso afectaba a dos de veintinueve y parecía arbitrario. Reproducido fuera del repo con un listado de 20k líneas; la solución es un here-string.

*Transferibilidad:* alta y de coste casi nulo: es una clase de bug que **cualquier** script nuestro con `set -euo pipefail` y `| grep -q` puede tener (§3, N7).

### Familia D — Guardas, ratchets y contratos de prosa

#### D13. Declaraciones de población de guardas + baseline con huella AST — **verificado leyendo**

`docs/architecture/guard-population.md` + `.guard-population-baseline.txt` definen un segundo ratchet, independiente del de deadcode:

- Se anota la guarda con `// guard:population <family> <too-tight|too-loose|fail-closed>: <población legítima y frontera de exclusión>` justo **encima** del nodo `if`/`switch`/`return` que la aplica.
- `TestEveryRegisteredGuardPopulationDeclarationMatchesProduction` ata la declaración al nodo adyacente por AST y `.guard-population-baseline.txt` congela `ruta \t familia \t dirección \t claim \t tipo-de-nodo \t sha256(nodo)`.
- El test falla en **ambas direcciones**: declaración ausente del registro y entrada del registro ausente de producción.
- **Declara su frontera:** *"The contract proves declaration presence, AST adjacency, and exact registry agreement. It does not prove that the population claim is true, that every qualifying guard was identified, or that tests sample the outside world."*
- Regeneración deliberada con `GENTLE_AI_GUARD_POPULATION_UPDATE=1 go test ./internal/cli -run TestEvery... -count=1`.

Cinco entradas congeladas hoy, en 10 familias registradas.

*Transferibilidad:* alta para nuestros `CRITICAL_HELPERS` y para cualquier guarda de seguridad/validación (§3, N8).

#### D14. Ratchet de deriva de secciones de orquestador entre 12 runtimes — **verificado leyendo**

`internal/assets/orchestrator_drift_ratchet_test.go`: recorre los 12 `orchestrator.md` embebidos, parte el contenido por headings `##`/`###`, hashea cada cuerpo y cuenta **cuántos cuerpos distintos** recibe cada sección entre runtimes. Un techo histórico por sección (`Delegation Rules` ≤ 11 variantes, `State and Conventions` ≤ 10, ...); superarlo falla; quedar por debajo **sólo registra** "considere bajar el ratchet"; una sección que desaparece de todos los runtimes falla; y 3 anclas de seguridad deben estar presentes en **todos**. El comentario: *"Keep historical ceilings for retained shared sections... Removing a section is an inventory change; new uncoordinated drift must fail."*

*Transferibilidad:* alta si alguna vez tenemos prosa replicada por destino (§3, N9).

#### D15. Contratos de idioma/slop con lista de tokens prohibidos — **verificado leyendo**

`internal/assets/language_contract_test.go` define `oddKnownLanguageLeaks = ["elegí", "Respondé", "¿Querés ajustar algo o continuamos?"]` y exige que **no** aparezcan en los assets gestionados; además fija frases obligatorias ("Generated technical artifacts default to English", "If the selected reply language is English, every part of the direct reply must be English: greetings, interjections... Do not use Hola, dale, listo...") y distingue canal persona vs output-style. `internal/assets/skill_friction_contract_test.go` hace una comprobación **a tres bandas** (skill público, skill embebido y skill de colaboración) con marcadores obligatorios (`"remote destination"`, `"credential/session"`, `"Before any target-host read"`, `"current direct human instruction"`, `"size:exception"`, `"native RDD consent"`) y una lista de **contradicciones prohibidas** (`"git stash"`, `"git pull"`, `"gh pr create --title"`, `"All automated checks must pass"`).

*Transferibilidad:* alta. Es slop-drift hecho mecánico, y a nosotros nos toca de cerca el bilingüismo castellano/inglés (§3, N10).

#### D16. Lint de frontmatter de skills como test + dualidad público/embebido — **verificado leyendo**

`internal/assets/skills_frontmatter_test.go` recorre cada `SKILL.md` embebido y exige: delimitadores `---`; `name` == basename del directorio; `description` como escalar **entrecomillado en una línea** (bloque `>`/`|` prohibido); longitud ≤160 caracteres (con **excepciones por fichero declaradas**: `systemic-issue-triage` 205, `gentle-ai-bench` 194, por ser copias byte a byte de fuentes públicas); presencia de la subcadena `Trigger:`; y una whitelist de claves top-level (`name, description, license, metadata, version, user-invocable, disable-model-invocation`). El parser es manual a propósito para no arrastrar dependencia YAML.

`internal/assets/bundled_skills_test.go` compara por bytes el skill público y el embebido... **sólo para 2 de los 11 skills públicos** (`systemic-issue-triage`, `gentle-ai-bench`). El repo raíz `skills/` (11, contribuidor) y `internal/assets/skills/` (15, embebidos) divergen con libertad; p. ej. `branch-pr` y `work-unit-commits` difieren entre ambas copias. `SharedSkillFileNames()` recorre el `embed.FS` para que ninguna lista literal de ficheros compartidos pueda quedarse obsoleta (`internal/assets/shared_skill_files.go:12-40`).

*Transferibilidad:* alta en forma (lint + whitelist + excepción declarada); el **hueco** de la dualidad es una advertencia (§3, N11).

#### D17. El `odd/tasks/<n>-<slug>.md` con marcadores `[done]` en prosa — **refinamiento del Informe 1 (IDEA T9 / COL2)**

`odd/tasks/ga-4882-telemetry-lock.md` (50 líneas) tiene las secciones ya conocidas, pero tres detalles que el Informe 1 no registró:

1. La línea `Claimed` incluye **fecha + id de comentario de issue + rama + ruta de worktree + SHA base**: `Claimed 2026-09-23 (issuecomment-5796980665). Branch fix/4882-telemetry-increment-syncs (worktree ~/gentleman/gentle-ai-4882) from origin/main a773ccfb.`
2. Las `Tasks` son prosa numerada con marcador `[done]` y, en la misma línea, el **número de PR** y el **id de linaje de review nativo** con su severidad y disposición de advisories.
3. `Evidence` es cronología append-only con el resultado observable por comando.

Hay 29 ficheros en `odd/tasks/`. No hay validador automático del formato (el único consumidor de `odd/tasks` en código es la guía de orquestación, `internal/components/agentguidance/routing.go`).

*Transferibilidad:* ya la tenemos (§3, N12 lo acota).

### Familia E — Instalador, release y empaquetado

#### D18. Contrato del instalador: derivar el path del módulo de `go.mod`, fail-closed — **verificado leyendo**

`scripts/test-install-module-path.sh` (unos 190 LOC) prueba, sin tocar red, con **funciones shell que ensombrecen** `curl` y `go` dentro de una subshell (`run_test` ejecuta `. install.sh` en un subshell nuevo para que `fatal()` no mate al runner):

1. `stable` con tag `v3.7.0` resuelve el módulo `/v3` **leyendo el `go.mod` del tag**.
2. `stable` con tag `v4.0.0` resuelve `/v4` — la regresión que motivó el test (#4689): *"A future /vN bump must need no installer change."*
3. `beta` resuelve el SHA de `main`, deriva `/v5` del `go.mod` en ese SHA, instala `@<sha>` y exporta `GONOSUMDB/GOPRIVATE/GONOPROXY` derivados (con assert de que **no** contienen `/v3`).
4. **Fail-closed:** con `go.mod` 404 o 200 sin línea `module`, `install_go` aborta y **`go install` no se ejecuta nunca** (lo assertan con una variable `GO_WAS_CALLED`).
5. **`curl | bash` sigue ejecutando `main`:** `cat install.sh | bash -s -- --help` debe imprimir `Usage: install.sh` — porque en ese modo `BASH_SOURCE[0]` está vacío.
6. **Windows:** `Install-ViaGo` debe resolver el tag de release y **no** contener `@latest` (que resolvería `/v4` a una pseudo-versión no publicada).

*Transferibilidad:* alta; es el modelo de "test del instalador sin red, con dobles por ensombrecimiento de funciones" (§3, N13).

#### D19. Convención de changelog y reproducibilidad de artefactos — **verificado leyendo**

`.goreleaser.yaml`: el changelog **excluye** `^docs:`, `^test:`, `^ci:` (líneas 116-124). No existe `CHANGELOG.md`. Los ficheros de los meta-archivos se empaquetan con `mode: 0644` y `mtime: "1970-01-01T00:00:00Z"` para que el archivo sea reproducible. Hay **tres** archivos: el del binario, el bundle de contrato y `gentle-ai-release-provenance-v1.tar.gz` (provenance separada y firmada con el mismo `checksums.txt`). La documentación de release incluye un gate de restauración de Windows con 4 condiciones y la razón de ausencia (`docs/release-signing.md`, sección *Windows distribution restoration gate*): sin firma Authenticode pública no se publica exe; el camino `go install` se verifica contra `sum.golang.org` y **no** desactiva el checksum DB.

*Transferibilidad:* media (la reproducibilidad de artefactos y el "gate de restauración con condiciones explícitas" sí; el changelog filtrado es una decisión).

### Familia F — Runtime y estado

#### D20. Dónde escribe el binario (runtime data) — **verificado leyendo**

- Config/estado de usuario en `~/.gentle-ai/`: `state.json`, `persisted-state.json`, `managed-assets.manifest.json`, `managed-assets.journal` (cap 1 MiB), `backups/`, `bin/` (OpenCode background) y `pi-codegraph*.json` (`internal/state/manifest.go:19-27`, `internal/app/app.go:1168`, `internal/opencode/background.go:333`, `internal/agents/pi/adapter.go:112`).
- El modelo de **propiedad de assets gestionados** es lo más valioso: `Manifest` lleva `schema: gentle-ai.managed-assets/v1`, `Producer{BinaryVersion, Commit}`, `BundleDigest` calculado sobre un subconjunto canónico (todo menos `observed`), y por recurso un `OwnedExtent` con `Kind ∈ {full, marker-block}` + `MarkerID`, `Ownership ∈ {managed, user}`, `Desired`/`Observed` (`internal/state/manifest.go:44-100`). Es decir: el binario sabe **exactamente qué bytes posee** dentro de un fichero ajeno (una región entre dos marcadores) y qué parte es del usuario.
- El store de review **no** vive en `~/.gentle-ai`: vive en `<git-common-dir>/gentle-ai/review-transactions/<version>/<linaje>/` con `review-state.json`, `review-receipt.json` y journals (`store_test.go:1277`, `compact_store.go:32-34`). Un worktree enlazado y su repo principal comparten `commonDir`, por eso un mismo store ve varias ramas (lo explota `j15-linked-worktree` del bench).
- No existe `internal/golib`; la separación runtime-vs-test se hace por **build tags** (`windows`, `unix`, `darwin`, `aix`, y los dos propios: `bench_fixture` en `internal/app/bench_model_picker_fixture.go` y `internal/reviewtransaction/bench_fixture.go`, que exponen sólo hooks deterministas de fallo). El tag `organic` que mencionaba el encargo **no existe**; el E2E "organic" es un directorio (`e2e/organicruntime/`) gateado por la env var `GENTLE_AI_REAL_AGENT_E2E=1`.

*Transferibilidad:* el modelo `OwnedExtent` + `Ownership` es directamente copiable a cualquier cosa que inyectemos en ficheros del usuario (§3, N14).

#### D21. `bench/` es un módulo Go propio a propósito — **verificado leyendo**

`bench/go.mod` propio hace que `go build ./...`, `go vet ./...` y `go test ./...` del módulo raíz **no lo vean**: *"the tool must never be able to break, slow, or enter a release build of the product it measures"*. El precio está declarado: *"nothing verifies it automatically — build it from inside this directory"*. Por eso el CI tiene un step explícito (`ci.yml:88-91`) y por eso el ratchet de deadcode (que corre sobre el módulo raíz) **no alcanza** las 2.446 líneas muertas del eje `damaged-store`.

*Transferibilidad:* el patrón "herramienta de medición en módulo aparte que jamás entra al build de producto" es bueno; su coste (fuera del radar de los gates) es exactamente el que se materializó en D7.

### Familia G — Gobernanza, etiquetas, reglas e historial

#### D22. El ruleset nació con el flujo issue-first y contiene `copilot_code_review` — **verificado leyendo (gh api)**

`gh api repos/Gentleman-Programming/gentle-ai/rulesets/13932547` (creado `2026-03-15T21:10:39Z`, actualizado `2026-05-05`): `enforcement: active`, `conditions.ref_name.include: ["~ALL"]`, y reglas `deletion`, `non_fast_forward`, `copilot_code_review` (`review_on_push: true`, `review_draft_pull_requests: false`), `required_status_checks` (7 checks, `strict_required_status_checks_policy: false`), `commit_message_pattern` y `branch_name_pattern` con sus regex exactos y su texto de ayuda. La fecha del ruleset coincide al minuto con `c73f2bcd` (*"feat(github): enforce issue-first PR workflow with templates, CI checks, skills, and CONTRIBUTING.md"*): el flujo issue-first y la protección de rama nacieron juntos.

*Transferibilidad:* media; el detalle nuevo es que la revisión de Copilot es una **regla del ruleset**, no un bot suelto.

#### D23. La tasa real de fallo de `ci.yml` — **verificado leyendo (gh api)**

`gh api .../actions/workflows/ci.yml/runs?per_page=100`:

| Ámbito | success | failure | action_required |
|---|---|---|---|
| Últimos 100 runs (todos los eventos) | 65 | 21 | 14 |
| Últimos 100 runs de `branch=main` | **92** | **8** | 0 |
| Desglose por evento (últimos 100) | — | — | — |

Por evento: `pull_request` 80 runs → 47 success / 19 failure (24 % rojo); `push` 18 runs → 17 success / 1 failure; `schedule` 2 runs → 1 success / 1 failure. Total histórico de runs de `ci.yml`: **5.750**. Y `Windows Full Suite` (últimos 100): **24 success / 75 failure / 1 null** — la suite Windows sigue mayoritariamente roja, como anticipaba el Informe 1, pero con un 24 % verde, no cero.

*Transferibilidad:* es un dato, no una idea: **corrige** la afirmación del Informe 1 de que "las ejecuciones son todas `success`".

#### D24. Nada aplica `type:*` ni `status:approved`: son humanas — **verificado leyendo**

`grep -rn "addLabels\|add-labels" .github/workflows/*.yml` no devuelve ninguna aplicación de etiquetas. Lo que hay:

- `.github/ISSUE_TEMPLATE/bug_report.yml:3` aplica automáticamente `["bug", "status:needs-review"]` al crear el issue, y su texto guía dice literalmente: *"A maintainer reviews it and adds `status:approved` (or closes it as invalid/duplicate). Only then should you (or anyone) open a PR."*
- El job `check-type-label` (`pr-check.yml:165-201`) **sólo lee** y, si no hay etiqueta `type:*`, falla con *"Ask a maintainer to add the appropriate label."*
- El catálogo de etiquetas incluye `status:approved`, `type:*`, `size:exception`, y además `slop`, `no-merge`, `rc-feedback`, `source:guided-report`, `gentle-report`, `up-for-grabs`.

**Conclusión:** la transición `status:needs-review → status:approved` y el etiquetado `type:*` son **actos humanos del maintainer en la UI**, no hay bot ni script. Es exactamente lo que el Informe 1 sospechaba y no pudo verificar.

#### D25. `promote-stable-rc.yml` se ha ejecutado 4 veces en total — **verificado leyendo (gh api)**

`gh api .../actions/workflows/promote-stable-rc.yml/runs`: `total_count: 4`. Run #1 `failure` (2026-08-08), #2 `success` (2026-08-08), #3 `cancelled` (2026-09-08), #4 `failure` (2026-09-08). `promote-stable-preflight.sh` contiene `recovery_state=verify-existing` y hay dos tests que lo fijan (`TestStablePromotionVerifyExistingRecoveryIsVerificationOnly`, `TestStablePromotionPreflightUsesRESTCompatibleReleaseID`), con prohibición explícita de `github.rest.repos.updateRelease` y `uploadReleaseAsset` en ese estado. Ningún run registrado demuestra que `verify-existing` se haya ejercitado en producción: el camino está **fijado por test, no probado en vivo**.

#### D26. `results.json` comiteado en la raíz con un journey **fallido** — **verificado leyendo**

El repo raíz contiene `results.json` (schema `gentle-ai-bench.results/v1`, `mode: driven`) con `binary: /tmp/claude-1000/.../ga`, `binary_version: "gentle-ai dev"` y un `j60` en `status: "failed"` con `failure_reason` completo (`repository_context_unavailable ... fatal: not a git repository`). Es un artefacto de una ejecución manual que quedó comiteado; convive con `bench/results-after.json`, que sí es el ejemplo curado del README. Hallazgo menor, pero ilustra que "el run falla cerrado" y "el artefacto se comitea igual" pueden dejarse juntos.

---

## 2. Cierre de la lista "Sin verificar" del Informe 1

Los siete puntos (§7 del Informe 1) y los cinco que el encargo añadía.

**1. Frecuencia exacta de fallo del CI principal — CERRADO.**
`ci.yml` en `main`, últimos 100 runs: **92 success / 8 failure**. Todos los eventos, últimos 100: 65/21/14 (`action_required`). Por evento: PR 24 % rojo, push 1/18, schedule 1/2. Total histórico: 5.750 runs. La muestra del Informe 1 ("todas success") estaba sesgada, como sospechaba. `Windows Full Suite`: 24/75/1. Evidencia: `gh api .../actions/workflows/ci.yml/runs` (verificado leyendo metadatos).

**2. Si `darwin-runtime` está en los required status checks — CERRADO Y CONFIRMADO.**
El ruleset lista exactamente 7 checks: `Check Issue Has status:approved`, `Check Issue Reference`, `Check PR Has type:* Label`, `Unit Tests`, `E2E Tests (ubuntu|arch|fedora)`. `darwin-runtime` **no** está. Pero `formatter_ordering_test.go:60-70` incluye `darwin-runtime` en la lista de jobs que *deben* cumplir el contrato fail-closed frente a `go-format`, con el comentario *"darwin-runtime is a required check like its siblings"*. Es decir: el código **ya lo trata como requerido** y el ruleset todavía no; la intención de activarlo es más fuerte de lo que el Informe 1 estimó.

**3. Por qué `windows-runtime` sigue en `ci.yml` y `windows-full-suite` se separa — CERRADO, con el motivo real.**
No es sólo "deuda visible". Los cuerpos de commit lo dicen:
- `de32556c` (*"unblock and shard the Windows lane"*): `windows-runtime` declaraba `timeout-minutes: 30` mientras su step declaraba `35`, así que el **job mataba al step antes de que el step alcanzara su propio límite**. Ocho pushes consecutivos a `main` cancelados exactamente a los 30 min, y **un job cancelado reporta el run entero como cancelled, que el gate de release lee como "no success"**. `main` sin CI verde desde 2026-07-21. Medición del mismo run: `go test ./...` = 4m58s en ubuntu-latest y **más de 30m** en windows-latest; Organic Runtime E2E = 2m07 vs 6m09, luego ~3× es el coste estructural de Windows en este repo. Arreglo: exclusiones de Defender (best-effort con `-ErrorAction SilentlyContinue`) + sharding.
- `99bfa8a3` (*"repair the Darwin drift guard and unblock releases"*): la suite completa **nunca una vez** había terminado; *"v2.2.0 shipped without these tests ever running, and unblocking them surfaced eighteen genuine Windows failures"*. Y el motivo de sacarla de `ci.yml`: *"Inside ci.yml that pre-existing debt blocks publication, because the release gate requires a green ci.yml run on the exact tagged commit. Outside it, the signal stays visible on every push and schedule while the debt is paid down."* Cierra con *"This lowers what gates a release to exactly what gated v2.2.0 — no less."*
- `36e820fa` (*"shard the Windows lane finely enough to finish"*): el primer sharding dejó dos shards que seguían chocando con `-timeout=30m` (`internal/cli` reportó FAIL a los 1800,041 s). `internal/cli` son 960 tests de los que 453 empiezan por `TestR`.
- El comentario vigente de `windows-full-suite.yml:1-18` recoge los tres hechos y la condición de retorno ("once the eighteen are fixed, fold this back into ci.yml").

La respuesta a "por qué `windows-runtime` sigue": es el **subset curado de release-blockers** (con drift guard `go test -list`) cuyo contrato fail-closed frente a `go-format` está testado, y **no** es required status check por el motivo de Defender (`ci.yml:209-211`); la suite completa se separó porque su rojo preexistente bloqueaba la publicación.

**4. `recovery_state=verify-existing` en promociones reales — PARCIALMENTE CERRADO.**
Código y tests: existe, está fijado como verificación pura y tiene prohibido mutar la release publicada (`release_security_test.go`, `TestStablePromotionVerifyExistingRecoveryIsVerificationOnly`; `scripts/promote-stable-preflight.sh` con `recovery_state=verify-existing`). Uso real: el workflow acumula **4 ejecuciones en toda su historia** (#1 failure, #2 success, #3 cancelled, #4 failure). No hay evidencia pública de que un run haya entrado por `verify-existing` concretamente: para saberlo habría que descargar los logs de los runs, y el encargo acotó la investigación a metadatos públicos. Se declara **no verificado en vivo**, con la salvedad de que el camino está cubierto por test estático en ambas direcciones.

**5. Quién aplica `type:*` y `status:approved` — CERRADO.**
Nadie automáticamente. Las plantillas de issue aplican `bug` + `status:needs-review` al crear; el paso a `status:approved` lo hace el maintainer en la UI (el propio texto de la plantilla lo dice, `bug_report.yml:12-14`); el check de `type:*` sólo lee y remite al maintainer. No hay `addLabels` en ningún workflow ni script. Etiquetas usadas además: `size:exception`, `slop`, `no-merge`, `rc-feedback`.

**6. Cobertura del bench journey por journey — CERRADO.**
Tres capas: `validateCorpus` (precondición obligatoria), manifiesto ordenado de 48 IDs + test de correspondencia exacta, y test de colisiones de ID (full ID y prefijo numérico) con ambos ficheros ofensores nombrados, más `TestJourneySourcesCoverTheWholeCorpus`. Añadido: cada fixture del corpus **prueba su propio edge case** (git readback) antes de que el journey confíe en el resultado; el eje `damaged-store` iba más lejos (re-derivar la revisión del registro desde los bytes leídos, para que el fixture falle *primero* cuando el marshalling se mueva). Verificado ejecutando: `go test -count=1 .` en `bench` → ok 4.786 s. Lo que **no** hay: un gate que exija que el subconjunto que el CI afirma por nombre cubra una fracción mínima del corpus; el CI conduce los 48 y afirma 13.

**7. (Encargo) El contenido del contrato de provider — CERRADO.** Ver D1, D2, D3. El contrato especifica 3 roles con esquema/prompt/límite de tamaño, inventario cerrado de ficheros hasheados, reglas de compatibilidad por SEMVER, y verificación estructural antes de extraer.

**8. (Encargo) Bench journeys: qué son y cuál es el mecanismo de cobertura — CERRADO.** Ver D4-D9 y §3 N1-N4.

**9. (Encargo) `.gentle-ai/` + `internal/` + build tags — CERRADO.** Ver D20 y D21. Corrección: no existe `internal/golib` y no existe tag `organic`.

**10. (Encargo) El catálogo de skills y cómo se versiona/testea/libera — CERRADO.** Ver D16. Los skills embebidos viajan **dentro del binario** (`//go:embed all:skills`, `internal/assets/assets.go:4-6`) y no en los archivos de release (`.goreleaser.yaml:31-42` sólo incluye LICENSE, README, un doc y los contratos). El "catálogo de 26 skills" del encargo no existe como tal: hay 11 skills públicos en `skills/` y 15 embebidos en `internal/assets/skills/`. El paquete npm **`gentle-pi` (v3.7.0) no es de este repo**: sale de `Gentleman-Programming/gentle-shell` (`npm view gentle-pi` → `gentle-pi@3.7.0 | MIT | ... https://github.com/Gentleman-Programming/gentle-shell`), y `gentle-ai` no existe en npm; el `package.json` de este repo se llama `gentleman-ai-installer` y está marcado `private: true`.

**11. (Encargo) `AI_POLICY.md` + ecosistema `AGENTS.md` — CERRADO.** `AI_POLICY.md` (62 líneas) se leyó completo: permiso explícito de contribución asistida, responsabilidad humana, **divulgación obligatoria** de asistencia material (herramienta/modelo, alcance, verificación realizada), prohibición de atribución humana a la IA (`Co-Authored-By`, `Reviewed-by`, `Tested-by`, `Signed-off-by`, aprobación), trailer opcional `Assisted-by`, distinción entre autoría y review/RDD advisory, y una lista de comportamientos inaceptables que es, en la práctica, nuestro catálogo de AI-slop (afirmar sin verificar, inventar APIs/rutas/evidencia, enmascarar síntomas, delegar el entendimiento al maintainer). El apartado *Enforcement* declara que **no** hay detección automática ni gate de divulgación: se aplica por juicio del revisor. `AGENTS.md` es un índice de 11 skills con columna de trigger y ruta, sin reglas operacionales propias. `.claude/` sólo contiene un `scheduled_tasks.lock` de 91 bytes: no hay configuración de agente comiteada. **Corrección de la premisa del encargo:** `AI_POLICY.md` sí se cubrió en el Informe 1 (COL3), pero el contenido de divulgación obligatoria en tres puntos y la lista de comportamientos inaceptables no.

**12. (Encargo) `docs/` más allá de `release-signing.md` — CERRADO.** 58 ficheros `.md` en `docs/`. Los de más valor encontrados: `docs/testing-agents-deterministically.md` (D10 del informe; el más transferible), `docs/architecture/guard-population.md` (D13), `docs/architecture/rdd-freeze-expansion-policy.md` (N15), `docs/codebase/maintainer-playbook.md` (checklists por tipo de cambio + tabla de preguntas de review), `docs/CODEBASE-GUIDE.md` (77 líneas, índice radial). **No hay `CHANGELOG.md`**; las notas se generan con GoReleaser excluyendo `docs:`/`test:`/`ci:`.

**13. (Encargo) El flujo del instalador — CERRADO.** Ver D18.

**14. (Encargo) Historia profunda con depth-100 — CERRADO.** El clon llegó a 3910 commits. Primer commit: `4c9176e0` (2026-02-28, *"feat: initial implementation of AI Gentle Stack"*). El ruleset nace 2026-03-15 con el commit issue-first. El ratchet de deadcode nace en `c75a9c14` (2026-07-27). La política de tamaño nace en `2242aa42` (2026-08-22, "install dormant base-controlled 400-line gate"). Los shards de Windows, en `de32556c`/`36e820fa` (2026-07-29). El desdoblamiento de la suite, `99bfa8a3` (2026-07-29). El bundle de contrato, `0ed5a45f` (2026-08-14). Estilo de commit: ~56-64 % de los commits llevan cuerpo; la longitud media del cuerpo sube de ~52 palabras (marzo) a **~153 (julio, la crisis de CI/Windows)** y baja a ~62 (septiembre); agosto concentra 1.651 commits.

---

## 3. Ideas transferibles nuevas (con coste)

Coste S = un fichero y un job; M = una pieza de infraestructura nueva; L = rediseño de un flujo.

### N1. Manifiesto ordenado de IDs en lugar de un contador entero — *la mejor relación genio/línea del repo* · Coste **S**

Qué hace: un fichero `testdata/<catalogo>.manifest` con una línea por elemento, ordenado, y un test que compara la unión de las fuentes contra el manifiesto y falla nombrando **qué** apareció y **qué** desapareció. Se regenera con un flag (`-update-journey-manifest`).
Por qué es brillante: sustituye un invariante que un merge resuelve **en silencio** (dos ramas que escriben el mismo entero) por uno que **conflictúa** cuando deben preguntar, y se documenta con un experimento de merge a tres bandas medido, incluyendo el caso en que el manifiesto *sí* conflictúa. Además enseña por qué un contador es peor: *"both branches write the same bytes and git has nothing to disagree about"*. Y el histórico está fechado: #3037/#3038 rompieron `main` el 2026-08-11.
Transferencia a un repo FastAPI: cualquier catálogo que hoy fijemos con un número — el inventario de `CRITICAL_HELPERS`, la lista de chequeos del linter APAP, el conteo de tablas del esquema, la lista de tests marcados `critical`. Coste S: ~40 LOC de test y un fichero de texto.

### N2. Afirmar el CI **por nombre de caso**, no por verde global · Coste **S**

Qué hace: el CI corre el corpus completo y luego `jq -e` con `completed_once(id)` sobre 13 IDs. Un journey que se renombre o desaparezca hace fallar el job aunque el run global siga verde.
Por qué es brillante: un "todo verde" no distingue "pasó lo que quería" de "no corrió nada". El complemento es el `unsupported` explícito: en vez de cero, la fila dice que esa superficie no existe en el binario medido.
Transferencia: los `jq`/`python -c` de nuestros workflows pueden afirmar por nombre los casos e2e/lint/contract que consideramos umbral. Coste S.

### N3. Eje opcional que declara su propio coste y sale en el informe · Coste **M**

Qué hace: un seam pequeño (registro, flag, sección de informe) para extensiones que **no** son black-box, cada una con `Properties` que se imprimen en el resultado del run y no sólo en la documentación. Borrar el fichero del eje deja el core idéntico.
Por qué es brillante: confina la excepción en lugar de explicarla en una nota al pie, y hace que quien lee un run sepa qué se midió sin abrir el README.
Advertencia (D7): la disciplina de baja es la mitad del patrón y este repo la incumplió (dos ejes fantasma + 2.446 líneas muertas + README sin actualizar) — precisamente porque el módulo `bench` está fuera del alcance del ratchet de deadcode. Si copiamos N3, copiemos también el gate que detecta el eje no registrado.
Transferencia: nuestras familias de checks (unit/integration/e2e/production-smoke) podrían seleccionarse por "eje" declarado. Coste M.

### N4. Punto ciego con nombre → eje permanente, no parche de regresión · Coste **S**

Qué hace: cuando aparece una clase de cobertura ausente, se crea un eje con un párrafo que **nombra lo que excluye y por qué**, y ese eje queda como el lugar donde irá la siguiente brecha de la misma clase.
Por qué es brillante: convierte "arreglamos el caso reportado" en "cerramos la clase", y deja por escrito el mapa de lo que aún no se cubre. El párrafo de exclusiones de `axis_compatibility.go:44` es un ejemplo pequeño y perfecto.
Transferencia: aplicable a nuestra auditoría de cobertura real vs mock (`docs/quality/test-audit.md`). Coste S.

### N5. Tests que leen el YAML del CI y afirman su estructura · Coste **M**

Qué hace: un test del propio proyecto parsea `.github/workflows/*.yml` y sostiene invariantes que GitHub no valida: todo job requerido cumple el contrato fail-closed frente a un guard (y la lista de jobs está completa, porque un job no listado se traga en la sección del anterior); cada selector de shard cubre tests reales del inventario `go test -list` y ninguno cubre dos veces; un pin de versión aparece exactamente una vez; un paquete retirado no reaparece; un Dockerfile conserva su orden.
Por qué es brillante: los workflows son código sin tests. El test usa la propia fuente de verdad del inventario en lugar de una lista copiada, y falla cuando el guard pasaría en vacío.
Transferencia: directa a `pytest`; nuestros `scripts/check_*` y `deploy.yml` pueden tener un `tests/test_ci_contract.py`. Coste M (un fichero y disciplina de mantenerlo).

### N6. Dobles de CLI externo + aserción de superficie de llamadas · Coste **M**

Qué hace: se escriben `gh`/`minisign`/`docker` falsos en un directorio temporal, se anteponen al `PATH` y se ejecuta el script real; el doble registra cada invocación y el test afirma que sólo hubo las permitidas, además del fail-closed en los casos inseguros. Complementado por `bash -n` de cada script y por asserts de texto sobre el workflow (recuento exacto de secretos, `persist-credentials: false` × N, SHAs de 40 hex).
Por qué es brillante: prueba el camino de release **sin** publicar ni mockear el script, y la inyección de linker por `MINISIGN_PUBLIC_KEYS` se prueba construyendo el binario de verdad y comprobando que **no existe**.
Transferencia: alta para nuestro `deploy.yml` (Cosign, Coolify, `gh` release/e2e gate) y para los scripts de evidencia de release. Coste M.

### N7. Auditoría de `| grep -q` bajo `set -o pipefail` · Coste **S**

Qué hace: documenta la clase de bug SIGPIPE-141 y su arreglo (here-string), y lo deja escrito en el commit que lo sufre.
Por qué es brillante: es una trampa silenciosa que sólo aparece cuando el flujo supera el buffer del pipe, y entonces se atribuye a "flakiness".
Transferencia: revisar nuestros scripts de CI con `pipefail` por `| grep -q` y por `| head`. Coste S (deuda, no feature).

### N8. Declaración de población de guarda + baseline con huella del nodo · Coste **M**

Qué hace: cada guarda de seguridad/integridad lleva una anotación con la **población legítima y la frontera de exclusión**, atada por AST al nodo adyacente y congelada en un baseline con hash del nodo; el test falla en ambas direcciones y declara que no prueba que la afirmación sea cierta.
Por qué es brillante: convierte "esto valida X" en "esto admite exactamente esta población y excluye esta otra", que es lo que un revisor necesita, y hace barato detectar que la guarda cambió en silencio.
Transferencia: `CRITICAL_HELPERS` y los chequeos de validación de APAP; complementa el ratchet shrink-only del Informe 1 (T2) con una dimensión semántica. Coste M.

### N9. Ratchet de variantes de prosa replicada por destino · Coste **M**

Qué hace: parte cada documento replicado por headings, hashea el cuerpo de cada sección y fija un techo histórico del número de variantes **distintas** por sección entre destinos; superarlo falla, converger sólo se registra, y unas anclas de seguridad deben estar en todos.
Por qué es brillante: es el único ratchet de prosa que he visto que no intenta exigir "texto idéntico" (imposible) ni se rinde a "cada destino improvisa"; cuenta deriva.
Transferencia: si APAP replica guías por destino (opencode/pi/claude, o docs por audiencia). Coste M.

### N10. Contrato de idioma/slop con tokens prohibidos y contradicciones · Coste **S**

Qué hace: listas explícitas de tokens de fuga de idioma (`elegí`, `Respondé`, `¿Querés...?`) prohibidos en los assets gestionados, frases obligatorias, y una lista de instrucciones **contradictorias** prohibidas (`git stash`, `gh pr create --title`, `All automated checks must pass`).
Por qué es brillante: es anti-slop verificable y barato. En un repo con documentación bilingüe como el nuestro, es directamente aplicable.
Transferencia: un test que revise nuestros SKILL.md/AGENTS y docs contra una lista de tokens. Coste S.

### N11. Lint de frontmatter de skills con whitelist y excepción declarada · Coste **S**

Qué hace: `name` == basename del directorio, `description` en una línea entrecomillada ≤160 caracteres con `Trigger:`, whitelist de claves top-level, y **excepciones por fichero** documentadas en el propio test cuando la fuente es una copia byte a byte de fuera.
Por qué es brillante: el `Trigger:` obligatorio en la descripción es lo que hace que el skill sea cargable por el agente de forma fiable; y la whitelist bloquea campos inventados.
Advertencia (D16): la igualdad de bytes público↔embebido se comprueba sólo para 2 de 11 skills en este repo. Si copiamos la dualidad, probémosla entera o no la tengamos.
Transferencia: revisión de los frontmatters de nuestro catálogo de skills en CI. Coste S.

### N12. Refinamiento de la ficha de tarea `odd/tasks` (acota el Informe 1 T9/COL2) · Coste **S**

Qué hace adicionalmente al patrón que ya conocemos: la línea `Claimed` lleva fecha, id de comentario, rama, ruta de worktree y SHA base; cada tarea numerada lleva marcador `[done]` **en la misma línea** que su evidencia (PR, linaje de review, severidad); `Evidence` es cronología append-only.
Por qué es bueno: el worktree y el SHA base convierten la ficha en reproducible; el `[done]` en prosa evita una segunda estructura de checklist que se desincronice.
Transferencia: nuestra ficha de épica puede adoptar la línea de claim. Coste S.

### N13. Test del instalador sin red, con dobles por ensombrecimiento de funciones · Coste **M**

Qué hace: `run_test` ejecuta `. install.sh` en un subshell nuevo, con `curl`/`go` redefinidos como funciones, y afirma: derivación del módulo desde `go.mod`, fail-closed sin ejecutar `go install`, y que `curl | bash` llega a `main`.
Por qué es brillante: prueba un instalador de shell sin red ni contenedor, y el assert de "no se ejecutó `go install`" es el que de verdad protege.
Transferencia: cualquier instalador/bootstrap que tengamos o queramos tener. Coste M si no hay instalador; S si lo hay.

### N14. `OwnedExtent` + `Ownership` para todo lo que inyectamos en ficheros ajenos · Coste **M**

Qué hace: un manifiesto con `schema`, `Producer{binary_version, commit}`, `BundleDigest` sobre un subconjunto canónico y, por recurso, la región poseída (`full` vs `marker-block` + `MarkerID`) y su propiedad (`managed` vs `user`), con `Desired`/`Observed`, más un journal acotado y `backups/`.
Por qué es brillante: es la respuesta explícita a "¿qué bytes de este fichero son míos y cuáles del usuario?", con digest que excluye lo observado para que el manifiesto no cambie sólo porque el usuario editó.
Transferencia: si en el futuro APAP escribe en ficheros de usuario (configs, plantillas), o para nuestro propio estado gestionado. Coste M.

### N15. Política de congelación con presupuesto de bloqueo y prohibición de "fail-mute" · Coste **S**

Qué hace (`docs/architecture/rdd-freeze-expansion-policy.md`): una política escrita que (a) congela trabajo aditivo sobre superficies con disposición `REMOVE/MERGE/DERIVE`, (b) declara un **presupuesto de bloqueo** — sólo se puede bloquear a un humano en el consentimiento previo a congelar y en decisiones terminales; todo lo demás es silencioso o advisory; (c) exige que **toda** guarda bloqueante ofrezca una salida self-service documentada (patrón de referencia: `size:exception`); (d) *"Fail-closed must never be fail-mute"*: todo stop nombra su motivo y su salida; (e) tres invariantes exentos de ablandamiento para siempre; (f) la política **caduça** (Wave 7 o abandono de la rama); (g) una excepción exige cuatro criterios conjuntivos, incluida reproducción en `main` en un SHA concreto y frontera de rollback declarada.
Por qué es brillante: es lo contrario del gate que se multiplica. Pone un techo a la fricción que la propia política puede infligir, y hace de la salida una obligación de diseño, no un favor.
Transferencia: altísima para nuestra épica de calidad/CI. Directamente copiable como documento. Coste S.

### N16. Ratchet de deadcode **no** alcanza los módulos separados: comprobarlo · Coste **S**

Qué hace: hallazgo negativo operacional (D7/D21). El ratchet de deadcode corre sobre el módulo raíz; `bench/` es un módulo aparte; por eso 2.446 líneas de eje muerto pasan desapercibidas.
Transferencia: si algún día separamos un submódulo (scripts, herramientas, migraciones), hay que decidir explícitamente si los ratchets lo cubren o se declara el hueco. Coste S.

---

## 4. Correcciones al Informe 1

Sin contemplaciones, porque de eso se trata.

1. **§7.1 ("las ejecuciones de `ci.yml` en las últimas 30 son todas `success`") es falso como afirmación general.** `main`: 92/100 success, 8 failure. PRs: 24 % rojo. El Informe 1 reconoció el sesgo de la muestra, pero "veredicto provisional: muy fiable" se queda corto: una de cada cuatro PRs de `gentle-ai` termina en rojo, y en julio-agosto de 2026 `main` estuvo **sin CI verde desde el 2026-07-21** (documentado en `de32556c`). El CI de Alan no es "muy fiable"; es un CI en obras que acaba de salir de una crisis.

2. **§1.4 y §6 NC1 atribuyen el desdoblamiento de `windows-full-suite` a "deuda visible" y lo describen como decisión de higiene.** El motivo real está a un commit de distancia y es más duro: `windows-runtime` declaraba `timeout-minutes: 30` con un step de `35`, ocho pushes a `main` murieron a los 30 min, y **un job cancelado reporta el run como `cancelled`, que el gate de release lee como "no success"**. La suite se sacó porque *"the release gate requires a green ci.yml run on the exact tagged commit"*. El Informe 1 además afirmó que el comentario explica "la cronología, pero no por qué `windows-runtime` (subset curado) sigue ahí y la suite completa se va" — la respuesta está en `ci.yml:209-211` (Defender puede romper `Add-MpPreference` y *"a CI lane must not go red because an optimisation was unavailable"*) más el hecho de que la suite completa nunca terminó. No era un misterio sin acceso a Slack; era un `git show` no hecho.

3. **§3.1 y §5 T3 presentan el drift guard de Darwin como ejemplo correcto.** Lo es en diseño, pero su primera versión estaba **rota**: `printf | grep -qx` bajo `pipefail` reportaba MANIFEST DRIFT de tests presentes. Un informe que propone copiar un patrón debería haber leído el commit que lo arregló (`99bfa8a3`), porque ahí está la lección transferible.

4. **§1.5 / IDEA T8 ("Contrato versionado + bundle firmado... **Hoy no es transferible**") queda desmentido.** El Informe 1 redujo el contrato a un número de versión y concluyó que, sin API pública, no aplica. La segunda pasada muestra que el valor no está en firmar un tar, sino en (a) el fichero de versión como fuente única, (b) `Generate` y `Verify` leyendo **los mismos bytes**, (c) la regla de introducción de campos por SEMVER con excusa explícita para contratos anteriores, y (d) inventario cerrado y hasheado con rechazo de claves duplicadas. Eso es transferible hoy a nuestros propios contratos internos (JSON de evidencia, salidas de `check_*`). El Informe 1 subestimó la idea por leer sólo el envoltorio de release.

5. **§7.7 ("la lista de 13 journeys + el model-picker untagged (`j97`) parece exhaustiva") es una lectura incompleta.** El CI conduce **los 48 journeys core** (sin `--only`), luego afirma 13 por nombre, más un run con `--axis transition`, más `j105` en el binario normal, más `j97` con **y sin** `-tags bench_fixture`. Y hay **3 ejes** registrados, no 4, y 2 de los 4 documentados no existen. La "cobertura del bench" no era un hueco de verificación: era un hueco de lectura.

6. **§2.1 y la tabla de §1.1 dan a entender que `darwin-runtime` no está activado por descuido.** El Informe 1 dice que "sugiere que Alan tiene intención de activarlo pero no lo ha hecho". La segunda pasada refuerza: `formatter_ordering_test.go` ya lo trata como required y le exige el contrato fail-closed, y fue añadido explícitamente para que el slicing de secciones siga siendo honesto. No es descuido; es intención codificada, pendiente sólo del ruleset.

7. **§10 ("Alan no usa su cuenta personal para push... no verificado").** No se ha resuelto y no se resolverá con metadatos públicos. Pero la premisa del encargo sobre `gentle-pi` sí es incorrecta y conviene registrarlo: `gentle-pi` es de `gentle-shell`, no de `gentle-ai`, y no existe paquete npm `gentle-ai`. El "catálogo de 26 skills" no existe: 11 públicos + 15 embebidos.

8. **Lo que el Informe 1 hizo bien y hay que preservar:** el mapa de workflows, la distinción informativo/trusted del tamaño, el ratchet de deadcode como caso de estudio, la lectura del preflight de release, el catálogo `odd/tasks`, y la disciplina de declarar lo no verificado. Los tres "sin verificar" que resolvió su propia lista eran reales; el problema fue el **alcance** (depth-50), no el método.

---

## 5. Síntesis final: las 3 ideas con mayor genio-por-línea de código (ambos informes)

### 1. El manifiesto ordenado de IDs que sustituye a un contador entero (D4, N1) — Informe 2

**~40 líneas de test y un fichero de texto** para eliminar una clase completa de corrupción silenciosa del catálogo, con un experimento de merge medido que documenta incluso el caso en que el manifiesto *sí* conflictúa, y con el incidente real fechado (#3037/#3038, 2026-08-11, `main` rojo en 95 bajo baseline 94). La relación genio/línea es obscena porque la idea es *"no cuentes, enumera"* y el resto del test es el mensaje de error que nombra al ofensor. Es inmediatamente aplicable a cualquier lista que hoy fijemos con un número.

### 2. Tests que leen el YAML del CI y manejan los scripts de release con `gh`/`minisign` falsos (D10, D11; N5, N6) — Informe 2

**Unos cientos de líneas** que cubren el eslabón que nadie prueba: el propio pipeline. Afirman que ningún job requerido puede saltarse el guard de formato (incluida la comprobación de que la lista de jobs no se deje ninguno), que cada test de Windows está reclamado por exactamente un shard consultando el inventario real, que un secreto aparece exactamente una vez, que cada `uses:` está pinneado a 40 hex, que el verificador de release sólo llama a `gh` dos veces y por la superficie read-only, y que una inyección de linker en `MINISIGN_PUBLIC_KEYS` **no produce binario**. Es el mayor radio de explosión por línea que he encontrado en cualquiera de los dos informes, y encaja tal cual en un repo Python con `pytest`.

### 3. Reemplace sólo el razonamiento del modelo; mantenga real todo lo demás (D10 del informe, §"testing-agents-deterministically") — Informe 2

**Un servidor `httptest` de ~200 líneas y un fixture adversarial** para convertir un E2E de agente —hasta entonces caro, no determinista, dependiente de red y con secreto— en una prueba **gratuita, offline, determinista y sin secretos**, y encima *más* fuerte, porque el fixture **inspecciona la petición entrante** y falla si la evidencia llega fuera de orden. El detalle que la hace genio y no truco: `edit: deny` en el agente, de modo que toda mutación tiene que pasar por el CLI; y la regla explícita de dejar fuera del gate lo que es intrínsecamente no determinista (*"whether a prompt reliably steers a live model is a product question, answered by usage, not by CI"*). Nosotros no tenemos un runtime de IA propietario que medir, pero sí tenemos (o tendremos) consumidores de modelos; y el principio "el runtime real, sólo la razón sustituida" es el mejor marco conceptual que ofrecen los dos informes para probar cualquier sistema con un LLM dentro.

**Mención de honor:** el *presupuesto de bloqueo* y *"fail-closed must never be fail-mute"* de la política de congelación (D/N15). No es código, y por eso no compite en genio-por-línea; pero es la idea que más fricción humana ahorra por página escrita, y la que más rápido deberíamos copiar tal cual.

---

## Anexo — comandos ejecutados (verificado ejecutando)

```
# Profundización del clon (read-only sobre el remoto)
cd /tmp/gentle-ai-research && git fetch --deepen 1000     # 256 -> 3910 commits, tags v1.0.4+

# Bench: build, vet y tests (módulo bench/)
cd bench && go vet ./...                                   # exit 0
cd bench && go test -run TestRegisteredJourneysMatchTheManifest -count=1 .   # ok 0.013s
cd bench && go test -count=1 .                             # ok 4.786s

# Ejes registrados (prueba de que damaged-store y real-world ya no existen)
cd bench && go build -o /tmp/gab .
/tmp/gab run --axis damaged-store --binary /bin/true --out /tmp/dsx.json
  -> unknown axis "damaged-store" (registered: compatibility, model-picker, transition, or `all`)
/tmp/gab run --axis real-world  --binary /bin/true --out /tmp/rwx.json
  -> unknown axis "real-world" (registered: compatibility, model-picker, transition, or `all`)
/tmp/gab run --axis compatibility --binary /bin/true --out /tmp/cwx.json
  -> arranca el core + el eje (j05, j10, ...)

# Metadatos públicos (lectura)
gh api repos/Gentleman-Programming/gentle-ai/rulesets/13932547
gh api repos/Gentleman-Programming/gentle-ai/labels
gh api "repos/.../actions/workflows/ci.yml/runs?per_page=100"
gh api "repos/.../actions/workflows/ci.yml/runs?branch=main&per_page=100"
gh api "repos/.../actions/workflows/windows-full-suite.yml/runs?per_page=100"
gh api "repos/.../actions/workflows/promote-stable-rc.yml/runs?per_page=20"
gh api "repos/.../actions/workflows/release.yml/runs?per_page=10"
npm view gentle-pi

# Historia
git log --follow -- <ficheros clave>
git log -1 --format='%s%n%n%b' <sha>          # cuerpos de commit de CI/release
git show --stat 838977fd                        # borrado del eje real-world
```

**Bloqueantes o límites de esta pasada:** (a) no se descargaron logs de runs, por lo que el uso real de `recovery_state=verify-existing` queda sin confirmar en vivo; (b) no se pudo determinar con metadatos públicos quién pulsó la etiqueta `status:approved` en cada issue (sólo que no hay automatización); (c) `bench/results.json` comiteado en la raíz se describió leyéndolo, no se re-ejecutó el run que lo produjo; (d) CodeGraph no se inicializó por la restricción de directorio temporal, de modo que las relaciones estructurales se derivaron por lectura directa y `git`.
