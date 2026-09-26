# D-44 — Alcance de lectura de los roles legacy: mapeo explícito fail-closed

## Decision

A partir del merge del PR que cierra el issue #923 (epic #911, hallazgo A-11), `require_permission` deja de conceder un `read:*` genérico a cualquier rol fuera del enum `Role`. La rama legacy pasa a un mapeo explícito:

- `_LEGACY_READ_ROLES = {developer, key_user, reader}` reciben, cada uno, el conjunto literal de los 10 permisos de lectura vigentes (`_LEGACY_READ_MATRIX`). Cero impacto sobre los usuarios actuales verificado para los cuatro strings de rol canónicos que `VALID_ROLES` puede asignar (`developer`, `admin`, `key_user`, `reader`): es exactamente el acceso que tenían. Cualquier fila preexistente de `usuarios_autorizados` con un valor de `rol` no canónico pasa a fail-closed por diseño (comportamiento intencional de esta decisión; follow-up de saneamiento de datos pendiente).
- Cualquier otro string de rol no reconocido recibe 403 también en lecturas (fail-closed). Hasta este cambio, cualquier string desconocido pasaba el fallback de lectura.
- Las escrituras no cambian: `_LEGACY_WRITER_ROLES = {developer, admin, key_user}` sigue gobernando `write:*`/`delete:*`.

Un guard test de completitud de matriz falla si aparece un permiso de lectura nuevo sin decisión explícita para cada rol legacy, de modo que el alcance no vuelve a ampliarse en silencio.

Este ADR formaliza la decisión de producto tomada el 2026-09-26 (opción "Compatibilidad explícita" entre tres alternativas) y queda registrada en `decisiones-proyecto.md` como D-44.

## Quick path

Para conceder o restringir lectura a un rol legacy, edite `_LEGACY_READ_ROLES`/`_LEGACY_READ_MATRIX` en `app/core/rbac.py` y actualice el guard test de `tests/test_rbac.py`. No restaure el fallback `return payload` para roles desconocidos: el 403 fail-closed es parte del contrato. La condición de salida del modelo legacy sigue siendo la invariante de `docs/security/rbac-matrix.md`: migrar las sesiones legacy al enum nuevo antes de ampliar permisos.

## Problem statement

El fallback pre-RBAC (`app/core/rbac.py`, comentado como "Any authenticated role can read") concedía `read:*` a cualquier string de rol que no resolviera contra el enum `Role` — no solo a los tres roles legacy documentados. Cada permiso de lectura nuevo que entrara en la matriz ampliaba en silencio lo que veían esos roles, sin test que fijara el alcance ni fecha de retirada. Un `reader` legacy podía leer más que el rol nuevo más restringido (`voluntario` carece de 6 de los 10 permisos de lectura).

## Evidence and scope

- `app/core/rbac.py` (líneas 252-257 pre-cambio): el fallback eliminado por este cambio concedía lectura a cualquier rol no enum (over-permission más allá de los 3 legacy).
- `app/core/auth.py:78` y los usos reales de `VALID_ROLES` en `app/core/admin_handlers.py:86,134,165`: `VALID_ROLES` deriva del enum `Rol` (`app/core/roles.py`: developer, admin, key_user, reader) — el panel de administración solo puede asignar roles legacy, de modo que hoy todos los usuarios reales pasan por el fallback y las restricciones del enum nuevo (`voluntario`/`staff`) son inalcanzables en la práctica.
- `docs/security/rbac-matrix.md` §"Legacy Role Backward Compatibility": la lectura abierta era carry-over deliberado del modelo #144, con el invariante de salida ya declarado.
- Antecedente: #679 (bypass RBAC de `reader` sobre el chip) — la lectura abierta ya produjo una regresión real.
- Átomos de verificación: guard de completitud sobre la matriz real, demostración de detección sobre una matriz sintética, pins de los 3 roles × 10 lecturas, pins de `reader` → 403 en cada write, y pin de `ghost_role` → 403 en lectura.

## Options considered

### Opción A — Compatibilidad explícita (aceptada)

**A favor**: cero impacto sobre usuarios reales (todos son legacy hoy); elimina el over-permission de strings desconocidos; el guard test convierte cada futura ampliación de lectura en una decisión explícita y testeada.

**En contra**: mantiene dos modelos de rol coexistiendo; la ampliación de permisos exige tocar el mapeo.

### Opción B — Restrictivo: recortar `reader` (rechazada)

**A favor**: alinea a `reader` con `voluntario` (perdería salud, reportes, adopciones, acogidas, cesiones y casas).

**En contra**: restringe usuarios reales activos hoy; el número exacto de lectores afectados solo lo sabe la base de datos de producción y no se verificó; la matriz lo documentaba como comportamiento intencional.

### Opción C — Alinear con el enum nuevo (rechazada)

**A favor**: un solo modelo mental (developer→admin, key_user→staff, reader→voluntario).

**En contra**: mayor blast radius (cambia lo que ven usuarios reales hoy), exige migración de sesiones y no era reversible sin impacto.

## Goals

- Fail-closed: ningún rol desconocido obtiene lectura por accidente.
- Trazabilidad: cada permiso de lectura de cada rol legacy tiene una decisión explícita y testeada.
- Cero impacto sobre el acceso real vigente (verificado para los cuatro roles canónicos de `VALID_ROLES`; valores de `rol` no canónicos preexistentes pasan a fail-closed por diseño).

## Non-goals

- Migrar usuarios de roles legacy a roles del enum nuevo.
- Cambiar permisos de escritura o los mensajes 403 de la rama de escritura.
- Ajustar los umbrales o el mecanismo del rate limit.

## Non-negotiable invariants

- El mapeo legacy de lectura contiene solo permisos `read:*`; ningún permiso de escritura o gestión puede filtrarse por esa vía (pin test).
- Un string de rol fuera de `_LEGACY_READ_ROLES` ∪ `_LEGACY_WRITER_ROLES` ∪ enum `Role` recibe 403 en lectura y en escritura.
- Todo permiso de lectura nuevo exige decisión explícita por rol legacy antes de fusionarse (guard test). El guard clasifica el alcance de lectura por el prefijo `read:`: un permiso futuro con capacidad de lectura que no use ese prefijo sería denegado en silencio a los roles legacy en lugar de forzar la decisión — mantener la convención `read:` es parte del contrato.

## Consequences

**Cambia**: un usuario con un `rol` tipográfico o desconocido en `usuarios_autorizados` pierde la lectura (antes la obtenía por el fallback); el fallo es visible y diagnosticable, no silencioso.

**Alcance del fail-closed**: rige solo para rutas protegidas con `require_permission`. Las rutas que dependen únicamente de `require_authorized_user` validan `is_authorized` pero no comprueban el valor del rol, de modo que ahí un rol desconocido no recibe 403 (gap preexistente, fuera del alcance de esta decisión; follow-up pendiente).

**Cambia**: añadir un `Permission` de lectura obliga a extender `_LEGACY_READ_MATRIX` o a decidir explícitamente que un rol legacy no lo recibe.

**No cambia**: el acceso real de `developer`, `key_user` y `reader` (los 10 reads y las escrituras de siempre), ni el comportamiento de los roles del enum nuevo.

## When this changes

- Cuando se migren las sesiones legacy al enum nuevo (invariante de salida de `docs/security/rbac-matrix.md`), este mapeo se retira y la matriz del enum queda como única fuente.
- Si el producto necesita restringir a `reader` (opción B), se reabre con conteo real de usuarios afectados y decisión documentada en este mismo archivo.
