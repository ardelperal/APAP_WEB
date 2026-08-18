---
name: legacy-initial-dashboard
description: Panel histórico de inicio y contadores en Access/VBA.
license: Proprietary
metadata:
  author: APAP_WEB maintainers
  version: 1.0.0
title: "Legacy: Panel inicial Form0Opciones"
status: "migrated"
legacy_source: "src/forms/Form_Form0Opciones.cls + Form_Form0Opciones.form.txt (Access/VBA)"
superseded_by: "docs/architecture/decisiones/d-02-home-dashboard.md"
---

# Panel Inicial Legacy — Form0Opciones

> **Fuente**: `src/forms/Form_Form0Opciones.cls` + `Form_Form0Opciones.form.txt`
> **Tablas backend**: `TbFichaAnimal`, `TbAdopcion`, `TbEntradas`, `TbRIAC`
> **Estado**: Evidencia completa (código + definición de formulario)

## What this doc is

| It is | Evidence in this repo |
|---|---|
| Documentación histórica del formulario de arranque del Access legacy (navegación + 10 contadores). | Tablas `TbFichaAnimal`, `TbAdopcion`, `TbEntradas`, `TbRIAC` descritas en §6. |
| Referencia de QUÉ hacia el producto nuevo (no de CÓMO se presenta). | [d-11-no-clonar-ux-legacy.md](architecture/decisiones/d-11-no-clonar-ux-legacy.md) §5. |

## What this doc is not

| It is not | Use this boundary |
|---|---|
| Una spec para clonar el dashboard en APAP_WEB. | La bandeja operativa moderna vive en [d-02-home-dashboard.md](architecture/decisiones/d-02-home-dashboard.md). |
| Una guía de implementación. | Las specs viven en [openspec/specs/](openspec/specs/). |

## Core invariants

- **Ocultar contador si es 0, mostrar en rojo si hay elementos pendientes**: patrón de "dashboard de lo que necesita atención" (§5).
- **Numeración jerárquica por dominio**: los contadores mantienen la estructura 1.3 (fallecidos), 2.1–2.5 (situación animal), 4.1–4.3 (seguimiento adopciones) — refleja la organización operativa del refugio (§7 §"Prioridad alta").
- **Ribbon visible solo para `adm`**: el control de visibilidad por usuario se traduce a roles de UI en el modelo nuevo (§1).

---

## 1. Descripción General

`Form0Opciones` es el formulario que abre al arrancar la aplicación. Sirve como **panel de control del usuario** con dos zonas funcionales:

1. **Navegación**: 12 botones de imagen con etiquetas hover que abren formularios de gestión.
2. **Contadores y alertas**: 10 etiquetas que muestran conteos en tiempo real de elementos pendientes, con color dinámico (verde = ok, rojo = pendiente).

El formulario solo muestra la barra de herramientas de Access (Ribbon) si el usuario es `"adm"` (`Environ("USERNAME")`).

---

## 2. Estructura del Formulario

### 2.1 Cabecera

| Control | Tipo | Descripción |
|---------|------|-------------|
| `lblTitulo` | Label | "Registro de animales APAP-ALCALÁ" |
| `lblVersion` | Label | Versión actual del sistema (desde `m_ObjEntorno.Version`) |
| `lblEstado` | Label | Texto informativo "Contador Seguimiento" |

### 2.2 Navegación (12 botones)

Cada botón es una imagen (`Image*`) con una etiqueta asociada. Al pasar el ratón, se muestra `lblExplicacion` con una descripción contextual.

| # | Control Label | Caption | Formulario que abre |
|---|--------------|---------|-------------------|
| 1 | `lblConsulta` | Consulta | (consulta general) |
| 2 | `lblFichasAnimales` | Fichas de los Animales | `FormFichaAnimalGestion` |
| 3 | `lblEntradas` | Entradas | `FormEntradasGestion` |
| 4 | `lblSalidas` | Salidas | (formulario de salidas) |
| 5 | `lblAcogida` | Acogidas | `FormAcogidaGestion` |
| 6 | `lblAdopciones` | Adopciones | `FormAdopcionesGestion` |
| 7 | `lblAcogidaCasas` | Casas de acogida | `FormCasaAcogidaGestion` |
| 8 | `lblInformes` | Informes | (generación de informes) |
| 9 | `lblFichasSanitarias` | Datos Sanitarios | (formulario sanitario) |
| 10 | `lblTerapias` | Terapias | (formulario de terapias) |
| 11 | — | Anexos | (documentos adjuntos) |
| 12 | `lblMaterial` | Material | `FormMaterialGestion` |

---

## 3. Contadores y Alertas

Los contadores se calculan al abrir el formulario mediante 4 procedimientos en `Funciones Generales.bas`. Cada etiqueta muestra un número entre paréntesis y cambia de color:
- **`ColorTrabajoPendiente`** (rojo) → hay elementos pendientes
- **`ColorInicalEnlaces`** (verde/neutral) → todo resuelto (label oculto si es 0)

### 3.1 Grupo 1: Situación de Animales

**Fuente de datos**: `TbFichaAnimal` (campo `Situacion`, `NCHIP`)
**Procedimiento**: `ColocarContadoresSituacionAnimal` → `RellenarSituacionAnimales()`

| # | Control | Caption dinámico | Lógica |
|---|---------|-----------------|--------|
| 2.1 | `lblAnimalesEnSituacionIncoherente` | "2.1 Animales en situación incoherente ( N )" | `Situacion = "Incoherente"` |
| 2.2 | `lblAnimalesEnSituacionPteNuevaEntrada` | "2.2 Animales Ptes. de Entrada ( N )" | `Situacion = "Pendiente de Entrada"` |
| 2.3 | `lblAnimalesEnSituacionPteNuevaSituacion` | "2.3 Animales Ptes. de Nueva Situación ( N )" | `Situacion = "Pendiente de Nueva Situación"` |
| 2.4 | `lblAnimalesPtesDeNChip` | "2.4 Animales Ptes. Chip ( N )" | `Left(NCHIP, 3) = "PTE"` |
| 2.5 | `lblAnimalesConChipPendienteDeCambioTitular` | "2.5 Pendientes de Cambio Titular ( N )" | Ver abajo (UNION de Entradas + Adopciones) |

**SQL de 2.5 (Cambio Titular)**:
```sql
-- Entradas desde 2019 sin RIAC y sin origen de acogida
SELECT DISTINCT TbEntradas.NChip
FROM TbEntradas LEFT JOIN TbRIAC ON TbEntradas.IDEntrada = TbRIAC.IDENTRADA
WHERE TbRIAC.IDRIAC Is Null
  AND TbEntradas.FEntradaProtectora >= #1/1/2019#
  AND TbEntradas.IDAcogidaOrigen Is Null
UNION
-- Adopciones desde 2019 sin RIAC
SELECT DISTINCT TbAdopcion.NChip
FROM TbRIAC RIGHT JOIN TbAdopcion ON TbRIAC.IDADOPCION = TbAdopcion.IDAdopcion
WHERE TbRIAC.IDRIAC Is Null
  AND TbAdopcion.FAdopcion >= #1/1/2019#
```

**Acción al hacer clic en 2.5**: Exporta a Excel la misma consulta y la abre.

### 3.2 Grupo 2: Fallecidos sin RIAC

**Fuente de datos**: `TbFichaAnimal` (campos `FDefuncion`, `ComunicacionARIAC`)
**Procedimiento**: `ColocarContadoresFallecidosSinRIAC` → `ContadoresFallecidosSinRIAC()`

| # | Control | Caption dinámico | Lógica |
|---|---------|-----------------|--------|
| 1.3 | `lblFallecidosSinComunicacionRIAC` | "1.3. Fallecidos sin comunicar a RIAC ( N )" | `FDefuncion Is Not Null and ComunicacionARIAC <> 'Sí'` |

**SQL**:
```sql
SELECT TbFichaAnimal.NCHIP
FROM TbFichaAnimal
WHERE Not (TbFichaAnimal.FDefuncion Is Null)
  AND TbFichaAnimal.ComunicacionARIAC <> 'Sí'
```

**Acción al hacer clic**: Abre `FormFichaAnimalGestion` con filtro especial (`"Sí"` como argumento).

### 3.3 Grupo 3: Seguimiento de Adopciones

**Fuente de datos**: `TbAdopcion` (campos `FDevolucion`, `FechaImpresoEntregado`, `FechaImpresoAdjunto`) <!-- alantyle-ignore:ALAN007 -->
**Procedimiento**: `ColocarContadoresSeguimientos` → `ContadoresSeguimiento()` → `DameCodigoSeguimiento()`

| # | Control | Caption dinámico | Lógica |
|---|---------|-----------------|--------|
| 4.1 | `lblAdopcionesSeguimientoInformesPorEntregar` | "4.1 Impresos por entregar ( N )" | `FechaImpresoEntregado` es nulo |
| 4.2 | `lblAdopcionesSeguimientoInformesPorRecibir` | "4.2 Impresos entregados y no recibidos ( N )" | `FechaImpresoEntregado` tiene valor, `FechaImpresoAdjunto` es nulo |
| 4.3 | `lblAdopcionesSeguimientosTotales` | "4.3 Seguimientos totales ( N )" | Total de adopciones activas con seguimiento |

**Código de seguimiento** (`DameCodigoSeguimiento`):
- `"Sí|Sí"` → Impreso entregado y escaneado (completo)
- `"Sí|No"` → Impreso entregado, pendiente de escaneo
- `"No|No"` → Impreso pendiente de entregar
- `"-|-"` → Devolución registrada (sin seguimiento)

**Acciones al hacer clic**:
- **4.1**: Abre `FormAdopcionesGestion` con filtro `ComboEstadoSeguimiento = "No entregado"`
- **4.2**: Abre `FormAdopcionesGestion` con filtro `ComboEstadoSeguimiento = "Entregado y no escaneado"`
- **4.3**: Abre `FormAdopcionesGestion` con filtro `ComboAdopcionesActivas = "Sí"`

---

## 4. Interacción Hover

Cada control de navegación tiene un handler `MouseMove` que:
1. Cambia el color de la etiqueta a `ColorAlPasarPorEnEnlace`
2. Muestra `lblExplicacion` con texto descriptivo del módulo

Los contadores también tienen `MouseMove` que muestran su descripción en `lblExplicacion`.

---

## 5. Comportamiento de Visibilidad

Todos los contadores se ocultan (`Visible = False`) cuando su valor es 0. Solo se muestran cuando hay elementos pendientes, creando un dashboard de "lo que necesita atención".

---

## 6. Tablas Backend Involucradas

| Tabla | Campos clave | Uso en dashboard |
|-------|-------------|-----------------|
| `TbFichaAnimal` | `Situacion`, `NCHIP`, `FDefuncion`, `ComunicacionARIAC` | Contadores 2.1-2.4, 1.3 |
| `TbAdopcion` | `IDAdopcion`, `FDevolucion`, `FechaImpresoEntregado`, `FechaImpresoAdjunto`, `NChip` | Contadores 4.1-4.3, 2.5 |
| `TbEntradas` | `NChip`, `FEntradaProtectora`, `IDEntrada`, `IDAcogidaOrigen` | Contador 2.5 |
| `TbRIAC` | `IDRIAC`, `IDENTRADA`, `IDADOPCION` | Contador 2.5 (verificación de registro) |

---

## 7. Notas para APAP_WEB

### Prioridad alta
- Los 10 contadores son **el corazón del dashboard** — muestran qué necesita atención inmediata
- El patrón "ocultar si es 0, mostrar en rojo si > 0" es UX valioso para el nuevo diseño
- La numeración jerárquica (1.3, 2.1-2.5, 4.1-4.3) refleja la estructura organizativa

### Prioridad media
- El hover con `lblExplicacion` se puede traducir a tooltips o cards informativas
- Los clics en contadores abren formularios pre-filtrados → en web serían enlaces a vistas con filtros
- El control de usuario `adm` para mostrar/ocultar Ribbon se puede mapear a roles de UI

### Datos clave para replicar
```typescript
// Estructura de datos del dashboard
interface DashboardCounters {
  animalSituation: {
    incoherent: number;      // 2.1
    pendingEntry: number;    // 2.2
    pendingNewSituation: number; // 2.3
    pendingChip: number;     // 2.4
    pendingOwnershipTransfer: number; // 2.5
  };
  deceasedUnreported: number; // 1.3
  adoptionFollowUp: {
    pendingDelivery: number;  // 4.1
    deliveredNotReceived: number; // 4.2
    totalActive: number;      // 4.3
  };
}
```

## Contributor checklist

- [ ] Si consulta este doc para implementar la home de APAP_WEB, lea primero [d-02-home-dashboard.md](architecture/decisiones/d-02-home-dashboard.md) — la capacidad está migrada.
- [ ] No use este doc para defender un clon visual de la bandeja del Access: contradice [d-11-no-clonar-ux-legacy.md](architecture/decisiones/d-11-no-clonar-ux-legacy.md).
- [ ] Si descubre un campo o contador del legacy que no aparezca en el modelo nuevo, abra issue `type:bug gap:legacy` ([proceso.md](proceso.md) §0 P1).
- [ ] Si modifica las queries agregadas de la bandeja moderna, ejecute los tests del módulo afectado antes de cerrar.

## Navigation

Back: [to Codebase Guide](CODEBASE-GUIDE.md)
