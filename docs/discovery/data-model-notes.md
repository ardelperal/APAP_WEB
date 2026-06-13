# APAP Data Model Notes

## Core entities identified

## Initial row counts

- `TbFichaAnimal`: 1,330
- `TbEntradas`: 1,596
- `TbAdopcion`: 1,159
- `TbAcogidaAnimal`: 305
- `TbActuacionSanitaria`: 14,815

### Animal (`TbFichaAnimal`)

Primary business identifier appears to be `NCHIP`.

Required fields include:

- `NCHIP`
- `NombreAnimal`
- `Especie`
- `Sexo`
- `FNacimiento`
- `Terapia`

Important lifecycle fields:

- `Situacion`
- `FDefuncion`
- `UltimoEstadoAntesDeFallecido`
- `Eutanasia`, `EutanasiaOtrasCausas`, `EutanasiaEnfermedad`
- `ComunicacionARIAC`

### Intake (`TbEntradas`)

Required fields include:

- `IDEntrada`
- `NChip`
- `NCONTRATOENTRADA`
- `FEntradaProtectora`
- `NombreDelQueEntrega`
- `FechaRecogida`
- `PropietarioEntregador`
- `DonativoEntregador`
- `DNIEntregador`
- `VoluntarioEntrada`

Important workflow fields:

- `FSalida`
- `Origen`
- `MotivoEntrega`
- `IDAdopcionOrigen`
- `IDAcogidaOrigen`
- `FEntregaAPropietario`

### Adoption (`TbAdopcion`)

Required fields include:

- `IDAdopcion`
- `NCHIP`
- `NContrato`
- `FAdopcion`
- `VoluntarioSeguimiento`
- `ResponsableAdopcion`
- `TelMovilVoluntarioSeguimiento`
- `emailVoluntarioSeguimiento`
- `CalleAdoptante`
- `ProvinciaAdoptante`
- `NombreAdoptante`
- `ApellidosAdoptante`
- `DNIAdoptante`

Important workflow fields:

- `TipoAdopcion`
- `CompromisoEsterilizacion`
- `FDevolucion`
- `FechaImpresoEntregado`
- `FechaImpresoAdjunto`
- `FormaDePago`
- `NumeroReciboPago`

### Foster stay (`TbAcogidaAnimal`)

Required fields include:

- `NCONTRATOACOGIDA`
- `IDAcogidaCasa`
- `Nchip`
- `Finicial`

Important workflow fields:

- `FFinal`
- `TipoAcogida`
- `VoluntarioSeguimiento1/2`
- `VoluntarioCosasSanitarias`
- `VoluntarioAcogida`

### Health action (`TbActuacionSanitaria`)

Required fields include:

- `NCHIP`
- `FechaAnotacion`

Important workflow fields:

- `Prueba`
- `Resultado`
- `Lote`
- `CodVeterinario`
- `TipoAnotacion`
- `Clinica`
- `Producto`
- `Titulo`

## Relationships detected

- `TbFichaAnimal.NCHIP` -> `TbTerapias.NCHIP`
- `TbFichaAnimal.NCHIP` -> `TbAnexos.NChip`
- `TbEntradas.IDEntrada` -> `TbAnexos.IDEntrada`
- `TbEntradas.IDEntrada` -> `TbCesionPorPropietario.IDEntrada`
- `TbEntradas.IDEntrada` -> `TbContratosAnexos.IDEntrada`
- `TbAdopcion.IDAdopcion` -> `TbAnexos.IDAdopcion`
- `TbAdopcion.IDAdopcion` -> `TbContratosAnexos.IDAdopcion`
- `TbAcogidaCasas.IDAcogidaCasa` -> `TbAcogidaAnimal.IDAcogidaCasa`
- `TbAcogidaAnimal.IDAcogida` -> `TbAcogidaAnimalMaterial.IDAcogida`
- `TbAcogidaAnimal.IDAcogida` -> `TbAnexos.IDAcogida`
- `TbAcogidaAnimal.IDAcogida` -> `TbContratosAnexos.IDAcogida`
- `TbTerapias.IdTerapia` -> `TbRecomendaciones.IDTerapia`

## Migration implications

- `NCHIP` is a natural identifier and appears central to animal-linked workflows.
- The future web app should model animal lifecycle explicitly: intake, foster stay, adoption, return/devolution, death/euthanasia, health actions, documents.
- Several fields encode states as text. These need domain catalogs/enums before migration.
- Attachment/contract/report tables must be analyzed together with file system folders (`Anexos`, `contratos`, `Informes`, `Plantillas`).
