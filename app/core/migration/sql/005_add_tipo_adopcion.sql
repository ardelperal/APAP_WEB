-- ADOPT-01 (#47) — añade la columna ``tipo_adopcion`` a ``adopciones``
-- con un CHECK enum de tres valores: regular (default), preadopcion,
-- judicial. Patrón idempotente (D-ADOPT-01, D-EST-05):
-- ``ADD COLUMN IF NOT EXISTS`` permite re-ejecutar ``apply_sql_migrations``
-- sin fallar en una base que ya tenga la columna.
--
-- El default 'regular' cubre el flujo común sin pedir campo extra al
-- operador; los tres valores están alineados con la discovery 2.3
-- (Adoption event lifecycle) y la rama legacy ``TbAdopcion`` que ya
-- distingue regular vs pre-adopción como campos separados.
ALTER TABLE adopciones
ADD COLUMN IF NOT EXISTS tipo_adopcion TEXT NOT NULL DEFAULT 'regular'
CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial'))