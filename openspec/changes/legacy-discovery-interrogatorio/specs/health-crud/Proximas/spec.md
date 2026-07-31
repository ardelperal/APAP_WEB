# Spec: HEALTH-04 — Listado de Próximas Pruebas / Recordatorios Sanitarios (issue #53, task 3.6)

## Context

Issue #53. Motor de recordatorios sanitarios: compute qué actuaciones están
próximas a vencer basándose en la periodicidad por especie y tipo de prueba.
Genera una lista de tareas pendientes para los operadores.

## Current state on main@0ab533d

**No existe** este feature. No hay tabla `TbPruebasPeridicidad` ni query que compute
próximas pruebas.

**Fuente:** `docs/discovery/feature-03-health-care.md` §3.5 ("Upcoming Health Tasks") +
`legacy-health-ui-workflow.md` §10.

## Required contract

### Periodicidad engine

El motor calcula:

```
próxima_fecha = última_fecha_de_ese_tipo + periodicidad_meses(Especie, Prueba)
```

Si `próxima_fecha <= hoy + 30_días` → la prueba aparece como "pendiente".

### Catalogo de periodicidad (tabla `catalogos_periodicidad`)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `prueba_nombre` | TEXT | Nombre de la prueba (fk a `catalogos_pruebas.nombre`) |
| `especie` | CANINA \| FELINA \| NULL | NULL = todas las especies |
| `periodicidad_meses` | INTEGER | Meses entre pruebas |
| `activo` | BOOLEAN | Activo/inactivo |

Seed inicial (del legacy `TbPruebasPeridicidad`):

| Prueba | Especie | Periodicidad |
|--------|---------|-------------|
| Vacuna Polivalente | CANINA | 12 meses |
| Rabia | CANINA | 12 meses |
| Leishmaniosis | CANINA | 12 meses |
| Desparasitación Interna | CANINA | 3 meses |
| Desparasitación Externa | CANINA | 3 meses |
| Vacuna Polivalente | FELINA | 12 meses |
| Rabia | FELINA | 12 meses |
| Esterilización | CANINA/FELINA | — (única, no recurrente) |

### Puppy tests (pruebas solo para perros < 8 meses)

Algunas pruebas (`Puppy test`) aplican solo a perros menores de 8 meses desde
`fecha_nacimiento`. Si `hoy - fecha_nacimiento > 8 meses` → excluir de la lista
de pendientes.

### Endpoint

```
GET /salud/proximas?especie=CANINA&limit=50&offset=0
```

### Response

```json
{
  "data": [
    {
      "animal_id": "uuid",
      "nchip": "123456789012345",
      "nombre": "Max",
      "especie": "CANINA",
      "prueba": "Desparasitación Interna",
      "ultima_fecha": "2024-01-10",
      "proxima_fecha": "2024-04-10",
      "dias_desde_ultima": 90,
      "esta_vencida": true,
      "dias_pendiente": -10
    }
  ],
  "total": 25
}
```

### Service function

```python
def list_proximas_pruebas(
    client: SqlExecutor,
    especie: Especie | None = None,
    limite_dias: int = 30
) -> list[ProximaPrueba]:
    """
    Lista animales con pruebas próximas a vencer (próxima_fecha <= hoy + limite_dias).
    Excluye animales con fecha_defuncion NOT NULL.
    Excluye puppy-only tests si animal > 8 meses.
    """
```

## Dependencies

- HEALTH-01 (#50) — tabla `actuaciones_sanitarias`.
- CATALOG-01 (#65) — catálogo de pruebas (`catalogos_pruebas`).

## Acceptance criteria

1. `GET /salud/proximas` lista pruebas pendientes ordenadas por `dias_pendiente` ASC.
2. `GET /salud/proximas?especie=CANINA` filtra por especie.
3. Animales muertos (`fecha_defuncion IS NOT NULL`) no aparecen.
4. Puppy tests excluidos si el animal tiene más de 8 meses.
5. Prueba sin registro previo (`ultima_fecha = NULL`) → aparece con `ultima_fecha = NULL`
   y `proxima_fecha = fecha_alta` (primera prueba al poco de entrar).
6. El campo `esta_vencida` es `true` si `dias_pendiente < 0`.
7. Endpoint protegido con `require_authorized_user`.

## Out-of-scope

- Generación automática de tareas en el motor de tareas (#7) — esto es solo
  el listado/query, no la creación de tareas.
- Notificaciones push/email a voluntarios.
- Batch de registro de pruebas múltiples — HEALTH-06 (#55).
