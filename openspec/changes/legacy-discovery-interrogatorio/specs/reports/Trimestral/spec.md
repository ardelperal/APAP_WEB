# Spec: REPORT-01 — Informe Trimestral (issue #60, task 3.8)

## Context

Issue #60. Informe trimestral de actividad de la protectora: censo actual de
animales por especie, movimientos del trimestre (entradas, acogidas, adopciones,
devoluciones, defunciones), desglosados por especie.

## Current state on main@0ab533d

**No existe** este feature. El legacy tiene un informe trimestral manual
(`FormProximosAsuntosSanitarios`) pero para salud, no para movimientos.

**Fuente:** `docs/discovery/feature-04-documents-contracts-reports.md` §4.5 ("Quarterly Report") +
`legacy-health-ui-workflow.md` §10.

## Required contract

### Endpoint

```
GET /reportes/trimestral?year=2024&quarter=2&format=json
GET /reportes/trimestral?year=2024&quarter=2&format=pdf
```

### Response (JSON)

```json
{
  "periodo": {
    "year": 2024,
    "quarter": 2,
    "fecha_desde": "2024-04-01",
    "fecha_hasta": "2024-06-30"
  },
  "censo": {
    "canina": {
      "total": 45,
      "albergue": 20,
      "acogida": 15,
      "adoptado": 8,
      "fallecido": 2
    },
    "felina": {
      "total": 30,
      "albergue": 18,
      "acogida": 8,
      "adoptado": 4,
      "fallecido": 0
    }
  },
  "movimientos": {
    "entradas": {"canina": 12, "felina": 8},
    "adopciones": {"canina": 5, "felina": 3},
    "devoluciones": {"canina": 1, "felina": 0},
    "acogidas_nuevas": {"canina": 7, "felina": 5},
    "acogidas_finalizadas": {"canina": 4, "felina": 3},
    "fallecidos": {"canina": 2, "felina": 0},
    "eutanasia": {"canina": 0, "felina": 0}
  },
  "notas": "Datos consolidados a fecha de generación"
}
```

### Cálculo de movimientos

| Concepto | Source table | Filter |
|----------|-------------|--------|
| Entradas | `entradas` | `fecha_entrada` dentro del trimestre |
| Adopciones | `adopciones` | `fecha_adopcion` dentro del trimestre |
| Devoluciones | `adopciones` | `fecha_devolucion` dentro del trimestre |
| Acogidas nuevas | `acogidas` | `fecha_inicio` dentro del trimestre |
| Acogidas finalizadas | `acogidas` | `fecha_final` dentro del trimestre |
| Fallecidos | `animals` | `fecha_defuncion` dentro del trimestre |
| Eutanasia | `animals` | `Eutanasia*` flags dentro del trimestre |

### Formato PDF

El endpoint con `format=pdf` retorna un documento PDF con el informe,
generado con `DocumentTemplateEngine` (DOC-02).

## Dependencies

- Task 3.1 (LIFECYCLE state resolver) — para compute de census por estado.
- DOC-02 (#57) — para generación de PDF.

## Acceptance criteria

1. `GET /reportes/trimestral?year=2024&quarter=2` retorna JSON con census y
   movimientos desglosados por especie.
2. Census muestra animales vivos (`fecha_defuncion IS NULL`) al final del trimestre.
3. Movimientos muestra solo los eventos que ocurrieron dentro del trimestre.
4. `GET /reportes/trimestral?...&format=pdf` retorna PDF generado.
5. Trimestre inválido (fuera de rango 1-4) → 422.
6. Endpoint protegido con `require_authorized_user`.

## Out-of-scope

- Histórico de trimestres anteriores (comparativas).
- Gráficos visuales en el PDF (texto y tablas sí).
- Envío automático del informe por email.
