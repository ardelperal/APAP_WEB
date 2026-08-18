---
name: legacy-volunteer-roles
description: Modelo histórico de voluntarios y roles en Access/VBA.
license: Proprietary
metadata:
  author: APAP_WEB maintainers
  version: 1.0.0
title: "Legacy: Modelo de voluntarios"
status: "historical"
legacy_source: "TbVoluntariosParaAutorrellenables + Funciones Generales.bas (RegistrarVoluntarios, RellenaDatosPersonales) + Form_FormEntradaAlta.cls, Form_FormAdopcionAlta.cls, Form_FormAcogidaAlta.cls, Form_FormTerapiasAlta.cls (Access/VBA)"
superseded_by: ""
---

# Modelo de Voluntarios en el Sistema Legacy APAP

## What this doc is

| It is | Evidence in this repo |
|---|---|
| Análisis del modelo plano legacy `TbVoluntariosParaAutorrellenables` (sin roles, sin ID numérico, auto-registro). | §1 tabla de campos + §6 tabla de evidencias. |
| Inventario de los campos contextuales por dominio (Entradas, Adopción, Acogida, Terapias). | §2.1–§2.4 (uno por tabla). |

## What this doc is not

| It is not | Use this boundary |
|---|---|
| Una spec del modelo de voluntarios de APAP_WEB. | El modelo many-to-many con catálogo de roles propuesto en §7.3 es una recomendación; las specs viven en [openspec/specs/](openspec/specs/) (VOL-01..05, #35–#38). |
| Una guía para modelar la entidad separada `TbAcogidaCasas`. | La separación entre voluntario y casa de acogida está documentada en §3 pero no se replica como tal. |

## Core invariants

- **Casa de acogida no es voluntario**: `TbAcogidaCasas` es una entidad separada con dirección y DNI; un acogedor no es necesariamente un voluntario del sistema (§3 tabla).
- **Auto-registro por nombre**: la tabla `TbVoluntariosParaAutorrellenables` se puebla automáticamente cuando se usa un nombre en cualquier formulario de negocio (§1 §"Características clave").
- **Sin distinción de roles en origen**: el legacy no permite asignar solo voluntarios de salud a tareas sanitarias; cualquier persona puede aparecer en cualquier rol (§7.1).

## Resumen ejecutivo

El sistema legacy Access/VBA **no tiene modelo de roles de voluntarios**. Existe una única tabla plana de lookup (`TbVoluntariosParaAutorrellenables`) con campos nombre, teléfono y email. Los "roles" de voluntario son simplemente **nombres de campo contextuales** en distintas tablas de negocio (entradas, adopciones, acogidas, terapias). Cualquier persona de la lista puede aparecer en cualquier rol sin restricción alguna.

**La hipótesis del usuario se confirma con evidencia: cada voluntario puede tener todos los roles.**

---

## 1. Tabla de Voluntarios: `TbVoluntariosParaAutorrellenables`

Esta es la ÚNICA tabla de registro de voluntarios en todo el sistema.

| Campo | Tipo | Propósito |
|-------|------|-----------|
| `Voluntario` | Texto (clave de búsqueda) | Nombre completo del voluntario |
| `Tel1` | Texto | Teléfono principal |
| `Tel2` | Texto | Teléfono secundario |
| `Email` | Texto | Dirección de email |

### Características clave

- **Sin ID numérico**: los voluntarios se identifican únicamente por nombre libre.
- **Sin campo de rol/tipo**: no hay distinción entre tipos de voluntario.
- **Sin campo de estado activo/inactivo**: no hay baja lógica.
- **Auto-registro**: la tabla se puebla automáticamente cuando se usa un nombre en cualquier formulario de negocio.

### Código fuente de referencia

- **Tabla**: `Funciones Generales.bas` líneas 3084-3134 (`RegistrarVoluntarios`)
- **Búsqueda**: `Funciones Generales.bas` líneas 3007-3083 (`RellenaDatosPersonales`)

```vb
' Patron de auto-registro (RegistrarVoluntarios)
' Solo upserta por nombre. Sin roles, sin tipos.
Public Function RegistrarVoluntarios(strNombre As String, ...)
    strSQL = "SELECT TbVoluntariosParaAutorrellenables.* " & _
             "FROM TbVoluntariosParaAutorrellenables " & _
             "WHERE Voluntario='" & strNombre & "';"
    ' Si no existe → AddNew con nombre, tel, email
    ' Si existe → Edit solo si los datos nuevos no están vacíos
End Function
```

---

## 2. Campos de Voluntario por Contexto de Negocio

Los "roles" del voluntario se manifiestan como nombres de campo en distintas tablas. **No hay tabla de roles ni catálogo de capacidades.**

### 2.1 Entrada (TbEntradas)

| Campo | Rol implícito | Obligatorio |
|-------|---------------|-------------|
| `VoluntarioEntrada` | Voluntario que recibe/tramita la entrada del animal | Sí |

- **Formulario**: `Form_FormEntradaAlta.cls`, `Form_FormEntradaEdicion.cls`
- **Clase**: `Entrada.cls` línea 1030
- **Comportamiento**: El combo `ComboVoluntarioEntrada` usa la misma lista plana de `TbVoluntariosParaAutorrellenables`.

### 2.2 Adopción (TbAdopcion)

| Campo | Rol implícito | Obligatorio |
|-------|---------------|-------------|
| `VoluntarioSeguimiento` | Voluntario asignado al seguimiento post-adopción | Sí |
| `ResponsableAdopcion` | Responsable/gestor de la adopción | Sí |
| `TelMovilVoluntarioSeguimiento` | Móvil del voluntario de seguimiento | Sí |
| `emailVoluntarioSeguimiento` | Email del voluntario de seguimiento | Sí |

- **Formulario**: `Form_FormAdopcionAlta.cls`, `Form_FormAdopcionEdicion.cls`
- **Clase**: `Adopcion.cls` líneas 109-112, 557-560
- **Comportamiento**: `ComboVoluntario` usa la misma lista plana. `ResponsableAdopcion` es otro campo de texto libre (no referenciable a la tabla de voluntarios).

### 2.3 Acogida Animal (TbAcogidaAnimal)

Este es el contexto más rico en campos de voluntario:

| Campo | Rol implícito | Obligatorio |
|-------|---------------|-------------|
| `VoluntarioSeguimiento1` | Voluntario principal de seguimiento de la acogida | Sí |
| `VoluntarioSeguimiento1Tel` | Móvil del voluntario de seguimiento 1 | Sí |
| `VoluntarioSeguimiento2` | Voluntario secundario de seguimiento | No |
| `VoluntarioSeguimiento2Tel` | Móvil del voluntario de seguimiento 2 | No |
| `VoluntarioCosasSanitarias` | Voluntario responsable de asuntos sanitarios | Sí |
| `VoluntarioCosasSanitariasTel` | Móvil del voluntario sanitario | Sí |
| `VoluntarioCosasSanitariasEmail` | Email del voluntario sanitario | Sí |
| `VoluntarioSeguimientoEmail` | Email del voluntario de seguimiento | No |
| `VoluntarioAcogida` | Voluntario vinculado a la acogida (¿acogedor?) | No |

- **Formulario**: `Form_FormAcogidaAlta.cls`, `Form_FormAcogidaEdicion.cls`
- **Clase**: `Acogida.cls` líneas 654-670, 824-842, 1790-1831
- **Validación**: Los campos obligatorios se validan en `Acogida.Alta` líneas 706-725.
- **Auto-fill**: Al seleccionar un nombre, `RellenaDatosPersonales` rellena automáticamente tel1 y email desde la tabla de lookup.

### 2.4 Terapias (TbTerapias)

| Campo | Rol implícito | Obligatorio |
|-------|---------------|-------------|
| `Voluntario` | Voluntario que realiza la terapia | Sí |

- **Formulario**: `Form_FormTerapiasAlta.cls`, `Form_FormTerapiasEdicion.cls`
- **Clase**: `Terapia.cls` líneas 364-367, 418
- **Comportamiento**: El combo usa la misma lista plana. La misma persona puede registrar terapias para múltiples animales.

---

## 3. Casa de Acogida vs Voluntario: Entidades Separadas

**TbAcogidaCasas** es una entidad distinta de los voluntarios:

| Campo | Propósito |
|-------|-----------|
| `Nombre`, `Apellidos` | Identificación del acogedor |
| `DNIAcogedor` | DNI del acogedor |
| `Calle`, `Numero`, `Piso`, `Letra`, `CP`, `Localidad`, `Provincia` | Dirección completa |
| `Telefono`, `email` | Contacto |
| `Coche` | Disponibilidad de coche (Sí/No) |
| `EspeciePreferente` | Especie preferente (Canina/Felina) |
| `Vinculacion` | Vinculación con la protectora |
| `FechaBaja` | Fecha de baja (activo/inactivo) |
| `Caracteristicas` | Características del tipo de acogida |

**Diferencia clave**: La casa de acogida es un **hogar** con dirección física, DNI y capacidad. Los voluntarios son **personas** que realizan tareas operativas. Un acogedor no es necesariamente un voluntario del sistema.

---

## 4. Flujo de Datos: Cómo se Relacionan

```
TbVoluntariosParaAutorrellenables (lookup plana, sin roles)
    │
    ├──→ TbEntradas.VoluntarioEntrada
    │
    ├──→ TbAdopcion.VoluntarioSeguimiento
    ├──→ TbAdopcion.ResponsableAdopcion (texto libre, no referenciable)
    │
    ├──→ TbAcogidaAnimal.VoluntarioSeguimiento1
    ├──→ TbAcogidaAnimal.VoluntarioSeguimiento2
    ├──→ TbAcogidaAnimal.VoluntarioCosasSanitarias
    ├──→ TbAcogidaAnimal.VoluntarioAcogida
    │
    └──→ TbTerapias.Voluntario

TbAcogidaCasas (entidad separada: hogar de acogida)
    │
    └──→ TbAcogidaAnimal.IDAcogidaCasa (FK)
```

---

## 5. Patrón de Auto-fill (RellenaDatosPersonales)

El sistema tiene un mecanismo de auto-rellenado que funciona así:

1. El usuario selecciona un nombre en un combo de voluntario
2. Se ejecuta `RellenaDatosPersonales(nombre, tel1, tel2, email)` con flags "Sí"/"No"
3. La función busca el nombre en `TbVoluntariosParaAutorrellenables`
4. Devuelve los datos solicitados como cadena separada por `|`
5. El formulario rellena automáticamente los campos de teléfono/email

**Importante**: Este mecanismo no distingue roles. Si "María" aparece como voluntario de entrada, el sistema rellenará su teléfono para ese campo. Si luego aparece en una terapia, se rellenará el mismo teléfono. No hay verificación de capacidades.

---

## 6. Evidencia de que No hay Restricciones de Rol

| Evidencia | Fuente |
|-----------|--------|
| La tabla `TbVoluntariosParaAutorrellenables` no tiene campo de tipo/rol | `Funciones Generales.bas` líneas 3084-3134 |
| Todos los combos de voluntario usan la misma lista plana | `Form_FormEntradaAlta`, `Form_FormAdopcionAlta`, `Form_FormAcogidaAlta`, `Form_FormTerapiasAlta` |
| `RegistrarVoluntarios` solo upserta nombre, teléfono y email | `Funciones Generales.bas` línea 3097 |
| No hay `WHERE` o filtro por tipo de voluntario en ninguna query | Todos los formularios relevantes | <!-- alantyle-ignore:ALAN003 -->
| La función `RellenaDatosPersonales` no verifica capacidades | `Funciones Generales.bas` líneas 3007-3083 |
| `ResponsableAdopcion` es texto libre, no referenciable a la tabla de voluntarios | `Adopcion.cls` línea 558 |

---

## 7. Implicaciones para APAP_WEB

### 7.1 Lo que el modelo actual permite

- Cualquier persona puede ser voluntario de entrada, seguimiento, sanitario, terapia o acogida
- No hay control de acceso por rol
- No hay trazabilidad de qué roles ha desempeñado una persona
- No hay estadísticas por tipo de voluntario

### 7.2 Lo que el modelo actual no permite

- Asignar solo voluntarios de salud a tareas sanitarias
- Filtrar voluntarios de terapia por capacidades
- Saber qué roles tiene activos un voluntario
- Dar de baja un voluntario sin borrar sus registros históricos
- Auditar quién hizo qué en cada etapa del ciclo de vida

### 7.3 Recomendación para APAP_WEB

**Modelo recomendado: Voluntario con roles/capabilidades (many-to-many)**

```
Voluntario (entidad central)
  ├── id, nombre, email, teléfono, DNI, activo
  │
  └──→ VoluntarioRol (tabla pivote)
        ├── voluntario_id (FK)
        ├── rol_id (FK → Catálogo de Roles)
        ├── fecha_inicio, fecha_fin (opcional)
        └── activo
```

**Catálogo de Roles sugerido** (basado en los campos contextuales del legacy):

| Rol | Campo legacy equivalente | Descripción |
|-----|-------------------------|-------------|
| `entrada` | `VoluntarioEntrada` | Recepción de animales |
| `SEGUIMIENTO` | `VoluntarioSeguimiento1/2` | Seguimiento post-adopción/acogida |
| `SALUD` | `VoluntarioCosasSanitarias` | Gestión de asuntos sanitarios |
| `TERAPIA` | `Voluntario` (en TbTerapias) | Realización de terapias |
| `ACOGIDA` | `VoluntarioAcogida` | Gestión de casas de acogida |
| `RESPONSABLE` | `ResponsableAdopcion` | Gestión/gestoría de adopciones |

**Ventajas sobre el modelo legacy**:
- Control de acceso por rol
- Trazabilidad de roles por persona
- Filtros de voluntarios por contexto
- Estadísticas de participación por rol
- Compatibilidad total con los datos existentes (cada campo contextual se mapea a un rol)

## Contributor checklist

- [ ] Antes de implementar VOL-01..05 (#35–#38), confirme con este doc los campos contextuales por dominio (§2.1–§2.4).
- [ ] Si diseña el modelo de voluntarios en APAP_WEB, decida si replica la tabla plana o evoluciona al many-to-many propuesto en §7.3 y documente la decisión en un ADR.
- [ ] Si descubre un campo de voluntario no listado en §2 (Entradas/Adopción/Acogida/Terapias), abra issue `type:bug gap:legacy` (P1, [proceso.md](proceso.md) §0).
- [ ] Si separa `voluntarios` de `casas_de_acogida`, preserve el invariante de §3 (entidades distintas).

## Navigation

Back: [to Codebase Guide](CODEBASE-GUIDE.md)
