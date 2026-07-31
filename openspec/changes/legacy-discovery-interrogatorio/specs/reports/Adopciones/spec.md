# Spec: REPORT-02 — Informe de Adopciones (issue #61, task 3.8)

## Context

Issue #61. Informe de adopciones: lista de adopciones en un período dado,
con datos del animal, adoptante, seguimiento y estado.

## Current state on main@0ab533d

**No existe** este feature. El módulo `adopciones` (ADOPT-01, #47) existe
pero no hay endpoint de informe agregado.

**Fuente:** `docs/discovery/feature-02-intake-foster-adoption.md` §2.3.

## Required contract

### Endpoint

```
GET /reportes/adopciones?fecha_desde=<date>&fecha_hasta=<date>&especie=CANINA&format=json
```

### Response (JSON)

```json
{
  "data": [
    {
      "id": "uuid",
      "fecha_adopcion": "2024-05-10",
      "animal": {
        "id": "uuid",
        "chip": "123456789012345",
        "nombre": "Max",
        "especie": "CANINA",
        "sexo": "Macho"
      },
      "adoptante": {
        "nombre": "Juan García",
        "dni": "12345678A",
        "telefono": "600123456",
        "email": "juan@example.com"
      },
      "seguimiento_estado": "DOCUMENTO_ENTREGADO",
      "vacunas_al_dia": true,
      "esterilizado": false,
      "observaciones": "Pendiente esterilización"
    }
  ],
  "total": 8
}
```

### Filters

| Filter | Behavior |
|--------|----------|
| `fecha_desde`, `fecha_hasta` | Filtro por `fecha_adopcion` |
| `especie` | Exact match CANINA/FELINA |
| `seguimiento_estado` | Filtro por estado de seguimiento (PENDIENTE/DOCUMENTO_ENTREGADO/etc.) |

### Formato CSV

`GET /reportes/adopciones?...&format=csv` → descarga CSV con las mismas columnas.

## Dependencies

- ADOPT-01 (#47) — tabla `adopciones` existente.
- ADOPT-03 (#49) — estado de seguimiento post-adopción.

## Acceptance criteria

1. `GET /reportes/adopciones?fecha_desde=2024-01-01&fecha_hasta=2024-06-30` lista
   adopciones en ese período.
2. Combinación de filtros (fecha + especie + seguimiento) es AND.
3. `format=csv` retorna CSV descargable.
4. `format=pdf` retorna PDF con el informe.
5. `fecha_desde` o `fecha_hasta` omitidos → usa todo el histórico.
6. Endpoint protegido con `require_authorized_user`.

## Out-of-scope

- Comparativas con períodos anteriores.
- Filtrado por voluntario de seguimiento.
