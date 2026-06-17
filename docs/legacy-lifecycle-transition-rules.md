# Reglas de Transición del Ciclo de Vida — Legado Access/VBA

> **Fuente**: Análisis del código fuente del sistema legado `APAP_ACTUAL` (Access/VBA)
> **Fecha del análisis**: 2026-06-08
> **Archivos principales**: `Funciones Generales.bas`, `Animal.cls`, `Entrada.cls`, `Acogida.cls`, `Adopcion.cls`, `Form_FormFichaAnimalEleccionFinSituacion.cls`, `Form_FormFichaAnimalFallecimiento.cls`

---

## 1. Estados posibles del animal

El sistema define **8 estados** para un animal, determinados por la función `DameSituacion()`:

| Estado | Descripción | Condición de cálculo |
|---|---|---|
| **Pendiente de entrada** | Ficha creada, sin ninguna entrada registrada | Sin entradas en `TbEntradas`, sin acogidas activas, sin adopciones activas, sin fecha de defunción |
| **Pendiente de Nueva Situación** | Tuvo al menos una entrada, pero todas cerradas sin devolución a propietario | Entradas existentes pero todas con `FSalida` rellenado; sin acogida/adopción activas; sin defunción; la última entrada **no** tiene `FEntregaAPropietario` |
| **Entregado** | Devuelto al propietario original | Mismo que "Pendiente de Nueva Situación" pero la **última** entrada **sí** tiene `FEntregaAPropietario` rellenado |
| **Albergue** | En el refugio (protectora) | Exactamente 1 entrada activa (`FSalida` Is Null), sin acogida/adopción activas, sin defunción |
| **Acogida** | En acogida temporal/condicionada | Exactamente 1 acogida activa (`FFinal` Is Null), sin entrada/adopción activas, sin defunción |
| **Adoptado** | Adoptado | Exactamente 1 adopción activa (`FDevolucion` Is Null), sin entrada/acogida activas, sin defunción |
| **Fallecido (X)** | Fallecido, donde X es el estado anterior | Fecha de defunción rellenada en `TbFichaAnimal.FDefuncion`; sin registros activos; el paréntesis indica el estado anterior (`UltimoEstadoAntesDeFallecido`) |
| **Incoherente** | Estado inconsistente detectado por el sistema | Múltiples estados activos simultáneos (p.ej. entrada activa + acogida activa) o múltiples registros del mismo tipo activos |

### Detección de "Incoherente"

La función `DameSituacion` (líneas 1219-1226 de `Funciones Generales.bas`) marca un animal como **Incoherente** cuando:

- Tiene entrada activa **Y** (acogida activa **O** adopción activa **O** fecha de defunción)
- Tiene acogida activa **Y** (entrada activa **O** adopción activa **O** fecha de defunción)
- Tiene adopción activa **Y** (entrada activa **O** acogida activa **O** fecha de defunción)
- Tiene fecha de defunción **Y** (entrada activa **O** acogida activa **O** adopción activa)
- Tiene **más de 1** entrada/acogida/adopción activa (detectado por presencia de `#` en el ID concatenado)

### Política APAP_WEB para nuevas incoherencias

APAP_WEB debe respetar el comportamiento de fondo del legacy: si los registros activos no son compatibles, el animal queda en estado **Incoherente**. Sin embargo, la nueva interfaz debe mejorar la experiencia:

- Al iniciar un flujo que pueda generar incoherencia, la aplicación debe avisar pronto, antes de que Virginia rellene todo el asistente.
- El aviso debe requerir confirmación explícita antes de continuar.
- El aviso no debe ocultar el problema ni normalizarlo automáticamente.
- Si finalmente se confirma la operación, el animal queda marcado como **Incoherente** para revisión.
- Este aviso debe aparecer también como pendiente de calidad de datos cuando proceda.

---

## 2. Funciones de control de estado

### 2.1 `DameSituacion(strNChip, strSoloSituacion)` — Calculador de estado

**Archivo**: `Funciones Generales.bas`, línea 1116

**Retorna**: `"1|respuesta|error"` donde `respuesta` tiene el formato:
```
strSituacion;strIDEntrada1#...#strIDEntradan;strIDAcogida;strIDAdopcion;strFDefuncion;strFEntregaAPropietario
```

**Lógica de determinación** (simplificada):

```
1. Buscar entradas activas (FSalida Is Null) → strIDEntrada
2. Buscar acogidas activas (FFinal Is Null) → strIDAcogida
3. Buscar adopciones activas (FDevolucion Is Null) → strIDAdopcion
4. Leer FDefuncion, Situacion, UltimoEstadoAntesDeFallecido de TbFichaAnimal

5. Evaluar en orden:
   a. Si hay más de 1 tipo activo → "Incoherente"
   b. Si no hay nada activo y no hay defuncion:
      - Si no tiene entradas → "Pendiente de entrada"
      - Si tiene entradas pero la última no tiene FEntregaAPropietario → "Pendiente de Nueva Situación"
      - Si la última tiene FEntregaAPropietario → "Entregado"
   c. Si solo hay entrada activa (única) → "Albergue"
   d. Si solo hay acogida activa (única) → "Acogida"
   e. Si solo hay adopción activa (única) → "Adoptado"
   f. Si hay defuncion → "Fallecido (estado_anterior)"
```

### 2.2 `RegistrarSituacion(strNChip)` — Persistidor de estado

**Archivo**: `Funciones Generales.bas`, línea 1666

Esta función:
1. Calcula el estado actual usando `DameSituacion`
2. Escribe el resultado en `TbFichaAnimal.Situacion`
3. Actualiza `TbFichaAnimal.UltimoEstadoAntesDeFallecido` cuando el estado es Albergue/Acogida/Adoptado (para preservarlo antes de una defunción)
4. Actualiza contadores globales de animales en estados especiales

**Manejo especial del estado "Fallecido"** (líneas 1677-1697):
Cuando el animal está en estado "Fallecido" y se invoca desde un origen conocido (Entrada/Acogida/Adopción), la función reemplaza el texto del estado anterior dentro del paréntesis de "Fallecido" para reflejar el estado real antes de la muerte.

### 2.3 `CerrarTodasLasSituacionesPorFallecimiento(strNChip, strFDefuncion)` — Cierre masivo por defunción

**Archivo**: `Funciones Generales.bas`, línea 3706

Al registrar una defunción, esta función cierra **todas** las situaciones abiertas:

| Tabla | Campo actualizado | Valor asignado |
|---|---|---|
| `TbAcogidaAnimal` | `FFinal` | Fecha de defunción |
| `TbAdopcion` | `FDevolucion` | Fecha de defunción |
| `TbEntradas` | `FSalida` | Fecha de defunción |

### 2.4 `AnimalBorrable(strNChip)` — Borrado de ficha

**Archivo**: `Funciones Generales.bas`, línea 3310

Un animal **solo** puede ser borrado si **no** tiene registros en:
- `TbEntradas` (entradas)
- `TbAcogidaAnimal` (acogidas)
- `TbActuacionSanitaria` (actuaciones sanitarias)
- `TbAdopcion` (adopciones)
- `TbTerapias` (terapias)

En la práctica, solo los animales en estado **"Pendiente de entrada"** (solo ficha) pueden ser borrados.

---

## 3. Matriz de transiciones de ciclo de vida

### 3.1 Acciones disponibles por estado (Formulario de Elección de Fin de Situación)

El formulario `FormFichaAnimalEleccionFinSituacion` (líneas 213-259) habilita/deshabilita botones según el estado actual:

| Estado actual | Nueva Acogida | Fallecimiento | Nueva Adopción | Nueva Entrada | Entrega a Propietario |
|---|:---:|:---:|:---:|:---:|:---:|
| **Pendiente de entrada** | ✅ | ✅ | ✅ | ✅ | ❌* |
| **Pendiente de Nueva Situación** | ✅ | ✅ | ✅ | ✅ | ❌* |
| **Albergue** | ✅ | ✅ | ✅ | ❌ | ❌* |
| **Acogida** | ❌ | ✅ | ✅ | ✅ | ❌* |
| **Adoptado** | ✅ | ✅ | ❌ | ✅ | ❌* |
| **Entregado** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Fallecido (X)** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Incoherente** | ❌ | ❌ | ❌ | ❌ | ❌ |

> *El botón "Entrega a Propietario" se controla independientemente: solo se habilita si existe un `strIDEntrada` (entrada activa), sin importar el estado.

### 3.2 Transiciones detalladas (desde → hacia)

#### Desde "Pendiente de entrada"
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| Nueva entrada → **Albergue** | Albergue | `Entrada.Alta` verifica: modo estricto → estado debe ser "Pendiente de entrada" o "Pendiente de Nueva Situación" | `Entrada.cls:884-888` |
| Nueva acogida → **Acogida** | Acogida | `Acogida.Alta` verifica: modo estricto → estado debe ser "Pendiente de Nueva Situación"; requiere casa de acogida, tipo, voluntarios | `Acogida.cls:742-747` |
| Nueva adopción → **Adoptado** | Adoptado | `Adopcion.Alta` verifica: modo estricto sin origen → estado debe ser "Pendiente de Nueva Situación"; sin adopción activa; sin acogida activa | `Adopcion.cls:195-207` |
| Fallecimiento → **Fallecido** | Fallecido (Desconocido) | Requiere fecha de defunción ≥ fecha nacimiento; llama `CerrarTodasLasSituacionesPorFallecimiento` | `FormFichaAnimalFallecimiento.cls:184` |

#### Desde "Pendiente de Nueva Situación"
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| Nueva entrada → **Albergue** | Albergue | Misma guarda que desde "Pendiente de entrada" | `Entrada.cls:884-888` |
| Nueva acogida → **Acogida** | Acogida | Misma guarda que desde "Pendiente de entrada" | `Acogida.cls:742-747` |
| Nueva adopción → **Adoptado** | Adoptado | Misma guarda que desde "Pendiente de entrada" | `Adopcion.cls:195-207` |
| Fallecimiento → **Fallecido** | Fallecido (Pendiente de Nueva Situación) | Misma lógica de defunción | `FormFichaAnimalFallecimiento.cls:184` |

#### Desde "Albergue" (animal en el refugio)
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| Nueva acogida → **Acogida** | Acogida | Se cierra la entrada activa (`FSalida` = fecha de acogida) antes de abrir acogida; se llama `CerrarSituacionNoEjecutivas` | `FormAcogidaGestion.cls:335-353` |
| Nueva adopción → **Adoptado** | Adoptado | Se cierra la entrada activa (`FSalida` = fecha de adopción) antes de abrir adopción; se llama `CerrarSituacionNoEjecutivas` | `FormAdopcionGestion.cls` / `FormAdopcionAlta.cls:180-190` |
| Fallecimiento → **Fallecido** | Fallecido (Albergue) | `CerrarTodasLasSituacionesPorFallecimiento` cierra la entrada activa | `FormFichaAnimalFallecimiento.cls:184` |
| ~~Nueva entrada~~ | ❌ Bloqueado | El botón "Entrada" está deshabilitado en modo Albergue | `FormFichaAnimalEleccionFinSituacion.cls:222` |

#### Desde "Acogida" (animal en acogida temporal)
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| Nueva adopción → **Adoptado** | Adoptado | Se cierra la acogida activa (`FFinal` = fecha de adopción); se cierra la entrada activa; se llama `CerrarSituacionNoEjecutivas` | `FormAdopcionAlta.cls:193-203` |
| Nueva entrada → **Albergue** | Albergue | Se cierra la acogida activa (`FFinal` = fecha de entrada); se llama `CerrarSituacionNoEjecutivas` | `FormAcogidaGestion.cls:662-680` |
| Fallecimiento → **Fallecido** | Fallecido (Acogida) | `CerrarTodasLasSituacionesPorFallecimiento` cierra la acogida activa | `FormFichaAnimalFallecimiento.cls:184` |
| ~~Nueva acogida~~ | ❌ Bloqueado | El botón "Acogida" está deshabilitado en modo Acogida | `FormFichaAnimalEleccionFinSituacion.cls:214` |

#### Desde "Adoptado" (animal adoptado)
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| Nueva acogida → **Acogida** | Acogida | Se cierra la adopción activa (`FDevolucion` = fecha de acogida); se llama `CerrarSituacionNoEjecutivas` | `FormAdopcionGestion.cls` / gestion flow |
| Nueva entrada → **Albergue** | Albergue | Se cierra la adopción activa (`FDevolucion` = fecha de entrada); se llama `CerrarSituacionNoEjecutivas` | `FormAdopcionGestion.cls` |
| Fallecimiento → **Fallecido** | Fallecido (Adoptado) | `CerrarTodasLasSituacionesPorFallecimiento` cierra la adopción activa | `FormFichaAnimalFallecimiento.cls:184` |
| ~~Nueva adopción~~ | ❌ Bloqueado | El botón "Adopción" está deshabilitado en modo Adoptado | `FormFichaAnimalEleccionFinSituacion.cls:227` |

#### Desde "Entregado" (devuelto al propietario)
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| ~~Todas~~ | ❌ Bloqueado | Todos los botones están deshabilitados | `FormFichaAnimalEleccionFinSituacion.cls:249-253` (else) |

> **Nota**: El estado "Entregado" se alcanza desde "Albergue" a través del botón "Entrega a Propietario", que actualiza `TbEntradas.FEntregaAPropietario` y `TbEntradas.FSalida` con la fecha proporcionada, y luego llama `RegistrarSituacion`.

#### Desde "Fallecido (X)"
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| ~~Todas~~ | ❌ Bloqueado | Todos los botones están deshabilitados; el animal no puede volver a ningún estado activo | `FormFichaAnimalEleccionFinSituacion.cls:229-233` |

> **Nota**: En modo **no estricto**, el formulario de edición (`FormFichaAnimalEdicion`) permite "Eliminar Fallecimiento" cambiando el caption del botón, lo que revierte la defunción. Este comportamiento **no existe en modo estricto**.

#### Desde "Incoherente"
| Acción | Estado destino | Guardas / Validaciones | Evidencia del código |
|---|---|---|---|
| ~~Todas~~ | ❌ Bloqueado | Todos los botones están deshabilitados; se requiere resolución manual | `FormFichaAnimalEleccionFinSituacion.cls:234-238` |

---

## 4. Acciones de cierre de situaciones

### 4.1 `CerrarSituacionNoEjecutivas(strSituacion, strIDACerrar)`

**Archivo**: `Variables de Entorno.bas`, línea 193

Se llama antes de abrir una nueva situación para cerrar la anterior. La lógica varía según la situación de origen:

| Situación de origen | Acción de cierre |
|---|---|
| Albergue | Actualiza `TbEntradas.FSalida` con la fecha de la nueva situación |
| Acogida | Actualiza `TbAcogidaAnimal.FFinal` con la fecha de la nueva situación |
| Adoptado | Actualiza `TbAdopcion.FDevolucion` con la fecha de la nueva situación |
| Fallecido | Manejo especial (no cierra, ya está cerrado) |

### 4.2 Entrega a propietario (desde "Albergue")

**Archivo**: `FormFichaAnimalEleccionFinSituacion.cls`, línea 89-119

Cuando se selecciona "Entrega a Propietario" desde un animal en Albergue:

```sql
UPDATE TbEntradas
SET FEntregaAPropietario = <fecha>, FSalida = <fecha>
WHERE IDEntrada = <strIDEntrada>
```

Luego se llama `RegistrarSituacion` que calculará el estado "Entregado" basándose en la presencia de `FEntregaAPropietario` en la última entrada.

---

## 5. Validaciones de integridad temporal

Todas las validaciones temporales están sujetas al modo estricto (`BaseEnModoEstricto = "Sí"`):

| Validación | Regla | Fuente |
|---|---|---|
| Fecha de defunción ≥ Fecha de nacimiento | `FDefuncion >= FNacimiento` | `FormFichaAnimalFallecimiento.cls:86-88` |
| Fecha de adopción ≥ Fecha de nacimiento | `FAdopcion >= FNacimiento` | `Adopcion.cls:322-325` |
| Fecha de adopción ≥ Fecha de entrada a protectora | `FAdopcion >= FEntradaProtectora` | `Adopcion.cls:326-329` |
| Fecha de acogida ≥ Fecha de nacimiento | `Finicial >= FNacimiento` | `Acogida.cls:784-788` |
| Animal ya fallecido no puede volver a registrarse | Si `FDefuncion` ya existe y no se indica ComunicacionARIAC → bloquea | `FormFichaAnimalFallecimiento.cls:118-122` |

---

## 6. Datos requeridos por operación

### 6.1 Nueva entrada (`Entrada.Alta`)
- NChip, Fecha de entrada, Voluntario, Nombre del entregador, DNI del entregador, Fecha de recogida, ¿Es propietario? (Sí/No), Lugar de recogida
- Si es propietario: motivo de entrega obligatorio
- Opcionales: donativo, cuota, RIAC (impreso, fecha, motivo), datos del entregador, observaciones, anamnesis, estado físico

### 6.2 Nueva acogida (`Acogida.Alta`)
- IDAcogidaCasa (casa de acogida), NChip, Tipo (Temporal/Condicionada), Fecha inicial, Voluntario de seguimiento 1 + teléfono, Voluntario sanitario + teléfono + email
- No se puede acoger el mismo animal en la misma casa si ya tiene una acogida activa para esa casa

### 6.3 Nueva adopción (`Adopcion.Alta`)
- NChip, NContrato (único), Fecha de adopción, Vales de vacunación (Sí/No), Voluntario de seguimiento 1, Responsable de adopción, Móvil del voluntario, Email del voluntario, Compromiso esterilización (Sí/No), Datos del adoptante (nombre, apellidos, DNI, dirección, teléfonos), Tipo de adopción (Preadopción/Adopción/Entrega)
- **Reglas adicionales**:
  - No se puede repetir un NContrato previo para el mismo animal
  - No se puede usar un NContrato ya empleado para otro animal
  - Si viene de acogida: cierra la acogida y crea entrada/salida reguladora

### 6.4 Fallecimiento
- Fecha de defunción (obligatoria)
- Opcionales: Eutanasia (Sí/No), Causa de eutanasia (enfermedad/otras causas), ComunicacionARIAC
- **Efecto en cascada**: cierra TODAS las situaciones abiertas del animal

---

## 7. Implicaciones para el diseño web (APAP_WEB)

### 7.1 State machine obligatoria
El sistema web debe implementar una **máquina de estados** que replique fielmente la lógica de `DameSituacion`. Los estados y transiciones documentados arriba son la fuente de verdad.

### 7.2 Reglas críticas a preservar
1. **Un solo estado activo**: Un animal solo puede tener 1 entrada activa, 1 acogida activa O 1 adopción activa. Nunca dos del mismo tipo ni de tipos incompatibles.
2. **Cierre automático al cambiar de estado**: Al transitar de Albergue→Acogida, se cierra la entrada. Al transitar de Acogida→Adopción, se cierra la acogida Y la entrada. etc.
3. **Defunción cierra todo**: registrar una defunción cierra todas las situaciones abiertas del animal.
4. **No hay retroceso desde Entregado/Fallecido**: estos estados son terminales en modo estricto.
5. **Incoherente es un estado de error**: requiere intervención manual; no permite acciones.
6. **Borrado solo con ficha limpia**: un animal solo puede eliminarse si no tiene ningún registro asociado (entradas, acogidas, adopciones, actuaciones sanitarias, terapias).

### 7.3 Funciones del backend a replicar
| Función legado | Equivalente web propuesto | Descripción |
|---|---|---|
| `DameSituacion` | `calculateAnimalState()` | Calcula el estado actual del animal a partir de sus registros |
| `RegistrarSituacion` | `persistAnimalState()` | Escribe el estado calculado en la tabla del animal |
| `CerrarTodasLasSituacionesPorFallecimiento` | `closeAllOnDeath()` | Cierra todas las situaciones abiertas ante una defunción |
| `CerrarSituacionNoEjecutivas` | `closePreviousSituation()` | Cierra la situación anterior al abrir una nueva |
| `AnimalBorrable` | `canDeleteAnimal()` | Verifica si un animal puede ser eliminado |

### 7.4 Consideraciones de modo estricto
El legado tiene un concepto de "modo estricto" (`BaseEnModoEstricto`) que activa/desactiva validaciones. En el web, se recomienda **siempre** operar en modo estricto ya que:
- Las validaciones de integridad temporal son esenciales
- El control de estados previene inconsistencias
- El borrado de animales con datos asociados debe estar siempre prohibido

---

## 8. Diagrama de transiciones (texto)

```
                    ┌─────────────────────┐
                    │ Pendiente de entrada │
                    └──────┬──────────────┘
                           │ Nueva entrada / Acogida / Adopción
                           ▼
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Albergue │ │ Acogida  │ │ Adoptado │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │             │             │
             │  ┌──────────┘  ┌──────────┘
             │  │             │
             ▼  ▼             ▼
        ┌────────────────────────────────┐
        │  Transiciones entre estados:   │
        │  Albergue → Acogida/Adopción   │
        │  Acogida → Adopción/Entrada    │
        │  Adoptado → Acogida/Entrada    │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │  Cualquier estado activo   │
        │  + Fallecimiento           │
        │         ↓                  │
        │  Fallecido (estado anterior)│
        └────────────────────────────┘

        ┌────────────────────────────┐
        │  Albergue + Entrega a      │
        │  Propietario               │
        │         ↓                  │
        │  Entregado                 │
        └────────────────────────────┘
```

---

## 9. Tablas de base de datos involucradas

| Tabla | Campos clave | Rol en el ciclo de vida |
|---|---|---|
| `TbFichaAnimal` | `NChip`, `Situacion`, `FDefuncion`, `UltimoEstadoAntesDeFallecido`, `FNacimiento`, `ComunicacionARIAC`, `FEntregaAPropietario` (campo del animal, no de entrada) | Ficha maestra del animal; almacena estado calculado y datos de defunción |
| `TbEntradas` | `IDEntrada`, `NChip`, `FEntrada`, `FSalida`, `FEntregaAPropietario`, `IDAcogida` | Registro de entradas al refugio; `FSalida` Is Null = entrada activa |
| `TbAcogidaAnimal` | `IDAcogida`, `NChip`, `IDAcogidaCasa`, `FFinal`, `Finicial`, `TipoAcogida` | Registro de acogidas; `FFinal` Is Null = acogida activa |
| `TbAdopcion` | `IDAdopcion`, `NChip`, `FDevolucion`, `FAdopcion`, `NContrato` | Registro de adopciones; `FDevolucion` Is Null = adopción activa |
| `TbActuacionSanitaria` | `NChip` | Actuaciones sanitarias (impide borrado) |
| `TbTerapias` | `NChip` | Terapias (impide borrado) |
