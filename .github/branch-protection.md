# Protección de la rama `main`

Este documento registra la política esperada de GitHub durante el pre-MVP. La
configuración viva de GitHub es la autoridad.

## Rama protegida

`main` es la única rama de entrega protegida. Todo cambio llega mediante un
pull request; el push directo no es una vía de entrega.

El ruleset `main-maintainers-and-admins-merge` restringe las actualizaciones a
los roles `Maintain` y `Admin` cuando está activo.
`Write` permite contribuir y revisar, pero no mergear en `main`.

El bypass de esos roles solo opera mediante pull request; no permite omitir
el PR ni hacer push directo.

**Estado actual: `disabled`** (issue #892, 2026-09-23). En un repo de
mantenedor único esa restricción no frena a nadie salvo al propio
mantenedor — es fricción sin protección real, y además `gh pr merge` sin
`--admin` no disparaba el bypass aunque el actor calificara, obligando a usar
`--admin` (que saltea también los checks requeridos, no solo esta regla) en
cada merge. Reactive el ruleset (`enforcement: active` vía
`gh api --method PUT repos/.../rulesets/22650195`) el día que se incorpore un
segundo colaborador con rol `Write` que no deba poder mergear sin
supervisión — mismo criterio que la política de revisión más abajo.

## Checks requeridos

| Check | Propósito |
|---|---|
| `ci / required` | Agrega los jobs aplicables y falla de forma cerrada. |
| `pr-name / branch-name` | Exige ramas `<type>/<issue>-<slug>`. |
| `pr-size / pr-size` | Exige 400 líneas o una excepción aprobada. |

Solo la matriz versionada puede aceptar un job omitido. Un resultado ausente,
cancelado, fallido u omitido sin permiso bloquea el merge.

## Política de revisión

El número de aprobaciones requeridas es `0`. El proyecto tiene un único
mantenedor; exigir una segunda persona impediría integrar cualquier PR.

Esto no relaja el gate automático: todos los checks deben quedar verdes. La
exigencia de conversaciones resueltas está desactivada
(`required_conversation_resolution.enabled: false`, issue #972); ver
«Estado verificado».

Cuando se incorpore un segundo mantenedor humano, eleve el requisito a `1` y
actualice `CODEOWNERS`.

## Ajustes aplicados

- Exigir pull request y rama actualizada antes del merge.
- Exigir todas las conversaciones resueltas — **desactivado** desde el issue #972 (CodeQL no debe bloquear merges por hilos de alertas preexistentes); ver «Estado verificado».
- Aplicar las reglas también a administradores.
- Restringir el merge a `Maintain` y `Admin` mediante pull request — **desactivado** desde el issue #892 (2026-09-23); reactivar al incorporar un segundo colaborador `Write`.
- Prohibir force-push y borrado de la rama.
- Permitir merge commits y mantener desactivado el historial lineal.

## Auditoría post-hoc de push directo

La rama clásica bloquea force-push y borrado pero no un push directo
legítimo de un actor con permisos. Varias sesiones de agente en paralelo
comparten la única credencial admin (`el-Gentleman <alan@apap.local>`);
un ruleset que restrinja el merge a roles concretos no las distingue, y
reactivarlo reintroduciría la fricción `--admin` que #892 cerró. La
cobertura del push directo la aporta `.github/workflows/main-audit.yml`
(issue #986), que:

- Recorre los últimos 30 commits de `origin/main` cada día a las 05:30 UTC
  (también bajo `workflow_dispatch`).
- Marca como infractor cualquier commit sin un pull request cuyo
  `merge_commit_sha` coincida con su SHA — exceptuando los commits que
  son ancestros del segundo padre de un merge commit de PR en `main`
  (commits intermedios legítimos de la rama del PR).
- Crea o actualiza **una** issue de seguimiento titulada
  `chore(gobernanza): push directo detectado en main` con la evidencia;
  no falla el workflow.

El ruleset `main-maintainers-and-admins-merge` permanece desactivado
(issue #892). Su condición de reactivación — segundo mantenedor humano
con rol `Write` que no deba poder mergear sin supervisión — no cambia.

## Verificación

Compruebe ambas capas tras cambiar un check o un rol:

```bash
gh api repos/ardelperal/APAP_WEB/branches/main/protection
gh api repos/ardelperal/APAP_WEB/rulesets
```

Inspeccione el ruleset activo sobre `main`: actores, modo de bypass, checks,
restricción de actualización, borrado y non-fast-forward.

Si este archivo y la API divergen, existe drift de configuración. Corríjalo
antes del siguiente merge.

## Estado verificado el 2026-09-27

Protección clásica vigente sobre `main`:

- `enforce_admins.enabled`: `true` — los administradores también pasan por
  los checks requeridos.
- `allow_force_pushes.enabled`: `false` y `allow_deletions.enabled`:
  `false` — sin reescritura ni borrado de la rama.
- `required_status_checks`: `["branch-name", "required", "pr-size / pr-size"]`
  — los tres checks agregados que `ci.yml` y los workflows satélite publican.
- `required_conversation_resolution.enabled`: `false` — desactivado por
  issue #972 para que CodeQL no bloquee merges por hilos de alertas
  preexistentes.
- `restrictions`: `null` — sin restricción de roles a nivel clásico; la
  restricción vive (desactivada) en el ruleset `main-maintainers-and-admins-merge`.

Rulesets activos sobre `main`: cero. El único ruleset declarado
(`main-maintainers-and-admins-merge`, id 22650195) está en `enforcement:
disabled` desde el 2026-09-23 (issue #892).
