# Protección de la rama `main`

Este documento registra la política esperada de GitHub durante el pre-MVP. La
configuración viva de GitHub es la autoridad.

## Rama protegida

`main` es la única rama de entrega protegida. Todo cambio llega mediante un
pull request; el push directo no es una vía de entrega.

El ruleset restringe las actualizaciones a los roles `Maintain` y `Admin`.
`Write` permite contribuir y revisar, pero no mergear en `main`.

El bypass de esos roles solo opera mediante pull request. No permite omitir el
PR ni hacer push directo.

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
- Restringir el merge a `Maintain` y `Admin` mediante pull request.
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
