# assets/templates — plantillas del scaffolder (wave siguiente)

Este directorio alojará las plantillas parametrizadas que `ci-pattern adopt`
copiará al repo destino, sustituyendo los parámetros P01–P48
(`assets/parameters.schema.json`).

**Estado:** vacío a propósito. La extracción de las plantillas desde el origen
(`ardelperal/APAP_WEB`, 62 activos del inventario
`references/asset-inventory.md` de esta skill) es la wave siguiente,
junto con `adopt` y `update`. La wave entregada (2026-10-02) es la CLI
determinista de validación y verificación: `params validate`, `verify`,
`status`, el manifiesto `.governance-manifest.json` y su esquema de parámetros.

No invente plantillas aquí: las que aterricen deben salir del árbol verificado
del origen, nunca de memoria.
