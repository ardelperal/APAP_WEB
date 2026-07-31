# Spec: LIFECYCLE — Búsqueda de Animales con Filtros (issue #30, task 3.2)

## Context

Issue #30. Endpoint de búsqueda de animales con filtros parametrizados por chip,
nombre, especie, sexo, estado y rango de fechas. La búsqueda debe ser exacta
para chip y substring para nombre (case-insensitive).

## Current state on main@0ab533d

**Ya existe:**
- Tabla `animals` con columnas `chip`, `nombre`, `especie`, `sexo`, `fecha_nacimiento`,
  `fecha_alta`, `fecha_baja`, `activo`.
- Ruta `GET /animales` (listado paginado sin filtros avanzados).

**Falta:**
- Filtros por estado (8 estados derivados), especie (CANINA/FELINA), chip (exact/partial),
  nombre (case-insensitive substring), sexo (Macho/Hembra), rango de fechas
  (fecha_nacimiento, fecha_alta).

## Required contract

### Endpoint

```
GET /animales?q=<nombre>&chip=<chip>&especie=<especie>&sexo=<sexo>
       &estado=<estado>&fecha_alta_since=<date>&fecha_alta_until=<date>
       &limit=<n>&offset=<n>
```

### Query parameters

| Parameter | Type | Behavior |
|-----------|------|----------|
| `q` | string | Substring match case-insensitive en `nombre`. Si chip exacto, buscar en `chip` también. |
| `chip` | string | Exact match en `chip`. Si se proporciona, ignora `q`. |
| `especie` | CANINA \| FELINA | Exact match. |
| `sexo` | Macho \| Hembra | Exact match. |
| `estado` | pendiente_entrada \| pendiente_nueva_situacion \| albergue \| acogida \| adoptado \| entregado \| fallecido \| incoherente | Computado dinámicamente via `calculateAnimalState` (task 3.1). Requiere JOIN con entradas/acogidas/adopciones activas. |
| `fecha_alta_since` | ISO date | `fecha_alta >= value`. |
| `fecha_alta_until` | ISO date | `fecha_alta <= value`. |
| `limit` | int | Default 50, max 200. |
| `offset` | int | Pagination cursor. |

### Response

```json
{
  "data": [
    {
      "id": "uuid",
      "chip": "123456789012345",
      "nombre": "Luna",
      "especie": "FELINA",
      "sexo": "Hembra",
      "estado": "ALBERGUE",
      "fecha_nacimiento": "2023-05-01",
      "fecha_alta": "2024-01-15"
    }
  ],
  "total": 123,
  "limit": 50,
  "offset": 0
}
```

### Ordering

Default: `fecha_alta DESC` (más recientes primero).

## Dependencies

- Task 3.1 (LIFECYCLE state resolver) — `calculateAnimalState()`.
- Tabla `animals` existente en schema.

## Acceptance criteria

1. `GET /animales` con `?chip=123` devuelve solo animales con chip exacto.
2. `GET /animales?q=luna` devuelve animales con "luna" en el nombre (case-insensitive).
3. `GET /animales?especie=CANINA` devuelve solo perros.
4. `GET /animales?estado=albergue` devuelve animales en estado Albergue.
5. `GET /animales?fecha_alta_since=2024-01-01&fecha_alta_until=2024-12-31` filtra por rango.
6. Combinación de filtros es AND.
7. Respuesta incluye `total` (sin paginar) para UI de "resultados encontrados".
8. `limit=0` devuelve solo `total` sin `data` (para count sin fetch).
9. Endpoint protegido con `require_authorized_user` (autenticado).

## Out-of-scope

- Búsqueda por DNI de propietario (no es un campo del animal).
- Filtros por rango de `fecha_nacimiento` (por ahora solo `fecha_alta`).
- Búsqueda difusa (fuzzy) de nombres — futuro, con `rapidfuzz` si hay demanda.
