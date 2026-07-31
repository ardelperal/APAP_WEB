# Spec: HEALTH-06 — Entrada Múltiple (Batch) de Actuaciones Sanitarias (issue #55, task 3.6)

## Context

Issue #55. Entrada por lote de actuaciones sanitarias: registrar la misma actuación
sanitaria (p.ej. vacuna) para múltiples animales en una sola operación.
Parallel al legacy `TbActuacionSanitariaAux` / `FormFichasSanitariasAsuntoAltaMultiple`.

## Current state on main@0ab533d

**Ya existe:**
- HEALTH-02 (#51) mergeado PR #322 (`f237c55`): batch API `POST /sanidad/actuaciones/batch`
  con staging preview + commit transaccional + D-24 per-record.
- HEALTH-01 (#50): CRUD básico de actuaciones sanitarias.

**Falta:**
- UI HTMX asociada al batch endpoint (form de selección múltiple de animales
  + preview + commit).
- Validación de puppy tests en batch ( HEALTH-04 future).

**Fuente:** `docs/discovery/feature-03-health-care.md` §9 ("Batch health action staging") +
`legacy-health-ui-workflow.md` §9.

## Required contract

### Flujo de batch

```
1. GET /sanidad/batch/new → Form de selección múltiple de animales + datos comunes
2. POST /sanidad/batch/preview → Validación D-24 por cada animal, preview de errores
3. POST /sanidad/batch/confirm → Commit atómico de todos los registros
```

### Endpoint de preview

```
POST /sanidad/actuaciones/batch/preview
Body: {
  "animal_ids": ["uuid1", "uuid2", "uuid3"],
  "fecha": "2024-06-15",
  "tipo_actuacion_id": "uuid",
  "descripcion": "Vacuna Polivalente",
  "resultado": "Correcto",
  "producto": "Nobivac",
  "lote": "L12345",
  "veterinario": "Dr. García"
}
```

### Response de preview

```json
{
  "valid_records": [
    {"animal_id": "uuid1", "chip": "123", "ok": true},
    {"animal_id": "uuid2", "chip": "456", "ok": true}
  ],
  "invalid_records": [
    {
      "animal_id": "uuid3",
      "chip": "789",
      "ok": false,
      "error": "fecha anterior al alta del animal (2023-01-15)"
    }
  ],
  "can_commit": false
}
```

### Endpoint de commit

```
POST /sanidad/actuaciones/batch
Body: { (same as preview) }
```

La diferencia es que `batch` ejecuta el INSERT atómico dentro de una transacción
PostgreSQL. Si cualquier registro falla, todos se revierten.

El endpoint `POST /sanidad/actuaciones/batch` (YA EXISTE en main@0ab533d,
PR #322) implementa este flujo. Esta spec documenta la UI HTMX asociada.

### D-24 en batch

> La validación D-24 se aplica por cada registro individual en el batch.
> Si un animal tiene fecha_alta NULL (legacy), la regla 3 se omite para ese animal.
> (Misma lógica que en HEALTH-01 individual.)

## Dependencies

- HEALTH-01 (#50) — `actuaciones_sanitarias` tabla.
- HEALTH-02 (#51) — `POST /sanidad/actuaciones/batch` endpoint ya existe.
- HEALTH-04 (#53) — periodicidad engine (para filtrar puppy tests en preview).

## Acceptance criteria

1. `GET /sanidad/batch/new` renderiza formulario con: selector de animales
   (checkbox list), campos comunes (fecha, tipo, resultado, producto, lote, veterinario).
2. `POST /sanidad/batch/preview` aplica D-24 a cada animal y retorna preview
   con errors específicos por animal.
3. `POST /sanidad/batch/preview` retorna `can_commit: false` si hay errores,
   permitiendo al usuario corregir.
4. `POST /sanidad/batch` commit atómico: todos los registros INSERT o ninguno.
5. Si `animal_ids` está vacío → 422.
6. Todos los endpoints protegidos con `require_writer_user`.
7. CSRF token en el formulario.
8. Logs via `log_safe("sanidad.batch.preview", ...)` y
   `log_safe("sanidad.batch.committed", record_count=N, ...)` con campos no sensibles.

## Out-of-scope

- Generación de recordatorios en el motor de tareas (#7) desde el batch.
- Adjuntar documentos (certificados veterinarios) a los registros del batch.
- Validación de duplicados por fecha+tipo+animal en el batch preview.
