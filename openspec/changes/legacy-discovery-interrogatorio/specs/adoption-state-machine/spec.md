# Spec: ADOPTION — State Machine de Seguimiento Post-Adopción (issue #49, task 3.5)

## Context

Issue #49 (ADOPT-03). Implementar la state machine de seguimiento post-adopción:
después de registrar una adopción, hay un flujo de seguimiento con 4 estados
que tracked document delivery y completion. Esto es independiente del estado
lifecycle del animal (que ya está en ADOPTADO).

## Current state on main@0ab533d

**Ya existe:**
- Tabla `adopciones` con campos básicos de adopción ( adopters, animal, contract).
- CRUD de adopciones en `app/modules/adopciones/service.py` + `routes.py`.
- Feature 02 discovery: `docs/discovery/feature-02-intake-foster-adoption.md` §2.3.
- Feature 04 discovery: `docs/discovery/state-machines.md` §5 con la state machine completa.

**Falta:**
- Campo `seguimiento_estado` en la tabla `adopciones`.
- Endpoints de transición de estado de seguimiento: marcar documento enviado,
  anexar documento, completar seguimiento.
- Validación de transiciones (solo las permitidas según la matriz).

**Fuente:** `docs/discovery/state-machines.md` §5 ("Adoption Follow-Up State Machine").

## Required contract

### Seguimiento estados

| Estado | Significado |
|--------|-------------|
| `PENDIENTE` | Adopción registrada; documentos de seguimiento no entregados |
| `DOCUMENTO_ENTREGADO` | Documento de seguimiento enviado al adoptante |
| `DOCUMENTO_ADJUNTO` | Adoptante ha devuelto el documento firmado; está anexado |
| `SEGUIMIENTO_COMPLETADO` | Proceso de seguimiento completamente cerrado |

### Transiciones válidas

| Desde | Hacia | Trigger |
|-------|-------|---------|
| PENDIENTE | DOCUMENTO_ENTREGADO | Mark documento enviado |
| PENDIENTE | SEGUIMIENTO_COMPLETADO | Completion directa (sin documento) |
| DOCUMENTO_ENTREGADO | DOCUMENTO_ADJUNTO | Anexar documento firmado |
| DOCUMENTO_ADJUNTO | SEGUIMIENTO_COMPLETADO | Staff marca completado |
| DOCUMENTO_ENTREGADO | SEGUIMIENTO_COMPLETADO | Override (raro) |
| DOCUMENTO_ADJUNTO | SEGUIMIENTO_COMPLETADO | — (mismo que arriba) |

### Endpoint

```
PATCH /adopciones/{adopcion_id}/seguimiento
Body: { "action": "marcar_entregado" | "anexar_documento" | "completar" }
```

### Service function

```python
def transition_seguimiento(
    client: SqlExecutor,
    adopcion_id: UUID,
    action: SeguimientoAction,
    operador_user_id: str,
    documento_url: str | None = None  # para "anexar_documento"
) -> SeguimientoTransitionResult:
    """
    Efectúa transición de estado de seguimiento si es válida.
    Retorna el nuevo estado o error con razón.
    """
```

### Campos a agregar en `adopciones`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `seguimiento_estado` | TEXT | Estado actual del seguimiento |
| `seguimiento_documento_url` | TEXT | URL del documento anexado (si existe) |
| `seguimiento_documento_entregado_at` | TIMESTAMPTZ | Fecha de envío del documento |
| `seguimiento_completado_at` | TIMESTAMPTZ | Fecha de completion |

### Validación de transición

```python
VALID_TRANSITIONS = {
    SeguimientoEstado.PENDIENTE:
        {SeguimientoAction.MARCAR_ENTREGADO: SeguimientoEstado.DOCUMENTO_ENTREGADO,
         SeguimientoAction.COMPLETAR: SeguimientoEstado.SEGUIMIENTO_COMPLETADO},
    SeguimientoEstado.DOCUMENTO_ENTREGADO:
        {SeguimientoAction.ANEXAR: SeguimientoEstado.DOCUMENTO_ADJUNTO,
         SeguimientoAction.COMPLETAR: SeguimientoEstado.SEGUIMIENTO_COMPLETADO},
    SeguimientoEstado.DOCUMENTO_ADJUNTO:
        {SeguimientoAction.COMPLETAR: SeguimientoEstado.SEGUIMIENTO_COMPLETADO},
}
```

## Dependencies

- Task 3.1 (LIFECYCLE state resolver) — para entender el estado ADOPTADO del animal.
- Task 3.7 (DOC-01: anexos) — para `documento_url` en storage.

## Acceptance criteria

1. `PATCH /adopciones/{id}/seguimiento` con acción válida → transición al nuevo estado.
2. `PATCH /adopciones/{id}/seguimiento` con acción inválida para el estado actual →
   409 Conflict con mensaje claro.
3. El estado del seguimiento (`PENDIENTE` → `DOCUMENTO_ENTREGADO` → etc.) es
   independiente del estado lifecycle del animal (ADOPTADO sigue igual).
4. La fecha de cada transición se registra en los campos `_entregado_at`, `_completado_at`.
5. El documento anexado se sube a object storage (DOC-01) y la URL se guarda en
   `seguimiento_documento_url`.
6. Logs via `log_safe("adoption.seguimiento.transition", ...)` con estado anterior
   y nuevo + operador.

## Out-of-scope

- Plantilla de documento de seguimiento (generación) — scope de DOC-02.
- Notificaciones automáticas al adoptante (email/SMS).
- Recordatorios automáticos de seguimiento pendiente.
- El contract de adopción en sí (generación y storage) — DOC-03.
