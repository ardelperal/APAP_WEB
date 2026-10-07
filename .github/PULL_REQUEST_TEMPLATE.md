## Issue vinculada

<!--
La rama `<tipo>/<N>-<slug>` identifica la issue `#N`; el gate `issue-spec` no lee este texto.
- PR único o tramo final: `Closes #N` (GitHub cierra la issue al fusionar).
- Tramo intermedio de una cadena: etiqueta `chain:partial`, misma `N` en la rama y `Refs #N` en lugar de `Closes`.
-->

Closes #

## Tipo

- [ ] Bug fix (`type:bug`)
- [ ] Nueva capacidad (`type:feature`)
- [ ] Documentación (`type:docs`)
- [ ] Refactor (`type:refactor`)
- [ ] Mantenimiento o tooling (`type:chore`)

## Resumen

- <!-- Resuma el cambio. -->

## Comandos ejecutados

<!-- Pegue cada comando y su resultado real, no una descripción. -->

```
$ <comando>
<salida real>
```

## Alcance

| Incluido | Fuera de alcance |
|---|---|
|  |  |

## Validación

- [ ] La issue vinculada contiene una spec completa y `status:approved`.
- [ ] Se han ejecutado los comandos indicados en la issue.
- [ ] La documentación refleja el comportamiento entregado.
- [ ] El commit usa Conventional Commits y no contiene atribución de IA.

## Excepción de tamaño

Deje esta sección vacía salvo que el diff supere 400 líneas y no quepa dividirlo. El motivo escrito aquí es el override real que lee el gate `pr-size` (issue #1121); el label `size:exception` es opcional e informativo. Si edita el cuerpo con el PR abierto, relance el job fallido de `ci` (`gh run rerun <run-id> --failed`): editar no recalcula el check.

`size-exception-reason:` <motivo en una sola línea>
