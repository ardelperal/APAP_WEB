# Propuesta: FOSTER-01 — CRUD de casas de acogida

skill_resolution: paths-injected

## Intención

Issue #43 cierra el bloque FOSTER-01: modelar la entidad propia **Casa de Acogida** (legacy `TbAcogidaCasas`, verificado vía Dysflow `projectId=apap` el 2026-07-04, 21 columnas) separada de la estancia (`acogidas`, ya creada como tabla de Fase 5a). Esto desbloquea FOSTER-02 (estancias con FK a casa), FOSTER-03 (gate de especie + capacidad) y FOSTER-04 (asignación de material), y la operativa real de "asignar animal a casa disponible" sin obligar al operador a tocar la entidad temporal de estancia.

## Alcance

### Dentro
- Nueva tabla `casas_acogida` con columna 1:1 del legacy `TbAcogidaCasas` (21 campos legacy + 2 mejoras justificadas: `id` UUID PK estable y `capacidad` INTEGER positivo).
- Mapeo a nombres snake_case en español: `nombre`, `apellidos`, `dni_acogedor`, `calle`, `numero`, `piso`, `letra`, `localidad`, `provincia`, `cp`, `telefono`, `telefono2`, `email`, `vinculacion`, `caracteristicas`, `coche`, `especie_preferente`, `observaciones`, `capacidad`, `fecha_alta`, `fecha_baja`, `activo`, `updated_at`.
- Service `foster_service.py` con: `create_casa_acogida`, `list_casas_acogida` (con filtro opcional por especie), `get_casa_acogida_by_id`, `update_casa_acogida`, `delete_casa_acogida` (soft-delete, mirror de INTAKE-01).
- Validación de especie preferente contra el enum legacy (`CANINA`, `FELINA` o NULL) — no se permite otro valor (P1 fidelidad).
- Validación de capacidad como entero positivo (mejora justificada — legacy no la tenía).
- Validación de `coche` contra el CHECK `('Sí', 'No')` con tildes preservados (mismo patrón que `cesiones_propietario`).
- Routes `foster_routes.py` (sub-router con `prefix="/casas-acogida"`): list, new, create, detail, edit, update, delete.
- Templates: `casas_acogida/list.html`, `casas_acogida/form.html` (compartido create/edit), `casas_acogida/detail.html`.
- Nav link "Casas de acogida" en `app/templates/base.html`.
- Tests TDD rojo→verde: 13+ atoms service (validation, soft-delete, search by species) + 12+ atoms routes (auth, CSRF, no SQL en routes).
- `docs/roadmap.md` refresca: quita #43 de §4 abiertas, añade a §5-bis cerradas con SHA.

### Fuera
- Estancia de acogida (FOSTER-02, #44) — depende de esta casa como FK.
- Gate de capacidad (FOSTER-03) y asignación de material (FOSTER-04) — pendientes de FOSTER-01 + FOSTER-02.
- Validación de capacidad contra estancias activas (queries cruzadas `casas_acogida` ↔ `acogidas`) — scope de FOSTER-03.
- Cálculo de estancia activa (`FFinal IS NULL`) — scope de FOSTER-02.
- Workflow judicial foster (variante `Acogida Judicial` con texto legal adicional) — scope de Fase 5b avanzada.

## Decisiones de producto

### D-FOSTER-01: Tabla propia `casas_acogida` separada de `acogidas`

Legacy tiene `TbAcogidaCasas` (casa) y `TbAcogidaAnimal` (estancia) como dos tablas separadas, lo que permite reusar la casa en N estancias. En la nueva app la tabla `acogidas` representa la estancia (creada en INTAKE-01, FOSTER-01 previo). Falta la casa: esta issue la crea con FK estable. P1 fidelidad: 1:1 con las 19 columnas de negocio de `TbAcogidaCasas` + 2 mejoras.

### D-FOSTER-02: Mejoras justificadas

- `id` UUID PK en vez de `IDAcogidaCasa` INT legacy: estable para FK desde `acogidas.casa_acogida_id` (que FOSTER-02 añadirá) y portable a LocalBackend/PostgREST.
- `capacidad` INTEGER NOT NULL CHECK (capacidad > 0): el legacy no tiene este campo pero la discovery 2.2 lo documenta explícitamente como regla de capacidad ("Current count = active foster stays, max capacity per foster home"). Sin esta columna no se puede implementar FOSTER-03. Documentado como gap P1.
- `coche` y los campos `Sí`/`No` con tildes: preservamos la tilde (mismo patrón que `cesiones_propietario`).
- `activo` BOOLEAN + `fecha_baja` TIMESTAMP: el patrón soft-delete del proyecto (mirror de `animales`, `voluntarios`, `entradas`). El legacy usa solo `FechaBaja`; web usa ambos para queries eficientes (`activo=true` vs `fecha_baja IS NULL`).

### D-FOSTER-03: Validación species + capacidad en servicio, no en ruta

Service owns SQL + validation. Routes traducen errores a HTTP 409/422. Sin SQL en `foster_routes.py` (regla layer boundaries AGENTS.md §1).

### D-FOSTER-04: Búsqueda por especie preferente en `list_casas_acogida`

El issue no lo pide explícitamente pero la discovery 2.2 indica que el operador necesita "buscar casas disponibles" por especie. Incluyo `list_casas_acogida(client, especie: str | None = None)` para no abrir una issue ad-hoc más adelante. Si la especie es None, devuelve todas las activas; si se pasa, filtra por `especie_preferente = $1 OR especie_preferente IS NULL` (casa "cualquier especie" cuenta como match — patrón conservador).

## Trazabilidad

- **Issue GitHub:** #43 (FOSTER-01).
- **SDD anterior:** INTAKE-01 (`openspec/changes/archive/2026-06-25-intake-entradas-crud/`) y INTAKE-02 (`openspec/changes/intake-batch-entradas-transaccional/`).
- **Discovery:** `docs/discovery/feature-02-intake-foster-adoption.md` §2.2 (Foster homes, Capacity validation, Evidence Source).
- **Legacy:** `TbAcogidaCasas` (verificado 2026-07-04 vía Dysflow `projectId=apap`, 21 columnas). Volumetría: 38 casas con estancias activas en producción, max 3 simultáneas.
- **P1 (fidelidad al legacy):** superset funcional — 1:1 con 19 columnas de negocio + 2 mejoras justificadas documentadas.
- **Decisiones de proyecto afectadas:** D-05 (fidelidad legacy), D-04 (paridad de campos), D-31 (workflow VBA via Dysflow).
- **Cierra con:** `docs(roadmap)` refresca + cierre #43 con SHA + test path.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| `coche` legacy es TEXT(2) y debe ser `Sí`/`No` con tilde — riesgo de mojibake | `CHECK (coche IN ('Sí', 'No'))` con tilde; tests service cubren happy/sad path |
| `capacidad` no existe en legacy (gap) | Mejora justificada D-FOSTER-02; documentación en `docs/architecture/decisiones-proyecto.md` si se considera novel (en este PR lo dejamos registrado en la propuesta y el SDD) |
| Volumetría pequeña (38 casas) — riesgo de sobre-diseño | Service mínimo, sin índices especiales ni triggers; PK es suficiente |
| Búsqueda por especie puede ser ambigua (`especie_preferente IS NULL` cuenta como match) | Documentado en D-FOSTER-04; tests cubren ambos casos |

## Criterios de aceptación

1. `POST /casas-acogida` con datos válidos → fila en `casas_acogida` con `id` UUID, redirect a `/casas-acogida/{id}`.
2. `POST /casas-acogida` con `especie_preferente` distinto a `CANINA`/`FELINA`/null → 422 con mensaje claro.
3. `POST /casas-acogida` con `capacidad <= 0` o no entero → 422.
4. `POST /casas-acogida` con `coche` distinto a `Sí`/`No` → 422.
5. `POST /casas-acogida` sin `nombre` o `apellidos` o `calle` o `telefono` → 422.
6. `GET /casas-acogida` lista casas activas con su `capacidad` y `especie_preferente` (no exponer campos sensibles en logs).
7. `GET /casas-acogida?especie=CANINA` filtra por especie preferente (incluye casas con `especie_preferente IS NULL`).
8. `POST /casas-acogida/{id}/delete` → soft-delete (`activo = false`, `fecha_baja = now()`), redirect a `/casas-acogida`.
9. Tests service: 13+ atoms cubriendo happy path, sad path por campo, soft-delete, búsqueda con/sin especie.
10. Tests routes: 12+ atoms cubriendo auth guard en 5 endpoints, CSRF en 3 forms, ausencia de SQL en routes.
11. `log_safe` para todo evento de foster (create, update, delete) con campos no sensibles.
12. Castellano, sin jerga, en templates y mensajes.