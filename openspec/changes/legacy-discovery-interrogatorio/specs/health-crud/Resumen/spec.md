# Spec: HEALTH-03 — Resumen de Última Prueba por Tipo (issue #52, task 3.6)

## Context

Issue #52. Panel "Salud" de la ficha animal: vista resumen que muestra la última
actuación sanitaria de cada tipo (vacuna, desparasitación, analítica, esterilización)
para un animal, con fecha y resultado.

## Current state on main@0ab533d

**Ya existe:**
- Tabla `actuaciones_sanitarias` (HEALTH-01, #50) mergeada PR #322 (`f237c55`).
- Endpoint `GET /sanidad?animal_id=<uuid>` lista actuaciones.
- Servicio `list_actuaciones_sanitarias`, `get_actuacion_sanitaria_by_id`.
- `GET /sanidad/{id}` con detalle de una actuación.

**Falta:**
- Endpoint `GET /animales/{nchip}/salud/resumen` que retorne la última actuación
  de cada tipo.
- Servicio `get_resumen_sanitario(animal_id)` que compute el resumen.

**Fuente:** `docs/discovery/feature-03-health-care.md` §3.2 ("Health Summary").

## Required contract

### Endpoint

```
GET /animales/{animal_id}/salud/resumen
```

### Response

```json
{
  "animal_id": "uuid",
  "nchip": "123456789012345",
  "resumen": [
    {
      "tipo": "Vacuna",
      "ultima_fecha": "2024-03-15",
      "ultimo_resultado": "Correcto",
      "ultima_descripcion": "Polivalente",
      "producto": "Nobivac"
    },
    {
      "tipo": "Desparasitación",
      "ultima_fecha": "2024-01-10",
      "ultimo_resultado": "Correcto",
      "ultima_descripcion": "Desparasitación Interna",
      "producto": "Milbemax"
    },
    {
      "tipo": "Analítica",
      "ultima_fecha": "2023-11-20",
      "ultimo_resultado": "Negativo",
      "ultima_descripcion": "Leishmaniosis",
      "producto": null
    }
  ]
}
```

### Service function

```python
def get_resumen_sanitario(client: SqlExecutor, animal_id: UUID)
    -> SaludResumen:
    """
    Para cada tipo de ActuacionSanitaria (agrupado por tipo de prueba):
    retorna la más reciente (MAX(fecha)) con su resultado y descripción.
    """
```

### Tipos cubiertos

Los tipos se derivan de `catalogos_pruebas.tipo` (vacuna, analítica, desparasitación,
esterilización, otras). Si no hay ningún registro de un tipo, ese tipo no aparece
en el resumen (no null rows).

## Dependencies

- HEALTH-01 (#50) — tabla `actuaciones_sanitarias` ya existente.

## Acceptance criteria

1. `GET /animales/{id}/salud/resumen` retorna la última actuación de cada tipo.
2. Si no hay actuaciones registradas para ningún tipo → `resumen: []`.
3. Si solo hay actuaciones de 2 tipos → array con 2 elementos.
4. Los tipos sin registros no aparecen en el array (no null entries).
5. Endpoint protegido con `require_authorized_user`.

## Out-of-scope

- Próximas pruebas pendientes — HEALTH-04 (#53).
- CRUD de actuaciones — HEALTH-01 (#50) ya mergeado.
- Batch entry — HEALTH-06 (#55).
