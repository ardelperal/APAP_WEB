# Especificación: ux-ui-foundation

## Propósito

Define la base UX/UI de APAP Web como producto operativo autónomo: shell, home, estados visuales, copy, componentes y señales de aceptación UAT. No añade contadores en tiempo real ni módulos no implementados.

## Requirements

### Requirement: Home operativa

La home autenticada MUST actuar como bandeja de trabajo: mostrar prioridades, pendientes y accesos útiles para la operativa diaria, no una portada técnica o comercial.

#### Scenario: Bandeja con pendientes

- GIVEN una persona autorizada accede a APAP Web
- WHEN abre la home
- THEN ve tarjetas operativas con título, estado, breve explicación y acción clara
- AND la página evita vender tecnología o hablar de migración

#### Scenario: Sin datos conectados

- GIVEN una tarjeta aún no tiene contador real
- WHEN se renderiza la home
- THEN la tarjeta indica estado pendiente o vacío sin inventar cifras
- AND no promete disponibilidad de datos que aún no existe

### Requirement: Shell y navegación incremental

El shell global MUST orientar por áreas de trabajo APAP y SHALL permitir módulos futuros sin enlaces rotos ni promesas falsas.

#### Scenario: Área disponible

- GIVEN un área tiene ruta funcional
- WHEN la persona usa la navegación
- THEN el destino es accesible y el texto describe la tarea, no la implementación

#### Scenario: Área futura

- GIVEN un área documentada aún no está implementada
- WHEN aparece en el shell
- THEN se muestra como próxima o no disponible, sin enlace roto

### Requirement: Estados visuales consistentes

El sistema MUST distinguir estados normal, pendiente, crítico y vacío con color, etiqueta textual y jerarquía visual accesible; el color MUST NOT ser la única señal.

#### Scenario: Estado crítico

- GIVEN una tarjeta representa una prioridad alta
- WHEN se muestra
- THEN usa etiqueta crítica, contraste suficiente y posición destacada

#### Scenario: Estado vacío

- GIVEN no hay trabajo para una categoría
- WHEN se muestra el bloque
- THEN comunica ausencia de pendientes y propone el siguiente paso razonable

### Requirement: Copy de producto sin lenguaje interno

Toda UI visible MUST usar castellano de España claro, orientado a tareas, y MUST NOT mostrar términos internos, legacy, stack técnico, nombres de tablas, ni APAP_WEB.

#### Scenario: Revisión de páginas visibles

- GIVEN se renderizan home, login, no autorizado y admin
- WHEN se inspecciona el texto visible
- THEN no aparece lenguaje de migración, Access, FastAPI, HTMX, LocalBackend, interno ni nombres técnicos

### Requirement: Componentes y accesibilidad base

Los componentes base MUST cubrir tarjetas, badges, botones, formularios, alertas y tablas/listados con responsive mobile-first, foco visible, estructura semántica y contraste WCAG AA.

#### Scenario: Navegación por teclado

- GIVEN una persona navega sin ratón
- WHEN recorre shell, tarjetas y acciones
- THEN el foco es visible y el orden permite completar la tarea principal

### Requirement: Señales de aceptación UAT

La especificación SHALL producir criterios validables por usuario para confirmar home, navegación, estados, copy y accesibilidad sin depender de conocimiento técnico.

#### Scenario: Validación de Virginia

- GIVEN Virginia valida la versión de la issue #6
- WHEN sigue los casos UAT
- THEN puede marcar PASA/FALLA para home operativa, navegación sin enlaces rotos, estados claros y copy profesional
