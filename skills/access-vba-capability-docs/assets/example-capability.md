<!--
EJEMPLO RESUELTO — un documento de capacidad relleno (de juguete pero realista) que muestra todas las convenciones.
Copia capability-doc-template.md para redactar uno real; usa esto solo como referencia de la forma esperada.
Idioma: castellano de España. Los enums e identificadores de código/test se mantienen tal cual.
-->

# Capacidad: Cierre de expediente

## §0 Identidad
- **ID de capacidad**: CAP-014
- **Tier**: standard
- **Estado**: active
- **Source**: hybrid
- **Responsable / autoridad de producto**: Responsable de calidad (María) — confirmado
- **Última verificación**: 2026-06-10 mediante `dysflow.test_vba` (Test_Cierre_RunAll, pasa) + `dysflow.verify_code` (frmExpediente)
- **Confianza global**: mixta — ver §7

## §1 Intención de negocio (≈ proposal SDD) — POR QUÉ
- **Propósito**: permitir a un gestor cerrar un expediente para que deje de aparecer en las cargas de trabajo activas.
- **Usuarios / perfiles**: gestor de área; solo lectura para auditores.
- **Problema que resuelve**: los expedientes cerrados seguían apareciendo en las listas activas e inflaban los indicadores.
- **Valor de negocio**: bandeja de activos limpia; fecha de cierre fiable para el reporte de SLA.
- **No-objetivos**: no archiva documentos; no notifica a sistemas externos.
- **Origen de la intención**: proposal SDD `sdd/close-case-file/proposal` + confirmación del responsable.
- **Referencia de tracker de origen**: GH #482.

## §2 Contrato de comportamiento (≈ spec SDD) — QUÉ  ⟵ ANCLA DE REGRESIÓN
### Escenarios
- DADO un expediente abierto con todas las tareas hechas CUANDO el gestor pulsa "Cerrar" ENTONCES el estado pasa a `Cerrado` y la fecha de cierre = hoy.
- (error) DADO un expediente con tareas pendientes CUANDO se pulsa "Cerrar" ENTONCES se bloquea con "Quedan tareas pendientes".
- (alternativo) DADO un expediente ya cerrado CUANDO se visualiza ENTONCES "Cerrar" está deshabilitado.

### Reglas de negocio
| ID regla | Enunciado (pretendido) | Autoridad | ¿Aplicada en código? | Prueba | Confianza |
|---|---|---|---|---|---|
| BR-1 | No se puede cerrar con tareas pendientes | spec SDD | Sí — `modExpediente.CanClose` | tests/Test_Cierre.bas::Test_Cierre_BloqueaPendientes — pasa 2026-06-10 | Verified-runtime |
| BR-2 | La fecha de cierre = fecha del sistema, no editable | responsable | Sí — `frmExpediente.cmdClose_Click` | AUSENTE → crear con access-vba-tdd-fundamentos | Verified-static |
| BR-3 | Solo el rol `Gestor` puede cerrar | spec SDD | No — cualquier usuario autenticado puede cerrar | tests/Test_Cierre.bas::Test_Cierre_SoloGestor — FALLA | Divergent |

### Validaciones
- El número de tareas pendientes debe ser 0 → mensaje "Quedan tareas pendientes".

### Transiciones de estado
- `Abierto` --(Cerrar, guarda: sin tareas pendientes)--> `Cerrado`

### Señales de aceptación / presencia
- Botón "Cerrar" visible en `frmExpediente` para expedientes abiertos.
- Cerrar un expediente válido fija el estado `Cerrado` y una fecha de cierre no nula. Si al pulsar no pasa nada ⇒ regresión.

## §3 Mapa de implementación (≈ design SDD) — CÓMO
- **Puntos de entrada de UI**: `frmExpediente` → `cmdClose` → Click.
- **Puntos de entrada de código**: `frmExpediente.cmdClose_Click`, `modExpediente.CanClose(idExp)`.
- **Datos afectados**: `TbExpedientes.Estado` (escritura), `.FechaCierre` (escritura); `TbTareas` (lectura, recuento de pendientes).
- **Salidas**: ninguna (sin informe/notificación).
- **Dependencias e integraciones**: módulo de Tareas (recuento de pendientes); módulo de Seguridad (comprobación de rol — ver laguna BR-3).
- **Sincronización fuente↔binario**: importado con `dysflow.import_modules`; binario confirmado con `dysflow.verify_code` el 2026-06-10.
- **Valoración de diseño (tal-como-está vs ideal)**: mayormente limpio, PERO la comprobación de rol (BR-3) nunca se implementó — deuda de seguridad. La lógica de cierre vive en el evento del formulario, no en el módulo; aceptable para este tier.

### Modelo de datos (agnóstico de plataforma)
| Entidad (tabla Access) | Campo | Tipo lógico | Restricción / dominio | Rol en la capacidad | Nota de migración |
|---|---|---|---|---|---|
| TbExpedientes | Estado | enum texto | Abierto \| Cerrado | escritura | mapear a máquina de estados |
| TbExpedientes | FechaCierre | fecha | nulo hasta el cierre | escritura | timestamp de servidor en web |
| TbTareas | idExpediente, Estado | FK long / enum | Pendiente \| Hecha | lectura (recuento de pendientes) | índice por idExpediente |

- **Relaciones**: `TbExpedientes` 1—N `TbTareas` por `idExpediente`.
- **Identidad / claves**: PK `idExpediente` (AutoNumber) → en web, UUID o serial con clave natural de expediente.
- **Reglas de integridad del dominio**: un expediente cerrado no admite tareas nuevas; `FechaCierre` obligatoria si `Estado=Cerrado`.

## §4 Receta de reconstrucción (≈ tasks SDD)
1. Añadir `modExpediente.CanClose(idExp)` que devuelva False cuando tareas pendientes > 0.
2. En `frmExpediente.cmdClose_Click`: proteger con `CanClose`, fijar `Estado="Cerrado"`, `FechaCierre=Date`, exigir rol `Gestor` (cierra la laguna BR-3).
3. Importar → `dysflow.import_modules`.
4. Verificar formulario → `dysflow.verify_code` (frmExpediente).
5. Demostrar los escenarios de §2 → `dysflow.test_vba` (Test_Cierre_RunAll), incluidos los nuevos tests de BR-2 y BR-3.

## §5 Evidencia y trazabilidad
- **Tests**: tests/Test_Cierre.bas — comprueba los escenarios BR-1/BR-3 — última `dysflow.test_vba` 2026-06-10, BR-1 pasa / BR-3 falla.
- **Trazabilidad de release** (solo-añadir):

| Elemento (funcionalidad o arreglo) | Ref. tracker | Versión de staging (UAT) | Estado UAT | Release de producción | Fecha en producción | Nota |
|---|---|---|---|---|---|---|
| Cierre de expediente | GH #482 | staging-2026.04 | passed | v8.3.0 | 2026-05-02 | primer despliegue |
| Arreglo: bloquear cierre con tareas pendientes | GH #511 | staging-2026.05 | passed | v8.3.1 | 2026-05-20 | arreglado |
| Comprobación de rol (BR-3) | GH #530 | Pendiente de confirmación | pending | Pendiente de confirmación | — | aún sin desplegar |

- **Tabla de diagnóstico de regresión**:

| Síntoma | Causa probable | Comprobación (Dysflow) | Ancla del documento |
|---|---|---|---|
| El botón Cerrar no hace nada | modExpediente no importado / formulario sin vincular | `dysflow.verify_code` | §3 / §4 |
| Cualquier usuario puede cerrar | BR-3 nunca implementada | `dysflow.test_vba` Test_Cierre_SoloGestor | §2 BR-3 |

## §6 Especificación de migración a web (agnóstica de plataforma)
### Dominio a preservar
- **Reglas a portar**: BR-1 (no cerrar con tareas pendientes), BR-2 (fecha de cierre = fecha de servidor, no editable), BR-3 (solo rol `Gestor` cierra).
- **Flujos / casos de uso**: los 3 escenarios de §2 son el contrato de aceptación de la versión web.

### Lógica a extraer de la UI (humble object)
| Unidad de lógica | Dónde vive hoy (Access) | Qué hace (dominio) | Destino web |
|---|---|---|---|
| CanClose | `modExpediente.CanClose` | valida que no haya tareas pendientes | `CaseClosingService.canClose(caseId)` |
| Fijar cierre | `frmExpediente.cmdClose_Click` | fija Estado=Cerrado, FechaCierre=hoy | `CaseClosingService.close(caseId, actor)` |
| Comprobación de rol | (ausente — BR-3 sin implementar) | exige rol Gestor | guard de autorización en servidor |

### Contrato funcional agnóstico
- **Entradas**: `caseId`, `actor` (usuario autenticado con rol).
- **Precondiciones**: expediente en estado `Abierto`; `actor` con rol `Gestor`.
- **Salidas / efectos**: estado → `Cerrado`, `FechaCierre` = fecha de servidor; evento `CaseClosed`.
- **Postcondiciones**: el expediente deja de aparecer en cargas activas.
- **Errores**: tareas pendientes → `PendingTasksError`; sin rol → `ForbiddenError` (coinciden con los caminos de error de §2).

### Intención de UI/UX
- **Qué resuelve**: el gestor saca un expediente terminado de su bandeja activa.
- **Acciones y feedback**: acción "Cerrar" → confirmación de éxito o mensaje "Quedan tareas pendientes".
- **Estados de UI**: acción deshabilitada si ya cerrado o sin rol; bloqueante con tareas pendientes.

### Integraciones y efectos externos
| Integración (Access) | Qué hace | Equivalente web |
|---|---|---|
| módulo de Seguridad | comprobación de rol (hoy ausente) | guard de autorización en servidor |
| (ninguna externa) | — | — |

### Datos a migrar y mapeo
- **Tipos**: `idExpediente` AutoNumber → serial/UUID; `Estado` texto → enum; `FechaCierre` Date → timestamp con zona.
- **Datos a trasvasar**: expedientes y tareas con su estado e historial de cierre.
- **Integridad a reforzar**: FK `TbTareas.idExpediente`; `FechaCierre` obligatoria cuando `Estado=Cerrado`.

### Requisitos no funcionales del porte
- **Seguridad**: BR-3 (rol) DEBE comprobarse en servidor — en Access estaba ausente (deuda); no replicar la ausencia.
- **Auditoría**: registrar quién y cuándo cerró.

### NO portar (legado)
- La lógica de cierre incrustada en `cmdClose_Click` — moverla a `CaseClosingService`.
- La ausencia de comprobación de rol (BR-3) — corregir, no copiar.

### Preguntas abiertas
- ¿El cierre debe encadenar el archivado de documentos? (responsable de producto)

## §7 Registro de confianza
| Hecho | Confianza | Evidencia | Fecha |
|---|---|---|---|
| Cierre bloqueado con tareas pendientes | Verified-runtime | Test_Cierre_BloqueaPendientes pasa | 2026-06-10 |
| Fecha de cierre = fecha del sistema | Verified-static | Leído en cmdClose_Click; sin test aún | 2026-06-10 |
| Solo el Gestor puede cerrar | Divergent | El spec lo exige; el código no lo aplica; el test falla | 2026-06-10 |

**⚠️ Divergencias (intención SDD ≠ realidad del código)**:
- BR-3: el spec exige cierre solo para rol `Gestor`; el código permite a cualquier usuario → deuda de seguridad, seguida en GH #530.

## §8 Semilla SDD para migración web (consumible por una IA)
- **PROPOSAL**: portar el cierre de expediente a la web para sacar expedientes terminados de las bandejas activas (de §1); alcance = esta capacidad; no-objetivos = no archiva documentos, no notifica a externos.
- **SPEC**: los 3 escenarios de §2 + BR-1/BR-2/BR-3 son la spec. La web es correcta cuando los pasa todos — incluida BR-3, que en Access estaba ausente.
- **DESIGN**: entidades de §3 (Expediente, Tarea) → modelo de datos web; `CaseClosingService` (de §6) como caso de uso sin UI; guard de autorización en servidor; endpoint `POST /cases/{id}/close`; vista de detalle con acción "Cerrar".
- **TASKS**:
  1. Modelar `Expediente`/`Tarea` con la restricción FechaCierre↔Cerrado.
  2. `CaseClosingService.canClose/close` con la guarda de tareas pendientes.
  3. Endpoint `POST /cases/{id}/close` con el contrato funcional de §6.
  4. UI de detalle con acción "Cerrar" y sus estados.
  5. Guard de rol `Gestor` en servidor (cierra BR-3).
  6. Tests que reflejan los 3 escenarios de §2.
- **Criterios de aceptación**: paridad con §2 (los 3 escenarios + BR-1/2/3 en verde en la nueva plataforma); BR-3 deja de ser `Divergent`.
- **Dependencias**: comparte `TbTareas` con la capacidad "Gestión de tareas" (CAP-009) → migrar/alinear su modelo de datos antes o a la vez.
