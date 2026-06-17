# Flujo Legacy: Contratos de ParaFirma a Firmados

**Fecha**: 2026-06-13
**Estado**: Exploración completa con evidencia de código
**Objetivo**: Documentar con precisión el flujo exacto de movimiento de contratos desde generación hasta firma, para diseño de APAP_WEB.

---

## 1. Resumen Ejecutivo

El flujo legacy tiene **dos fases claramente separadas** que NO están conectadas automáticamente:

| Fase | Acción | Directorio | Quién la ejecuta |
|------|--------|------------|-----------------|
| **Generación** | `Plantilla.GenerarDocumento()` crea Word con mail-merge | `contratos/ParaFirma/` | Sistema (automático) |
| **Firma + Anexado** | Usuario selecciona archivo firmado desde cualquier lugar | `contratos/Firmados/` | Usuario (explorador de archivos) |

**Hallazgo clave**: NO existe código que mueva, copie o elimine archivos de `ParaFirma/` a `Firmados/`. Son flujos independientes. El usuario elige manualmente qué archivo adjuntar.

---

## 2. Fase 1: Generación del Documento (ParaFirma)

### 2.1 Punto de entrada
Cada formulario de gestión tiene un botón "Generar Contrato" que invoca:

```vba
' Form_FormEntradaGestion.cls:438
strURLDocumento = MiPlantilla.GenerarDocumento("IDEntrada", strIDEntradaSeleccionada, "Sí", "Entrada", _
    m_ObjEntorno.URLDirectorioContratosParaFirma, , , strTextoError)

' Form_FormAcogidaGestion.cls:535
strURLDocumento = MiPlantilla.GenerarDocumento("IDAcogida", strIDAcogidaSeleccionada, "Sí", "Acogida", _
    m_ObjEntorno.URLDirectorioContratosParaFirma, , , strTextoError)

' Form_FormAdopcionesGestion.cls:356
strURLDocumento = MiPlantilla.GenerarDocumento("IDAdopcion", strIDAdopcionSeleccionada, "Sí", "Adopción", _
    m_ObjEntorno.URLDirectorioContratosParaFirma, , , strTextoError)
```

### 2.2 Flujo interno de `Plantilla.GenerarDocumento()`
**Ubicación**: `src/classes/Plantilla.cls:2228`

1. `CopiarPlantillaEnSuSitio()` copia `.docx` desde `Plantillas/` a directorio local
2. Crea instancia `Word.Application`, abre documento
3. Rellena datos según tipo (`RellenarContratoEntrada`, `RellenarContratoAcogida`, etc.)
4. Guarda en local, copia a `contratos/ParaFirma/`, elimina temporal

### 2.3 Nomenclatura generada
```
contratos/ParaFirma/Entrada_0003.docx
contratos/ParaFirma/AcogT_0015.docx
contratos/ParaFirma/Adop_0042.docx
```

### 2.4 Estado post-generación
- El archivo queda en `ParaFirma/` como borrador Word editable
- **NO se crea registro en `TbContratosAnexos`** en esta fase
- El usuario debe abrir el Word, imprimirlo/firmarlo externamente

---

## 3. Fase 2: Anexado del Contrato Firmado (Firmados)

### 3.1 Acción del usuario
El usuario hace clic en el botón `ComandoAnexarContrato` (caption: "Anexar Contrato").

### 3.2 Flujo del `ComandoAnexarContrato_Click()`
**Evidencia**: `Form_FormEntradaGestion.cls:1384`, `Form_FormAcogidaGestion.cls:71`, `Form_FormAdopcionesGestion.cls:728`

```vba
Private Sub ComandoAnexarContrato_Click()
    strTituloBoton = Me.ComandoAnexarContrato.Caption
    
    If strTituloBoton = "Anexar Contrato" Then
        ' Abre EXPLORADOR DE ARCHIVOS (file picker)
        strURLContratoInicial = AbrirExplorador("Seleccione el contrato", strUltima)
        
        ' Valida que el usuario no canceló
        If InStr(1, strURLContratoInicial, ":\") = 0 Then Exit Sub
        
        ' Verifica si ya existe contrato para esta entidad
        flag = Dame("TbContratosAnexos", "NombreArchivo", "IDEntrada", strIDEntradaSeleccionada, True)
        If strTextoOKOtro <> "" Then
            MsgBox "Ya hay anexado un contrato. ¿Desea sustituirlo?"
        End If
        
        ' Llama a Anexo.AnexarContrato()
        flag = MiAnexo.AnexarContrato(strURLContratoInicial, strIDEntradaSeleccionada)
        
        MsgBox "¿Desea verlo ahora?"
    Else
        ' Si caption = "Eliminar Contrato" → eliminar
        flag = MiAnexo.EliminarContrato(strIDEntradaSeleccionada)
    End If
End Sub
```

### 3.3 El Explorador de Archivos
**Ubicación**: `src/modules/Explorador.bas:4`

```vba
Public Function AbrirExplorador(Title As String, ...) As String
    Set fDialog = Application.FileDialog(msoFileDialogFilePicker)
    With fDialog
        .AllowMultiSelect = False
        .Title = Title
        .InitialFileName = strUbicacionInicial  ' Último directorio usado
        .Filters.Add "Todos los documentos", "*.*"
    End With
End Function
```

**Comportamiento**: Se abre un `FileDialog` de Office (explorador de Windows) **sin filtro específico**. El usuario puede navegar a **CUALQUIER archivo** en el sistema.

### 3.4 Método `Anexo.AnexarContrato()`
**Ubicación**: `src/classes/Anexo.cls:12`

1. Valida que el archivo existe
2. Obtiene el nombre del contrato desde la entidad (ej. `TbEntradas.NCONTRATOENTRADA`)
3. Construye ruta final: `URLDirectorioContratosFirmados & strContrato & "." & strExtension`
4. Verifica si el archivo final está abierto
5. Busca/inserta/actualiza registro en `TbContratosAnexos`
6. **COPIA el archivo** a Firmados: `FSO.CopyFile strURLContrato, strURLContratoFinal, True`

---

## 4. Pregunta Clave: ¿Se conserva el documento de ParaFirma?

### 4.1 Evidencia de código

**NO existe código que:**
- Elimine archivos de `contratos/ParaFirma/` después del anexado
- Mueva archivos de `ParaFirma/` a `Firmados/`
- Haga referencia a `ParaFirma/` dentro de `AnexarContrato()`

### 4.2 Comportamiento real

| Directorio | Contenido | ¿Se modifica? |
|------------|-----------|----------------|
| `contratos/ParaFirma/` | Borradores Word generados por el sistema | **NO** — se acumulan indefinidamente |
| `contratos/Firmados/` | Archivos firmados seleccionados por el usuario | Sí — se copian/eliminan por acción del usuario |

### 4.3 Implicaciones
- El documento de ParaFirma **queda como borrador** después de la firma
- El archivo Firmado **puede ser un PDF escaneado**, no necesariamente el Word original
- El usuario podría adjuntar un archivo que **nunca estuvo en ParaFirma**
- No hay relación forzada entre el borrador generado y el archivo anexado

---

## 5. Tabla `TbContratosAnexos`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `NombreArchivo` | Texto | Nombre del archivo firmado (ej. `E_0003.pdf`) |
| `Contrato` | Texto | Número/identificador del contrato |
| `Fecha` | Fecha/Hora | Fecha de anexado (`Now()`) |
| `IDEntrada` | Número | FK → `TbEntradas.IDEntrada` |
| `IDAcogida` | Número | FK → `TbAcogidaAnimal.IDAcogida` |
| `IDAdopcion` | Número | FK → `TbAdopcion.IDAdopcion` |

**Regla**: Solo UN contrato por tipo por entidad.

---

## 6. Recomendaciones para APAP_WEB

| Decisión | Recomendación | Rationale |
|----------|---------------|-----------|
| **Conservar borrador** | Sí, mantener en ParaFirma como referencia | El legacy lo hace implícitamente |
| **Formato de subida** | PDF obligatorio, Word opcional | El usuario típicamente firma y escanea a PDF |
| **Naming en Firmados** | `{Tipo}_{ID}.{ext}` | Compatibilidad con rutas existentes |
| **Registro DB** | `TbContratosAnexos` con los mismos campos | Mantener modelo existente |
| **Reemplazo** | Confirmar antes de sobrescribir | El legacy ya lo hace |
| **Eliminación** | Solo eliminar de Firmados, nunca de ParaFirma | El legacy NO toca ParaFirma |
| **File picker** | Abrir en directorio por defecto | El legacy usa último directorio usado |
| **Validación** | Solo 1 contrato por tipo por entidad | Regla de negocio existente |

---

## 7. Archivos Relevantes

| Archivo | Rol |
|---------|-----|
| `src/classes/Anexo.cls` | `AnexarContrato()`, `EliminarContrato()` |
| `src/classes/Plantilla.cls` | `GenerarDocumento()`, `CopiarPlantillaEnSuSitio()` |
| `src/classes/Entorno.cls` | Directorios de contratos |
| `src/modules/Explorador.bas` | `AbrirExplorador()` — file picker |
| `src/modules/Funciones Generales.bas` | `VerContrato()`, `ActivarDesactivarImagenes()` |
| `src/forms/Form_FormEntradaGestion.cls` | `ComandoAnexarContrato_Click()` |
| `src/forms/Form_FormAcogidaGestion.cls` | `ComandoAnexarContrato_Click()` |
| `src/forms/Form_FormAdopcionesGestion.cls` | `ComandoAnexarContrato_Click()` |
