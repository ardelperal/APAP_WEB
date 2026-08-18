---
title: "Legacy: Flujo de UI de Ficha Sanitaria"
status: "historical"
legacy_source: "src/forms/Form_FormFichasSanitarias*.cls + src/classes/FichaSanitaria.cls + src/classes/Animal.cls + Funciones Generales.bas (Access/VBA)"
superseded_by: ""
---

# Flujo de UI de Ficha Sanitaria — APAP_ACTUAL (Legacy Access/VBA)

**Fecha de análisis:** 2026-06-13  
**Proyecto fuente:** APAP_ACTUAL (Access/VBA)  
**Objetivo:** Documentar el flujo completo de la UI de salud para guiar la implementación en APAP_WEB

## What this doc is

| It is | Evidence in this repo |
|---|---|
| Catálogo del modelo de datos sanitario (5 tipos de eventos) y del flujo de navegación (FormFichasSanitariasGestion → AsuntoEleccion → Alta). | §3 tablas + §4 flujo. |
| Inventario de validaciones y restricciones por estado del animal. | §7 reglas + §9.2 restricciones. |

## What this doc is not

| It is not | Use this boundary |
|---|---|
| Una spec del módulo de salud de APAP_WEB. | El diseño vive en [discovery/feature-03-health-care.md](discovery/feature-03-health-care.md) y las specs en [openspec/specs/](openspec/specs/) (HEALTH-02..06, #51–#55). |
| Una guía para implementar la pestaña Salud del animal en la UI nueva. | La UI es responsabilidad del slice de salud en `app/modules/salud/` y del design system (D-12, pendiente). |

## Core invariants

- **Tipos de evento sanitario son cinco**: Analítica, Desparasitación, Vacuna, Esterilización, Otros (§3 tipo `TipoAnotacion`).
- **Tabla resumen se mantiene por evento**: `TbResumenActuacionesSanitarias` refleja el último valor por chip y tipo de prueba; debe actualizarse tras cada CRUD (§3 §"Tabla de Resumen").
- **Validación de fechas**: la fecha del evento es posterior al nacimiento y anterior a la defunción (§8.1).
- **No duplicados por chip + prueba + fecha**: `MismaPruebaYFechaParaNChip` bloquea el alta (§8.2).
- **Fallecido bloquea nuevos eventos**: animales con `FDefuncion` no admiten nuevas actuaciones sanitarias (§9.2).
- **Incoherente bloquea nuevos eventos**: estado requiere intervención manual antes de cualquier alta (§9.2).

---

## 1. Tabla de Contenidos

1. [Visión General](#1-visión-general)
2. [Modelo de Datos](#2-modelo-de-datos)
3. [Flujo de Navegación Principal](#3-flujo-de-navegación-principal)
4. [Tipos de Eventos Sanitarios](#4-tipos-de-eventos-sanitarios)
5. [Formularios y sus Funciones](#5-formularios-y-sus-funciones)
6. [Lógica de Negocio Central (FichaSanitaria.cls)](#6-lógica-de-negocio-central-fichasanitariacls)
7. [Reglas de Validación](#7-reglas-de-validación)
8. [Estado del Animal y Restricciones](#8-estado-del-animal-y-restricciones)
9. [Funcionalidad de Lote (Múltiple)](#9-funcionalidad-de-lote-múltiple)
10. [Informe de Próximas Pruebas](#10-informe-de-próximas-pruebas)
11. [Resumen para Implementación Web](#11-resumen-para-implementación-web)

---

## 2. Visión General

El sistema de Ficha Sanitaria de APAP_ACTUAL gestiona el historial médico completo de cada animal (perro/gato) del refugio. Permite:

- **Registrar** nuevos eventos sanitarios (vacunas, desparasitaciones, análisis clínicos, esterilizaciones, otros)
- **Consultar** el historial completo de cada animal
- **Editar** eventos existentes
- **Ver resumen** de los últimos valores por tipo de prueba
- **Generar informes** de próximas pruebas pendientes
- **Entrada por lote** para vacunaciones y desparasitaciones múltiples

### Flujo de Alto Nivel

```
┌─────────────────────────────────────────────────────────────────┐
│                     GESTIÓN FICHAS SANITARIAS                   │
│                    (FormFichasSanitariasGestion)                 │
│                                                                 │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ ComboChip   │───▶│ ListaFiltrados│───▶│ ComboAcciones    │   │
│  │ (Búsqueda)  │    │ (Resultados) │    │ (Acciones)       │   │
│  └─────────────┘    └──────────────┘    └──────────────────┘   │
│                                                    │            │
│                        ┌───────────────────────────┼────────┐   │
│                        ▼                           ▼        ▼   │
│                  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│                  │ Ver      │  │ Alta     │  │ Próximas │      │
│                  │ Detalle  │  │ Nuevo    │  │ Pruebas  │      │
│                  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Modelo de Datos

### Tabla Principal: `TbActuacionSanitaria`

Almacena todos los eventos sanitarios (una fila por evento).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `IDActuacionSanitaria` | Autonumérico | PK, identificador único del evento |
| `NCHIP` | Texto | FK → `TbFichaAnimal.NCHIP`, chip del animal |
| `FechaAnotacion` | Fecha | Fecha del evento sanitario |
| `TipoAnotacion` | Texto | Tipo: "Analítica", "Desparasitación", "Vacuna", "Esterilización", "Otros" |
| `Prueba` | Texto | Nombre de la prueba (ej: "Desparasitación Interna", "Tripanosoma") |
| `Resultado` | Texto | Resultado del evento (ej: "Positivo", "Negativo", "Correcto") |
| `Anotacion` | Texto | Nota adicional o texto libre |
| `Observaciones` | Texto | Observaciones extendidas |
| `Titulo` | Texto | Título o categoría del evento |
| `Producto` | Texto | Producto utilizado (vacuna, desparasitante) |
| `Lote` | Texto | Número de lote del producto |
| `CodVeterinario` | Texto | Código del veterinario responsable |
| `Clinica` | Texto | Nota clínica (esterilizaciones) |
| `IDAsunto` | Texto | FK → `TbAsunto`, referencia al tipo de asunto |
| `SituacionActual` | Texto | Situación del animal al momento del evento |

### Tabla de Resumen: `TbResumenActuacionesSanitarias`

Cache/mirror de los últimos valores por chip y tipo de prueba. Se actualiza cuando se crea/modifica un evento.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `NCHIP` | Texto | FK → `TbFichaAnimal.NCHIP` |
| `Prueba` | Texto | Nombre de la prueba |
| `FechaAnotacion` | Fecha | Fecha del último evento |
| `Resultado` | Texto | Último resultado |
| `Anotacion` | Texto | Última anotación |

### Tabla de Tipos de Asunto: `TbAsunto`

Catálogo de tipos de eventos sanitarios disponibles.

### Tabla de Nombres de Pruebas: `TbNombrePruebas`

Catálogo de pruebas disponibles, filtrado por especie.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `NombrePrueba` | Texto | Nombre de la prueba |
| `Observaciones` | Texto | Categoría: "analítica", "vacuna", etc. |
| `Especie` | Texto | Especie aplicable (vacío = todas) |

### Tabla de Ficha Animal: `TbFichaAnimal`

Datos del animal, incluyendo campos relevantes para salud:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `NCHIP` | Texto | PK, chip identificador |
| `NombreAnimal` | Texto | Nombre del animal |
| `Especie` | Texto | "Perro" o "Gato" |
| `Sexo` | Texto | "Macho" o "Hembra" |
| `FDefuncion` | Fecha | Fecha de defunción (si aplica) |
| `Situacion` | Texto | Situación anterior a fallecimiento |
| `UltimoEstadoAntesDeFallecido` | Texto | Último estado antes de morir |
| `NombreFoto` | Texto | Nombre del archivo de foto |

---

## 4. Flujo de Navegación Principal

### 4.1. Punto de Entrada: `FormFichasSanitariasGestion`

**Formulario principal de gestión.** Título: "Gestión de las fichas sanitarias"

**Controles principales:**
- `ComboChipBusqueda` — Búsqueda de animal por chip
- `ListaFiltrados` — Lista de resultados filtrados
- `ComboAcciones` — Menú de acciones disponibles
- `CmdBuscaAsuntos` — Botón de búsqueda

**Flujo:**
1. Usuario busca un animal por chip → `ComboChipBusqueda`
2. Se muestra el animal en `ListaFiltrados`
3. Usuario selecciona acción de `ComboAcciones`:
   - **Ver Resumen** → Abre `FormFichaSanitariaUltimosValores`
   - **Crear Nuevo Evento** → Abre `FormFichaSanitariaAsuntoEleccion`
   - **Próximas Pruebas** → Abre `FormProximosAsuntosSanitarios`

### 4.2. Selección de Tipo: `FormFichaSanitariaAsuntoEleccion`

**Formulario de selección del tipo de evento.** Muestra las opciones disponibles.

**Opciones:**
1. **Análisis** (Analítica) → Abre `FormFichasSanitariasAnaliticaAlta`
2. **Desparasitación** → Abre `FormFichasSanitariasDesparasitacionAlta`
3. **Vacuna** → Abre `FormFichasSanitariasVacunaAlta`
4. **Esterilización** → Abre `FormFichasSanitariasEsterilizacionAlta`
5. **Otros** → Abre `FormFichasSanitariasOtrosAlta`
6. **Múltiple** (Vacuna/Desparasitación por lote) → Abre formularios de entrada múltiple

### 4.3. Resumen de Valores: `FormFichaSanitariaUltimosValores`

**Vista resumen de los últimos valores por chip.** Título: "Ficha Sanitaria (últimos resultados)"

Muestra una tabla con los chips seleccionados y sus últimas pruebas/valores. Permite:
- Ver los últimos resultados de cada tipo de prueba
- Navegar al detalle de un evento específico
- Imprimir el resumen

---

## 5. Tipos de Eventos Sanitarios

### 5.1. Analítica (Análisis Clínico)

**Campos específicos:**
- `FANotacion` — Fecha de la anotación
- `ComboAnalítica` — Tipo de análisis (ej: "Tripanosoma", "Leishmaniosis")
- `Resultado` — Resultado del análisis (ej: "Positivo", "Negativo")
- `ComboTitulo` — Título/categoría
- `Observaciones` — Notas adicionales

**Llamada a negocio:** `FichaSanitaria.AltaAnaliticaComun(strNChip, strFAnotacion, strAnalitica, strResultado, strTitulo, strObservaciones, strVieneDeAltaMultiple)`

**Tablas relacionadas:**
- `TbNombrePruebas` (filtrado por `Observaciones='analítica'` y especie)

### 5.2. Vacuna

**Campos específicos:**
- `FANotacion` — Fecha de la vacunación
- `ComboVacuna` — Tipo de vacuna (ej: "Polivalente", "Rabia")
- `Producto` — Nombre del producto/comercial
- `Lote` — Número de lote
- `CodVeterinario` — Código del veterinario
- `Observaciones` — Notas

**Llamada a negocio:** `FichaSanitaria.AltaVacuna(strNChip, strFAnotacion, strVacuna, strProducto, strLote, strCodVeterinario, strObservaciones, strVieneDeAltaMultiple)`

**Tablas relacionadas:**
- `TbNombrePruebas` (filtrado por `Observaciones='vacuna'` y especie)

### 5.3. Desparasitación

**Campos específicos:**
- `FANotacion` — Fecha
- `ComboTipo` — Tipo: "Interna" o "Externa"
- `Producto` — Producto utilizado
- `Observaciones` — Notas

**Llamada a negocio:** `FichaSanitaria.AltaDesparasitacion(strNChip, strFAnotacion, strProducto, strTipo, strObservaciones, strVieneDeAltaMultiple)`

**Tablas relacionadas:**
- `TbNombrePruebas` (filtrado por nombre que contiene "Interna" o "Externa")

**Nota:** Las desparasitaciones se buscan como "Desparasitación Interna" y "Desparasitación Externa" en `TbActuacionSanitaria`.

### 5.4. Esterilización

**Campos específicos:**
- `FANotacion` — Fecha
- `ComboClinica` — Nota clínica del procedimiento
- `Observaciones` — Notas

**Llamada a negocio:** `FichaSanitaria.AltaEsterilizacion(strNChip, strFAnotacion, strClinica, strObservaciones, strVieneDeAltaMultiple)`

### 5.5. Otros

**Campos específicos:**
- `FANotacion` — Fecha
- `Anotacion` — Texto libre de la anotación

**Llamada a negocio:** `FichaSanitaria.AltaOtrasAnotaciones(strNChip, strFAnotacion, strAnotacion, , strVieneDeAltaMultiple)`

---

## 6. Formularios y sus Funciones

### 6.1. Formularios de Alta (Crear)

| Formulario | Tipo | Llamada a Negocio | Campos Clave |
|-----------|------|-------------------|--------------|
| `FormFichasSanitariasAnaliticaAlta` | Analítica | `AltaAnaliticaComun` | Fecha, Analítica, Resultado, Título, Observaciones |
| `FormFichasSanitariasVacunaAlta` | Vacuna | `AltaVacuna` | Fecha, Vacuna, Producto, Lote, CodVeterinario, Observaciones |
| `FormFichasSanitariasDesparasitacionAlta` | Desparasitación | `AltaDesparasitacion` | Fecha, Producto, Tipo (Interna/Externa), Observaciones |
| `FormFichasSanitariasEsterilizacionAlta` | Esterilización | `AltaEsterilizacion` | Fecha, Clinica, Observaciones |
| `FormFichasSanitariasOtrosAlta` | Otros | `AltaOtrasAnotaciones` | Fecha, Anotacion |

### 6.2. Formularios de Edición (Modificar)

| Formulario | Tipo | Llamada a Negocio | Campos Clave |
|-----------|------|-------------------|--------------|
| `FormFichasSanitariasAnaliticaEdicion` | Analítica | `ModificarAnalitica` | ID, Fecha, Analítica, Resultado, Título, Observaciones |
| `FormFichasSanitariasVacunaEdicion` | Vacuna | `ModificarVacuna` | ID, Fecha, Vacuna, Producto, Lote, CodVeterinario, Observaciones |
| `FormFichasSanitariasDesparasitacionEdicion` | Desparasitación | `ModificarDesparasitacion` | ID, Fecha, Producto, Tipo, Observaciones |
| `FormFichasSanitariasEsterilizacionEdicion` | Esterilización | `ModificarEsterilizacion` | ID, Fecha, Clinica, Observaciones |
| `FormFichasSanitariasOtrosEdicion` | Otros | `ModificarOtros` | ID, Fecha, Anotacion |

### 6.3. Formularios de Lote (Múltiple)

| Formulario | Tipo | Descripción |
|-----------|------|-------------|
| `FormFichasSanitariasAsuntoAltaMultiple` | Múltiple | Entrada de múltiples eventos del mismo tipo |
| `FormFichasSanitariasDesparasitacionMultiple` | Desparasitación | Entrada de desparasitaciones para múltiples animales |
| `FormFichasSanitariasAsuntoEdicionMultiple` | Múltiple | Edición de eventos múltiples |

### 6.4. Otros Formularios

| Formulario | Función |
|-----------|---------|
| `FormFichasSanitariasDetalleGestion` | Vista detalle de un evento seleccionado |
| `FormProximosAsuntosSanitarios` | Informe de próximas pruebas pendientes |
| `FormFichaSanitariaUltimosValores` | Resumen de últimos valores por chip |

---

## 7. Lógica de Negocio Central (`FichaSanitaria.cls`)

Clase central con toda la lógica CRUD para eventos sanitarios.

### 7.1. Métodos de Consulta

| Método | Descripción | Retorna |
|--------|-------------|---------|
| `DameUltimoResultadoDeLaPrueba(NChip, Prueba)` | Obtiene el último resultado de una prueba específica | `FechaAnotacion#Resultado#Anotacion` |
| `DameUltimoResultadoDeDesparasitacion(NChip)` | Obtiene la última desparasitación (interna o externa, whichever is newer) | `FechaAnotacion#Resultado#Anotacion` |

### 7.2. Métodos de Alta (Crear)

Todos retornan: `"strEstado|strTextoOk|strTextoError"`
- `strEstado="1"` → Éxito, `strTextoOk` contiene el `IDActuacionSanitaria` creado
- `strEstado="-1"` → Error, `strTextoError` contiene el mensaje

| Método | Parámetros Principales |
|--------|----------------------|
| `AltaAnaliticaComun` | NChip, FechaAnotacion, Analitica, Resultado, Titulo, Observaciones, VieneDeAltaMultiple |
| `AltaVacuna` | NChip, FechaAnotacion, Vacuna, Producto, Lote, CodVeterinario, Observaciones, VieneDeAltaMultiple |
| `AltaDesparasitacion` | NChip, FechaAnotacion, Producto, Tipo, Observaciones, VieneDeAltaMultiple |
| `AltaEsterilizacion` | NChip, FechaAnotacion, Clinica, Observaciones, VieneDeAltaMultiple |
| `AltaOtrasAnotaciones` | NChip, FechaAnotacion, Anotacion, , VieneDeAltaMultiple |

### 7.3. Métodos de Modificación (Editar)

| Método | Parámetros Principales |
|--------|----------------------|
| `ModificarAnalitica` | IDActuacionSanitaria, FechaAnotacion, Analitica, Resultado, Titulo, Observaciones |
| `ModificarVacuna` | IDActuacionSanitaria, FechaAnotacion, Vacuna, Producto, Lote, CodVeterinario, Observaciones |
| `ModificarDesparasitacion` | IDActuacionSanitaria, FechaAnotacion, Producto, Tipo, Observaciones |
| `ModificarEsterilizacion` | IDActuacionSanitaria, FechaAnotacion, Clinica, Observaciones |
| `ModificarOtros` | IDActuacionSanitaria, FechaAnotacion, Anotacion |

### 7.4. Métodos de Borrar

| Método | Descripción |
|--------|-------------|
| `Borrar` | Elimina un evento sanitario por IDActuacionSanitaria |

---

## 8. Reglas de Validación

### 8.1. Validación de Fechas (`FechasBienParaPrueba`)

**Reglas:**
1. La fecha del evento debe ser **posterior a la fecha de nacimiento** del animal
2. La fecha del evento debe ser **anterior a la fecha de defunción** (si el animal ha fallecido)
3. La fecha no puede ser futura

### 8.2. Duplicados (`MismaPruebaYFechaParaNChip`)

**Regla:** No se permite registrar dos eventos del mismo tipo (`Prueba`) con la misma fecha para el mismo chip.

### 8.3. Validación de Animal

- El chip debe existir en `TbFichaAnimal`
- El animal no debe estar en situación "Baja" (fallecido)
- Se verifica la situación actual antes de permitir el alta

### 8.4. Formulario con Clave (`FormularioClave`)

Algunos formularios requieren una clave de seguridad para acceder (protección contra uso no autorizado).

---

## 9. Estado del Animal y Restricciones

### 9.1. Función `DameSituacion`

Determina la situación actual del animal. Situaciones posibles:

| Situación | Descripción | Restricción en Salud |
|-----------|-------------|---------------------|
| **Pendiente de entrada** | No ha tenido entradas | No debería registrar salud |
| **Albergue** | En el refugio | ✅ Permitido |
| **Acogida** | En acogida temporal | ✅ Permitido |
| **Adoptado** | Adoptado | ✅ Permitido (pero con nota) |
| **Entregado** | Entregado a propietario | ⚠️ Restringido |
| **Fallecido** | Ha muerto | ❌ No permitido |
| **Pendiente de Nueva Situación** | Entrada sin resolver | ⚠️ Verificar |
| **Incoherente** | Estado inconsistente | ❌ Revisar |

### 9.2. Restricciones por Situación

- **Fallecido:** No se permiten nuevas actuaciones sanitarias
- **Pendiente de entrada:** Se muestra advertencia
- **Incoherente:** Se muestra error y se bloquea la operación

---

## 10. Funcionalidad de Lote (Múltiple)

### 10.1. Entrada Múltiple de Vacunas

**Formulario:** `FormFichasSanitariasVacunaAlta` (con `strVieneDeAltaMultiple`)

Permite registrar la misma vacuna para múltiples animales en una sola operación.

### 10.2. Entrada Múltiple de Desparasitaciones

**Formulario:** `FormFichasSanitariasDesparasitacionMultiple`

Permite registrar desparasitaciones para múltiples animales seleccionados.

### 10.3. Flujo de Lote

1. Seleccionar tipo de evento
2. Se abre formulario de entrada múltiple
3. Se seleccionan los animales (chips)
4. Se completa la información común (fecha, producto, etc.)
5. Se crea un evento por cada animal seleccionado
6. Se muestra resumen de éxitos/errores

---

## 11. Informe de Próximas Pruebas

**Formulario:** `FormProximosAsuntosSanitarios`

**Generación:** `Resumen.ExcelGenerarInformeProximasPruebas()`

**Funcionalidad:**
- Genera un informe Excel con las pruebas próximas a vencer
- Permite filtrar por rango de fechas
- Muestra: chip, nombre, tipo de prueba, fecha última, fecha próxima, estado

**Uso típico:** Planificación de vacunaciones y desparasitaciones periódicas.

---

## 12. Resumen para Implementación Web

### 12.1. Componentes Necesarios en APAP_WEB

| Componente Legacy | Equivalente Web Propuesto |
|------------------|--------------------------|
| `FormFichasSanitariasGestion` | `HealthDashboard` — Panel principal con búsqueda y listado |
| `FormFichaSanitariaAsuntoEleccion` | `HealthEventTypeSelector` — Selector de tipo de evento |
| `FormFichasSanitariasAnaliticaAlta` | `LabTestForm` — Formulario de análisis clínico |
| `FormFichasSanitariasVacunaAlta` | `VaccinationForm` — Formulario de vacunación |
| `FormFichasSanitariasDesparasitacionAlta` | `DewormingForm` — Formulario de desparasitación |
| `FormFichasSanitariasEsterilizacionAlta` | `SterilizationForm` — Formulario de esterilización |
| `FormFichasSanitariasOtrosAlta` | `OtherEventForm` — Formulario de otros eventos |
| `FormFichaSanitariaUltimosValores` | `HealthSummaryView` — Vista resumen de últimos valores |
| `FormFichasSanitariasDetalleGestion` | `HealthEventDetail` — Vista detalle de un evento |
| `FormProximosAsuntosSanitarios` | `UpcomingHealthReport` — Informe de próximas pruebas |
| `FichaSanitaria.cls` | `health.service.ts` — Servicio de lógica de negocio |

### 12.2. Campos Comunes a Todos los Formularios

```typescript
interface HealthEventBase {
  id: string;                    // IDActuacionSanitaria
  chip: string;                  // NCHIP
  eventDate: Date;               // FechaAnotacion
  eventType: HealthEventType;    // TipoAnotacion
  observations?: string;         // Observaciones
  currentSituation?: string;     // SituacionActual
}
```

### 12.3. Tipos de Eventos (Enum)

```typescript
enum HealthEventType {
  LAB_TEST = 'Analítica',
  DEWORMING = 'Desparasitación',
  VACCINE = 'Vacuna',
  STERILIZATION = 'Esterilización',
  OTHER = 'Otros'
}
```

### 12.4. Interfaces por Tipo

```typescript
// Analítica
interface LabTestEvent extends HealthEventBase {
  testType: string;        // ComboAnalítica (Prueba)
  result: string;          // Resultado
  title?: string;          // Titulo
}

// Vacuna
interface VaccinationEvent extends HealthEventBase {
  vaccineType: string;     // ComboVacuna (Prueba)
  product: string;         // Producto
  lot?: string;            // Lote
  vetCode?: string;        // CodVeterinario
}

// Desparasitación
interface DewormingEvent extends HealthEventBase {
  dewormingType: 'Interna' | 'Externa';  // Tipo
  product: string;         // Producto
}

// Esterilización
interface SterilizationEvent extends HealthEventBase {
  clinicalNote: string;    // Clinica
}

// Otros
interface OtherHealthEvent extends HealthEventBase {
  annotation: string;      // Anotacion
}
```

### 12.5. Flujo de UI Propuesto

```
┌─────────────────────────────────────────────────────────────────┐
│                    HEALTH DASHBOARD                              │
│                                                                 │
│  🔍 [Buscar por chip...]  [Ver Resumen] [Próximas Pruebas]    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Lista de Animales                                        │   │
│  │ ┌──────┬────────┬───────────┬────────────┐              │   │
│  │ │ Chip │ Nombre │ Últ. Vacuna│ Situación  │              │   │
│  │ ├──────┼────────┼───────────┼────────────┤              │   │
│  │ │ 1234 │ Max    │ 2024-01-15│ Albergue   │              │   │
│  │ │ 5678 │ Luna   │ 2024-02-20│ Acogida    │              │   │
│  │ └──────┴────────┴───────────┴────────────┘              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [Seleccionar Animal] → [Ver Historial] / [Nuevo Evento]       │
└─────────────────────────────────────────────────────────────────┘
```

### 12.6. Consideraciones Importantes

1. **Validación de duplicados:** Implementar verificación de fecha+tipo+chip antes de crear
2. **Restricciones por estado:** Bloquear creación de eventos para animales fallecidos
3. **Entrada múltiple:** Considerar implementar como funcionalidad futura (no MVP)
4. **Sincronización de resumen:** Actualizar `TbResumenActuacionesSanitarias` después de cada CRUD
5. **Fecha de nacimiento:** Validar que la fecha del evento sea posterior al nacimiento
6. **Historial completo:** Mantener todas las versiones de un evento (no sobrescribir)

---

## 13. Archivos Analizados

### Formularios (VBA Code-Behind)
- `src/forms/Form_FormFichasSanitariasGestion.cls` — Panel principal de gestión
- `src/forms/Form_FormFichaSanitariaAsuntoEleccion.cls` — Selección de tipo
- `src/forms/Form_FormFichasSanitariasAnaliticaAlta.cls` — Alta de análisis
- `src/forms/Form_FormFichasSanitariasAnaliticaEdicion.cls` — Edición de análisis
- `src/forms/Form_FormFichasSanitariasVacunaAlta.cls` — Alta de vacuna
- `src/forms/Form_FormFichasSanitariasVacunaEdicion.cls` — Edición de vacuna
- `src/forms/Form_FormFichasSanitariasDesparasitacionAlta.cls` — Alta de desparasitación
- `src/forms/Form_FormFichasSanitariasDesparasitacionEdicion.cls` — Edición de desparasitación
- `src/forms/Form_FormFichasSanitariasEsterilizacionAlta.cls` — Alta de esterilización
- `src/forms/Form_FormFichasSanitariasEsterilizacionEdicion.cls` — Edición de esterilización
- `src/forms/Form_FormFichasSanitariasOtrosAlta.cls` — Alta de otros
- `src/forms/Form_FormFichasSanitariasOtrosEdicion.cls` — Edición de otros
- `src/forms/Form_FormFichasSanitariasDetalleGestion.cls` — Vista detalle
- `src/forms/Form_FormFichaSanitariaUltimosValores.cls` — Resumen de valores
- `src/forms/Form_FormProximosAsuntosSanitarios.cls` — Próximas pruebas

### Clases (Lógica de Negocio)
- `src/classes/FichaSanitaria.cls` — Clase central de salud (~2500 líneas)
- `src/classes/Animal.cls` — Gestión de animales (fotos, chips, ficha)

### Módulos
- `src/modules/Funciones Generales.bas` — Funciones auxiliares (`DameSituacion`, etc.)

---

## 14. Siguiente Paso

Este documento sirve como fuente de verdad para la implementación del módulo de salud en APAP_WEB. El siguiente paso es:

1. **Crear el esquema de base de datos** en InsForge/PostgreSQL basado en las tablas documentadas
2. **Implementar el servicio de salud** (`health.service.ts`) con las operaciones CRUD
3. **Crear los componentes UI** siguiendo el flujo de navegación documentado
4. **Implementar validaciones** según las reglas documentadas
5. **Crear el dashboard** con búsqueda, listado y resumen

---

*Documento generado por IA basado en análisis del código fuente de APAP_ACTUAL.*

## Contributor checklist

- [ ] Antes de implementar HEALTH-02..06 (#51–#55), confirme con §3 los cinco tipos de evento y los campos clave de `TbActuacionSanitaria`.
- [ ] Si implementa el alta de un evento, cubra los cinco invariantes de §7–§8 con tests de regresión (`FechasBienParaPrueba`, `MismaPruebaYFechaParaNChip`, estado del animal).
- [ ] Si añade un nuevo tipo de evento, actualice el catálogo de `TbNombrePruebas` y el filtro por especie; no reutilice tipos existentes para fines distintos.
- [ ] Si descubre una validación del legacy no listada en §7–§8, abra issue `type:bug gap:legacy` (P1, [proceso.md](proceso.md) §0).
- [ ] Si implementa el informe de próximas pruebas (§10), preserve el formato chip + tipo de prueba + fecha última + fecha próxima.

## Navigation

Back: [to Codebase Guide](CODEBASE-GUIDE.md)
