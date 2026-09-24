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

Esto no relaja el gate automático. Todos los checks deben quedar verdes y todas
las conversaciones deben resolverse.

Cuando se incorpore un segundo mantenedor humano, eleve el requisito a `1` y
actualice `CODEOWNERS`.

## Ajustes aplicados

- Exigir pull request y rama actualizada antes del merge.
- Exigir todas las conversaciones resueltas.
- Aplicar las reglas también a administradores.
- Restringir el merge a `Maintain` y `Admin` mediante pull request — **desactivado** desde el issue #892 (2026-09-23); reactivar al incorporar un segundo colaborador `Write`.
- Prohibir force-push y borrado de la rama.
- Permitir merge commits y mantener desactivado el historial lineal.

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
