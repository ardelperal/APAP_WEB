# Spec: REPORT-04 — Informe Sanitario (issue #63, task 3.8)

## Context

Issue #63. Informe sanitario agregado: estadísticas de actuaciones sanitarias
realizadas en un período, por tipo de prueba y especie.

## Current state on main@0ab533d

**Ya existe:**
- HEALTH-01 (#50) — tabla `actuaciones_sanitarias` con datos.
- HEALTH-02 (#51) — batch API.

**Falta:** endpoint de informe agregado sanitario.

**Fuente:** `docs/discovery/feature-03-health-care.md` §3.5 ("Upcoming Health Tasks") +
`legacy-health-ui-workflow.md` §10.

## Required contract

### Endpoint

```
GET /reportes/sanidad?fecha_desde=<date>&fecha_hasta=<date>&format=json
```

### Response (JSON)

```json
{
  "periodo": {
    "fecha_desde": "2024-01-01",
    "fecha_hasta": "2024-06-30"
  },
  "resumen": {
    "total_actuaciones": 145,
    "por_especie": {
      "CANINA": 95,
      "FELINA": 50
    }
  },
  "por_tipo": [
    {
      "tipo": "Vacuna",
      "total": 60,
      "CANINA": 40,
      "FELINA": 20,
      "ultima_fecha_max": "2024-06-15"
    },
    {
      "tipo": "Desparasitación",
      "total": 55,
      "CANINA": 35,
      "FELINA": 20,
      "ultima_fecha_max": "2024-06-10"
    },
    {
      "tipo": "Analítica",
      "total": 20,
      "CANINA": 15,
      "FELINA": 5,
      "ultima_fecha_max": "2024-05-20"
    },
    {
      "tipo": "Esterilización",
      "total": 10,
      "CANINA": 5,
      "FELINA": 5,
      "ultima_fecha_max": "2024-04-30"
    }
  ],
  "positivos": [
    {
      "tipo": "Analítica",
      "prueba": "Leishmaniosis",
      "resultado": "Positivo",
      "count": 3,
      "animal_chip": "123456789012345",
      "fecha": "2024-03-10"
    }
  ]
}
```

### Filters

| Filter | Behavior |
|--------|----------|
| `fecha_desde`, `fecha_hasta` | Por `fecha` de la actuación |
| `especie` | Filtrar por especie del animal |

### Resultados positivos

Sección `positivos`: listado de actuaciones con resultado containing "positivo"
o "Positivo" para facilitar el seguimiento clínico.

## Dependencies

- HEALTH-01 (#50) — `actuaciones_sanitarias` table.
- HEALTH-04 (#53) — periodicidad engine (para contexto de próximas pruebas).

## Acceptance criteria

1. `GET /reportes/sanidad` lista resumen agregado de actuaciones.
2. `GET /reportes/sanidad?fecha_desde=2024-01&fecha_hasta=2024-06` filtra por período.
3. `resumen.total_actuaciones` = SUM de todos los tipos.
4. `positivos` incluye solo registros con resultado conteniendo "positivo" (case-insensitive).
5. `format=csv` y `format=pdf` disponibles.
6. Endpoint protegido con `require_authorized_user`.

## Out-of-scope

- Comparativas con períodos anteriores (tendencia).
- Filtrado por voluntario que registró la actuación.
