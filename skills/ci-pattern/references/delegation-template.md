# Plantilla de encargo de delegación (HR-36)

Regla única del encargo: **todo dato se llena desde una lectura en vivo del
repositorio, con el comando y su salida estampados junto al dato.** Un dato
sin comando es una hipótesis, no un hecho (HR-25). Los comandos de esta
plantilla son genéricos; los valores son específicos del repo destino y se
rellenan en cada encargo. La plantilla no sustituye al GATE DE ADOPCIÓN
del §1 de `SKILL.md`: la adopción de un repo nuevo exige antes el porting-guide
completo.

El worker recibe este encargo tal cual, verifica en vivo cada bloque antes de
actuar, y ante cualquier desajuste **reporta el desajuste y se detiene**;
nunca se adapta en silencio a una prescripción obsoleta.

---

## Encargo: <título de la unidad de trabajo>

- **Issue:** `<owner>/<repo>#<N>` — URL verificada de la issue
- **Delegado por / a:** <actor orquestador> → <actor worker>
- **verified_at:** `<UTC timestamp>` (regenerar en cada re-emisión del encargo)

## 1. Repo

| Campo | Valor | Comando de verificación (en vivo) | Salida observada |
|---|---|---|---|
| Owner/name canónico | | `gh repo view <owner>/<name> --json nameWithOwner,url` | |
| Remote URL | | `git -C <ruta-local> remote get-url origin` | |
| Ruta local | | `git -C <ruta-local> rev-parse --show-toplevel` | |

Regla: el repo no se nombra en prosa de memoria. La URL remota leída de
vuelta `MUST` coincidir con la issue; el caso real que motivó esta regla fue
un encargo que decía un repo y cuyo trabajo vivía en otro. Si el remote leído
no coincide con el repo de la issue: parada y reporte (repo equivocado).

## 2. Base y tip

| Campo | Valor | Comando de verificación (en vivo) | Salida observada |
|---|---|---|---|
| Ref base | | `git -C <ruta> rev-parse <base>` (o `gh pr view <N> --json baseRefName,headRefOid`) | |
| SHA tip actual | | `git -C <ruta> rev-parse HEAD` | |
| Run de CI vigente | | `gh run list --branch <rama> --limit 1` | |

Regla: el SHA `MUST` leerse en vivo en el momento de emitir y en el momento
de ejecutar; nunca copiarse de un reporte anterior (un SHA de slice que ya se
movió invalida todo lo que cuelga de él).

## 3. Worktree

- **Ruta del worktree nuevo:** `<ruta>` — `git -C <repo> worktree add <ruta> -b <rama>`
- **Rama:** generada con `assets/branch-name.sh`
  (`new --issue <N> --type <tipo> --slug-from <texto>`), nunca escrita a mano
  (HR-35); salida del generador estampada aquí.
- **Regla de actor:** un worktree por actor concurrente (HR-24). Dos workers
  `MUST NOT` compartir working tree ni rama; si el worktree ya existe, se
  reclama desde el estado real (`git worktree list`), no desde la memoria.

## 4. Superficies de edición permitidas

Rutas relativas al repo, derivadas listando el árbol real (no de memoria):

```
git -C <ruta> ls-tree -r --name-only <tip> -- <prefijos>   # o git ls-files
```

- `<ruta/a/fichero>` — verificado: existe en `<tip>` el `<fecha>` (comando: `git -C <ruta> cat-file -e <tip>:<ruta> && echo EXISTS`)
- `<ruta/a/directorio/>` — ídem

Regla: **una entrada que no resuelve es un defecto del encargo, no una
errata del worker.** El worker reporta la entrada rota y se detiene; el
orquestador la corrige con su comando de verificación y re-emite.

## 5. Hechos en vivo a verificar antes de actuar

Toda prescripción del orquestador (conteos, rutas de test, SHAs, nombres de
rama, existencia de ficheros) se lista aquí como hipótesis con su comando:

| Hecho prescrito | Valor prescrito | Comando de verificación | Resultado del worker (en vivo) |
|---|---|---|---|
| Ejemplo: pasos del job de lint | 20 | `<preflight del consumer>` | 19 — desajuste reportado |
| | | | |

Regla: el worker trata cada fila como hipótesis (HR-25); un desajuste se
reporta en su primer reporte de progreso y detiene la fase afectada. Un
desajuste adaptado en silencio es una violación de HR-25, no una iniciativa.

## 6. Condiciones de parada

- Cualquier desajuste del §2, §4 o §5: parar y reportar.
- Cualquier gate rojo cuya causa no sea identificable al paso exacto
  (`gh api repos/<org>/<repo>/actions/jobs/<id>`): parar y reportar.
- Cualquier cambio de alcance respecto de la issue: parar y reportar.
- Regla de vigías: NINGÚN watcher ni bucle de sondeo (HR-9, HR-23); la
  espera se resuelve mecanismo > script > IA.

## 7. Plazo y progreso

- **Deadline:** `<fecha/hora UTC>` — al vencer, el worker reporta estado y se
  detiene; no extiende el plazo por su cuenta.
- **Reporte de progreso:** una línea por transición de estado
  (`iniciado <fase>` / `<fase> ok con <evidencia>` / `bloqueado: <motivo>`,
  con su comando y salida). Sin transición nueva, sin reporte nuevo.

---

### Cómo se rellena (contrato del orquestador)

1. Ejecute cada comando de la plantilla contra el repo real y copie la
   salida observada junto al campo; estampe `verified_at` en UTC.
2. Genere la rama con `assets/branch-name.sh` y pegue su salida (HR-35).
3. Liste y verifique cada superficie de edición del §4 contra `<tip>`.
4. Enumere en §5 toda afirmación que el worker no pueda derivar solo.
5. Re-emita el encargo si pasa el tiempo o avanza la base: los campos de
   §2 y §5 caducan con el SHA, no con el calendario.
