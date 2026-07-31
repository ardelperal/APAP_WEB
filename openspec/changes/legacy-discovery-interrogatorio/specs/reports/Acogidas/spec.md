# Spec: REPORT-03 — Informe de Acogidas (issue #62, task 3.8)

## Context

Issue #62. Informe de acogidas: lista de acogidas activas y finalizadas en un
período, con datos del animal, casa de acogida, voluntarios y duración.

## Current state on main@0ab533d

**Ya existe:**
- CRUD de casas de acogida (FOSTER-01, #43) y estancias (FOSTER-02, #44).
- Tablas `casas_acogida`, `acogidas`.

**Falta:** endpoint de informe agregado.

## Required contract

### Endpoint

```
GET /reportes/acogidas?fecha_desde=<date>&fecha_hasta=<date>&estado=activa&format=json
```

### Response (JSON)

```json
{
  "data": [
    {
      "id": "uuid",
      "fecha_inicio": "2024-03-01",
      "fecha_final": null,
      "estado": "activa",
      "animal": {
        "chip": "123456789012345",
        "nombre": "Luna",
        "especie": "FELINA"
      },
      "casa_acogida": {
        "id": "uuid",
        "nombre": "Casa García",
        "capacidad": 2,
        "ocupadas": 1
      },
      "voluntario_seguimiento_1": "María López",
      "voluntario_sanitario": "Carlos Ruiz",
      "tipo": "Temporal",
      "dias_activa": 45
    }
  ],
  "total": 12
}
```

### Filters

| Filter | Values | Behavior |
|--------|--------|----------|
| `fecha_desde`, `fecha_hasta` | date | Por `fecha_inicio` |
| `estado` | `activa` \| `finalizada` \| `todas` | Default `todas` |
| `casa_acogida_id` | UUID | Filtro por casa específica |

### Agregados

El informe también incluye agregados summaries:

```json
{
  "resumen": {
    "total_acogidas": 12,
    "activas": 5,
    "finalizadas": 7,
    "duracion_promedio_dias": 62.3,
    "por_casa": [
      {"casa": "Casa García", "activas": 3, "total_historico": 8}
    ]
  }
}
```

## Dependencies

- FOSTER-01 (#43) — `casas_acogida` table.
- FOSTER-02 (#44) — `acogidas` table.

## Acceptance criteria

1. `GET /reportes/acogidas?estado=activa` lista solo acogidas con `fecha_final IS NULL`.
2. `GET /reportes/acogidas?casa_acogida_id=<uuid>` filtra por casa.
3. `resumen.duracion_promedio_dias` computado solo sobre acogidas finalizadas.
4. `format=csv` y `format=pdf` disponibles.
5. Endpoint protegido con `require_authorized_user`.

## Out-of-scope

- Occupancy forecast por casa.
- Ranking de casas por acogidas completadas.
