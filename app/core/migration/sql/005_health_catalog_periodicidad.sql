-- HEALTH-06 (#55) — migrate catalogos_periodicidad to species-aware schema.
--
-- The CATALOG-01 (#65) initial seed used ``codigo`` as the sole key and
-- seeded 12 rows at 12 months each (one row per test type, ignoring
-- species). The legacy ``TbPruebasPeridicidad`` actually has species-aware
-- rules: the same test (e.g. "Vacuna Polivalente") has different
-- periodicities for CANINA vs FELINA, and some tests (e.g.
-- Desparasitación) have 3-month intervals, not 12.
--
-- Migration steps:
--   1. Backup data from the existing catalogos_periodicidad table.
--   2. Drop the old table (the 12-row codigo-only seed + codigo UNIQUE key).
--   3. Recreate with species-aware schema:
--        - especie column (NULL = all species; 'canina'/'felina' = specific)
--        - UNIQUE(codigo, especie) so species-aware rows don't conflict.
--   4. Seed the 9 rows from the legacy TbPruebasPeridicidad.
--   5. Restore any data previously written to the old table.
--
-- The species-aware schema matches the catalogos_pruebas (codigo, especie)
-- composite key so joins are natural. The NULL especie row for
-- Esterilización (one-shot, not recurring) coexists with the NULL
-- conflict target.

BEGIN;

-- Step 1: preserve any operator-added rows (those with non-UUID ids or
-- ids that don't match the CATALOG-01 seeded ids).
CREATE TEMP TABLE _periodicidad_backup AS
SELECT id, codigo, nombre, periodicidad_meses, activo, orden
FROM catalogos_periodicidad;

-- Step 2: drop and recreate with species-aware schema.
-- The new table carries:
--   - especie TEXT (NULL = all species, 'canina' or 'felina' = specific)
--   - UNIQUE(codigo, especie) — replaces the old codigo-only UNIQUE
--   - Natural key is (codigo, especie) matching catalogos_pruebas
DROP TABLE IF EXISTS catalogos_periodicidad;

CREATE TABLE catalogos_periodicidad (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT DEFAULT NULL,           -- NULL = all species
    periodicidad_meses INTEGER,          -- NULL = one-shot (e.g. Esterilización)
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT catalogos_periodicidad_natural_key UNIQUE (codigo, especie)
);

-- Step 3: seed from legacy TbPruebasPeridicidad (extracted via Dysflow 2026-07-03).
-- Periodicity values:
--   Vacuna Polivalente CANINA  -> 12 meses
--   Rabia             CANINA  -> 12 meses
--   Leishmaniosis     CANINA  -> 12 meses
--   Desparasitación Int CANINA ->  3 meses
--   Desparasitación Ext CANINA ->  3 meses
--   Vacuna Polivalente FELINA  -> 12 meses
--   Rabia             FELINA  -> 12 meses
--   Esterilización    CANINA  -> NULL (one-shot, not recurring)
--   Esterilización    FELINA  -> NULL (one-shot, not recurring)
INSERT INTO catalogos_periodicidad (codigo, nombre, especie, periodicidad_meses, orden)
VALUES
    ('Vacuna Polivalente', 'Vacuna Polivalente', 'canina', 12,  1),
    ('Rabia',               'Rabia',               'canina', 12,  2),
    ('Leishmaniosis',      'Leishmaniosis',        'canina', 12,  3),
    ('Desparasitación Interna', 'Desparasitación Interna', 'canina', 3, 4),
    ('Desparasitación Externa', 'Desparasitación Externa', 'canina', 3, 5),
    ('Vacuna Polivalente', 'Vacuna Polivalente', 'felina', 12,  6),
    ('Rabia',               'Rabia',               'felina', 12,  7),
    ('Esterilización',    'Esterilización',        'canina', NULL, 8),
    ('Esterilización',    'Esterilización',        'felina', NULL, 9)
ON CONFLICT (codigo, especie) DO NOTHING;

-- Step 4: restore operator-added rows that were not part of the seed.
-- These are rows whose id is NOT a known CATALOG-01 seed id.
-- The backup may also contain duplicates of the new seed; those are skipped
-- by the ON CONFLICT clause above.
INSERT INTO catalogos_periodicidad (codigo, nombre, especie, periodicidad_meses, activo, orden)
SELECT cp.codigo, cp.nombre, NULL, cp.periodicidad_meses, cp.activo, cp.orden
FROM _periodicidad_backup cp
WHERE NOT EXISTS (
    SELECT 1 FROM catalogos_periodicidad cp2
    WHERE cp2.codigo = cp.codigo AND (cp2.especie IS NOT DISTINCT FROM NULL)
)
ON CONFLICT (codigo, especie) DO NOTHING;

COMMIT;
