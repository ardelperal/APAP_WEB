# APAP Inventory Baseline

## Source export snapshot

`src/` currently contains an Access source snapshot exported from the APAP frontend. Dysflow export has now been verified for project id `apap`.

- Standard modules: 7
- Class modules: 14
- Forms detected by Dysflow: 60
- Form code-behind files: 60+
- Form definition files: 60+
- Reports detected by Dysflow: 2 (`Subinforme TbRecomendaciones`, `Terapias`)
- Report export files in `src/reports`: 0 detected

> Note: The source export now works through Dysflow. Report extraction needs focused verification because reports are visible in Access inventory but no report files are present under `src/reports`.

## Backend tables detected through Dysflow

- TbAcciones
- TbAcogidaAnimal
- TbAcogidaAnimalMaterial
- TbAcogidaCasas
- TbActuacionSanitaria
- TbActuacionSanitariaAux
- TbAdopcion
- TbAnexos
- TbAuxAnimales
- TbAuxAnimalesDesparasitacion
- TbAuxPruebasPendientes
- TbCesionPorPropietario
- TbContratosAnexos
- TbDesparasitacionMultipleExternaDetalle
- TbDesparasitacionMultipleExternaPpal
- TbDesparasitacionMultipleInternaDetalle
- TbDesparasitacionMultipleInternaPpal
- TbEntradas
- TbEntradasMultiplesAuxIniciales
- TbEntradasMultiplesAuxSeleccionados
- TbFichaAnimal
- TbFichaSanitariaPrincipalAux
- TbInformes
- TbInformeTrimestralCoordenadasDatos
- TbMaterial
- TbMaterialesParaAcogidaAntes
- TbMotivosEntrada
- TbNombrePruebas
- TbOpciones
- TbOrigenEntrada
- TbPlantillas
- TbPruebasPeridicidad
- TbRecomendaciones
- TbRIAC
- TbTamaños
- TbTerapias
- TbVersion
- TbVoluntariosParaAutorrellenables

## Initial domain signals

- Animal records and chip management: `TbFichaAnimal`, `TbRIAC`.
- Intake workflows: `TbEntradas`, `TbMotivosEntrada`, `TbOrigenEntrada`, `TbCesionPorPropietario`.
- Foster homes and foster stays: `TbAcogidaCasas`, `TbAcogidaAnimal`, `TbAcogidaAnimalMaterial`.
- Adoption workflows: `TbAdopcion`, `TbContratosAnexos`.
- Health records: `TbActuacionSanitaria`, `TbNombrePruebas`, desparasitation tables, therapies, recommendations.
- Documents and attachments: `TbAnexos`, `TbPlantillas`, `TbInformes`.
- Materials/inventory: `TbMaterial`, `TbMaterialesParaAcogidaAntes`.
