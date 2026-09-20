<!--
PLANTILLA DE DOCUMENTO DE CAPACIDAD — calidad SDD, reproducible sin código.
Linaje: arc42 (arquitectura) + Specification by Example/BDD (§2) + ADR (§3 valoración) + Matriz de Trazabilidad de Requisitos (§5).

Profundidad por tier:
  minimal  → §0, §1 (breve), §2 (reglas + señales de aceptación), §7
  standard → §0–§5, §7
  critical → todas las secciones, completas
Objetivo de migración web (cualquier tier): §3 (modelo de datos) + §6 (especificación de migración) + §8 (semilla SDD)
son obligatorios; juntos permiten que una IA levante el SDD del porte legacy→web sin leer el código.

Regla de verdad: EL CÓDIGO es la fuente de verdad del QUÉ/CÓMO. SDD/responsable de producto es la fuente del POR QUÉ.
Verifica los hechos de comportamiento contra el código + Dysflow antes de marcar Verified. Ver references/reproducibility-model.md.
Idioma: toda la documentación en castellano de España. Los identificadores de código, nombres de test, tools de Dysflow y los enums (tier/status/source/niveles de confianza) se mantienen tal cual.
Sustituye cada <marcador>. No borres nada sin moverlo; marca lo desconocido como Pendiente de confirmación.
-->

# Capacidad: <nombre de negocio, no el nombre de un módulo>

## §0 Identidad
- **ID de capacidad**: <CAP-xxx>
- **Tier**: critical | standard | minimal
- **Estado**: active | deprecated | broken
- **Source**: sdd | reverse-engineered | hybrid
- **Responsable / autoridad de producto**: <nombre o "Pendiente de confirmación">
- **Última verificación**: <YYYY-MM-DD> mediante <evidencia dysflow.test_vba / dysflow.verify_code>
- **Confianza global**: <Verified-runtime / mixta — ver §7>

## §1 Intención de negocio (≈ proposal SDD) — POR QUÉ
> Fuente de verdad: artefactos SDD + responsable de producto. El código NO explica el porqué.
- **Propósito**: <qué resultado de negocio habilita>
- **Usuarios / perfiles**: <quién, en qué situación>
- **Problema que resuelve**: <la carencia sin esta funcionalidad>
- **Valor de negocio / por qué existe**: <...>
- **No-objetivos**: <qué NO hace deliberadamente>
- **Origen de la intención**: <ref. proposal SDD | responsable de producto | inferido → marcar Likely>
- **Referencia de tracker de origen**: <issue GH / PR que la solicitó — o "Pendiente de confirmación">

## §2 Contrato de comportamiento (≈ spec SDD) — QUÉ  ⟵ ANCLA DE REGRESIÓN
> Esta sección permite a una IA detectar que la funcionalidad está rota o AUSENTE y reconstruirla según el contrato.

### Escenarios (Dado / Cuando / Entonces)
- **DADO** <estado> **CUANDO** <acción del usuario> **ENTONCES** <resultado observable>
- (camino alternativo) DADO … CUANDO … ENTONCES …
- (camino de error) DADO … CUANDO … ENTONCES <mensaje de error/validación>

### Reglas de negocio
> Toda regla DEBE llevar una prueba. Si "Prueba" está AUSENTE, créala con la skill `access-vba-tdd-fundamentos` — eso es un entregable de este documento, no un extra opcional.

| ID regla | Enunciado (pretendido) | Autoridad | ¿Aplicada en código? | Prueba | Confianza |
|---|---|---|---|---|---|
| BR-1 | <p. ej. el importe no puede ser negativo> | <spec SDD / responsable> | <Sí — dónde / No / Parcial> | <ruta del test + última ejecución \| AUSENTE → crear con access-vba-tdd-fundamentos> | Verified-runtime \| Verified-static \| Intended \| Divergent |

### Validaciones
- <campo/condición> → <regla> → <mensaje>

### Transiciones de estado
- <estado-origen> --(<evento/guarda>)--> <estado-destino>

### Casos límite y de error
- <caso límite> → <comportamiento esperado>

### Señales de aceptación / presencia  ⟵ cómo saber que la funcionalidad EXISTE y funciona
- <señal observable 1 que la app en ejecución debe producir>
- <señal observable 2> — si está ausente ⇒ regresión / funcionalidad ausente

## §3 Mapa de implementación (≈ design SDD) — CÓMO
> Fuente de verdad: EL CÓDIGO, confirmado con Dysflow. Esto es lo que la hace reproducible sin leer código.
- **Puntos de entrada de UI**: <formulario> → <control> → <evento, p. ej. Click>
- **Puntos de entrada de código**: <módulo/clase>.<procedimiento>(<args>)
- **Datos afectados**: <tabla/consulta>.<campos clave> — lectura | escritura
- **Salidas**: <informes / notificaciones / exportaciones>
- **Dependencias e integraciones**: <otras capacidades, APIs, backends vinculados>
- **Sincronización fuente↔binario**: importado con `dysflow.import_modules`; estado del binario confirmado con `dysflow.verify_code` el <YYYY-MM-DD>
- **Valoración de diseño (tal-como-está vs ideal)**: <veredicto — ¿bien hecho? / deuda conocida / olores de diseño>  ⟵ la respuesta a "si se ha hecho bien o no"

### Modelo de datos (agnóstico de plataforma) ⟵ base del modelo de datos web
> Entidades y campos que la capacidad toca, en términos de dominio (no de Access). Esto es lo que un modelo destino (SQL/ORM/NoSQL) debe poder representar. Captura el dominio, no solo lo que Access declara.

| Entidad (tabla Access) | Campo | Tipo lógico | Restricción / dominio | Rol en la capacidad | Nota de migración |
|---|---|---|---|---|---|
| <TbExpedientes> | <Estado> | <enum texto> | <Abierto \| Cerrado> | <lectura \| escritura> | <mapear a máquina de estados> |

- **Relaciones**: <TbExpedientes 1—N TbTareas por `idExpediente`>
- **Identidad / claves**: <PK; clave natural de negocio vs AutoNumber>
- **Reglas de integridad del dominio**: <FKs, obligatorios, unicidad que el negocio exige — no solo las declaradas en Access>

## §4 Receta de reconstrucción (≈ tasks SDD) — REPRODUCIBILIDAD
> Pasos ordenados para reconstruir esta capacidad desde cero. TODAS las operaciones fuente↔binario pasan por el MCP de Dysflow.
1. <crear/editar módulo o formulario …>
2. <cablear evento / escribir procedimiento …>
3. **Importar** cambios → `dysflow.import_modules`
4. **Verificar vínculo del formulario** (si lo hay) → `dysflow.verify_code`
5. **Demostrar el comportamiento** contra los escenarios de §2 → `dysflow.test_vba`

## §5 Evidencia y trazabilidad (≈ verify SDD)
- **Tests**: <ruta> — comprueba <qué> — última ejecución `dysflow.test_vba` <YYYY-MM-DD>, resultado <pasa/falla>
- **Trazabilidad de release** — histórico solo-añadir (una fila por evento de versión; registrar cuando se sepa, si no `Pendiente de confirmación`). Permite responder "qué versión tenía esta funcionalidad, y cuándo":

| Elemento (funcionalidad o arreglo) | Ref. tracker | Versión de staging (UAT) | Estado UAT | Release de producción | Fecha en producción | Nota |
|---|---|---|---|---|---|---|
| <id funcionalidad/arreglo> | <issue GH / PR> | <build/versión de staging> | pending \| passed \| failed | <tag/versión de producción> | <YYYY-MM-DD> | <p. ej. primer despliegue / arreglado / regresión> |

- **Tabla de diagnóstico de regresión**:

| Síntoma | Causa probable | Comprobación (Dysflow) | Ancla del documento |
|---|---|---|---|
| <funcionalidad no aparece> | <módulo no importado / formulario sin vincular> | `dysflow.verify_code` | §3 / §4 |

## §6 Especificación de migración a web (agnóstica de plataforma) ⟵ HABILITA EL PORTE LEGACY→WEB
> Esta sección + §2 (contrato observable) + el modelo de datos de §3 deben bastar para reconstruir la capacidad en una stack web SIN leer el código Access. Si falta algo aquí, la migración tendrá que volver al binario.

### Dominio a preservar (sobrevive a cualquier plataforma)
- **Reglas de negocio que deben portarse**: <IDs de §2 — BR-1, BR-2…; son invariantes de negocio, no detalles de Access>
- **Flujos / casos de uso**: <los escenarios de §2 son el contrato de aceptación que la versión web también debe pasar>

### Lógica a extraer de la UI (humble object)
> Hoy vive acoplada a eventos de formulario / VBA. En web debe vivir en servicios/casos de uso sin UI.

| Unidad de lógica | Dónde vive hoy (Access) | Qué hace (dominio) | Destino web (servicio/caso de uso) |
|---|---|---|---|
| <CanClose> | <frmExpediente.cmdClose_Click> | <valida que no haya tareas pendientes> | <CaseClosingService.canClose()> |

### Contrato funcional agnóstico (entradas → salidas)
> El caso de uso como contrato mapeable a endpoint/API, independiente de Access.
- **Entradas**: <parámetros y su tipo lógico>
- **Precondiciones**: <estado/permiso requerido antes de ejecutar>
- **Salidas / efectos**: <resultado, cambios de estado, eventos emitidos>
- **Postcondiciones**: <qué garantiza tras ejecutarse>
- **Errores / rechazos**: <condiciones de error y su semántica — deben coincidir con los caminos de error de §2>

### Intención de UI/UX (el QUÉ para el usuario, no el CÓMO de Access)
- **Qué resuelve la pantalla para el usuario**: <propósito de la interacción, no controles concretos>
- **Acciones y feedback esperado**: <acción del usuario → respuesta visible>
- **Estados de UI**: <vacío / cargando / error / éxito / sin permiso>

### Integraciones y efectos externos
| Integración (Access) | Qué hace | Equivalente web / consideración |
|---|---|---|
| <Outlook.Application> | <envía aviso por correo> | <servicio de email del backend / cola> |
| <backend vinculado> | <lee/escribe tabla X> | <API/DB del nuevo sistema> |

### Datos a migrar y mapeo
- **Tipos origen → destino**: <ver §3 modelo de datos; p. ej. AutoNumber→UUID/serial, Sí/No→boolean, Memo→text>
- **Datos a trasvasar**: <qué tablas/filas; transformaciones; limpieza necesaria>
- **Integridad a reforzar en destino**: <FKs/obligatorios/unicidad que el dominio exige>

### Requisitos no funcionales del porte
- **Seguridad**: <comprobaciones que en Access eran de cliente y en web DEBEN ser de servidor — p. ej. rol>
- **Concurrencia / auditoría / rendimiento**: <lo que aplique>

### NO portar (legado)
- <deuda de Access que no debe copiarse — p. ej. lógica en eventos de formulario, valores hardcodeados, `getdb()` global>

### Preguntas abiertas
- <para responsable de producto / calidad — bloquean decisiones de diseño web>

## §7 Registro de confianza
> `Verified-static` es transitorio: debe una prueba. Llévalo a `Verified-runtime` con `access-vba-tdd-fundamentos`.

| Hecho | Confianza | Evidencia | Fecha |
|---|---|---|---|
| <hecho de comportamiento> | Verified-runtime \| Verified-static \| Intended \| Likely \| Divergent | <ref. código + dysflow.test_vba en verde / solo ref. código / ref. SDD / inferencia> | <YYYY-MM-DD> |

**⚠️ Divergencias (intención SDD ≠ realidad del código)** — marcar para revisión humana:
- <BR-x: el spec dice A, el código hace B → bug / deuda / cambio no documentado>

## §8 Semilla SDD para migración web (consumible por una IA) ⟵ PARA LEVANTAR LOS SDDs
> Bloque estructurado para que una IA genere un SDD completo (proposal → spec → design → tasks) del porte web de ESTA capacidad sin volver al código. Cada capa cita de qué sección sale, de modo que el SDD se reconstruye trazablemente desde este documento.

- **Semilla de PROPOSAL (POR QUÉ + alcance)**: de §1 (intención, problema, valor, no-objetivos) + «Dominio a preservar» de §6. Alcance = esta capacidad; límites = los no-objetivos de §1.
- **Semilla de SPEC (QUÉ)**: los escenarios y reglas de §2 SON la spec de la versión web — el mismo contrato observable. La versión web es correcta cuando pasa los mismos escenarios (re-expresados como tests de la nueva plataforma) y respeta cada BR-*.
- **Semilla de DESIGN (CÓMO, en destino)**: modelo de datos de §3 → modelo de datos web; «Lógica a extraer» y «Contrato funcional» de §6 → servicios/casos de uso; «Integraciones» de §6 → adaptadores; «Intención de UI/UX» de §6 → vistas/rutas; requisitos no funcionales de §6 → decisiones de arquitectura.
- **Semilla de TASKS (rebanadas ordenadas)**:
  1. Modelar las entidades de §3 en la stack destino.
  2. Implementar el/los caso(s) de uso con la lógica extraída de §6 — sin UI.
  3. Exponer el contrato funcional de §6 como API/endpoint.
  4. Construir la UI según la intención de UX de §6.
  5. Reforzar seguridad y no-funcionales en servidor (§6).
  6. Tests que reflejan los escenarios de §2 (paridad de cada BR-*).
- **Criterios de aceptación de la migración**: paridad total con §2 — cada escenario y cada BR-* verificados en la nueva plataforma — y cero regresiones respecto a las «Señales de aceptación» de §2.
- **Dependencias con otras capacidades**: <CAP-xxx que comparten datos o flujos; condicionan el ORDEN de migración — ver el mapa de dependencias del índice>
