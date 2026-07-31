-- VOL-04 (#37) — añade columnas FK de voluntario a adopciones y acogidas.
--
-- Tabla legacy    | Campo legacy         | Nueva columna FK
-- ----------------|---------------------|------------------------------
-- TbAdopcion      | ResponsableAdopcion | adopciones.responsable_adopcion_id (optional)
-- TbAcogidaAnimal | VoluntarioAcogida   | acogidas.voluntario_acogida_id (optional)
-- TbAcogidaAnimal | VoluntarioSeguim…2  | acogidas.voluntario_seguimiento2_id (optional)
-- TbAcogidaAnimal | VoluntarioCosas…    | acogidas.volario_sanitario_id (required)
--
-- Patrón idempotente (mismo que 004 y 005):
-- ``ADD COLUMN IF NOT EXISTS`` permite re-ejecutar ``apply_sql_migrations``
-- sin fallar en una base que ya tenga la columna.
-- ``ADD CONSTRAINT IF NOT EXISTS`` para la FK.
--
-- Nota: TbEntradas.VoluntarioEntrada y TbTerapias.Voluntario ya tienen
-- sus columnas FK (voluntario_entrada_id, voluntario_id) — el trabajo
-- de esas tablas es ya existente; el servicio entradas ya persiste
-- voluntario_entrada_id y sanidad ya tiene voluntario_id en el schema.

-- 1. adopciones: añadir responsable_adopcion_id (optional FK → voluntarios.id)
ALTER TABLE adopciones
    ADD COLUMN IF NOT EXISTS responsable_adopcion_id UUID;

ALTER TABLE adopciones
    ADD CONSTRAINT IF NOT EXISTS adopciones_responsable_adopcion_fk
    FOREIGN KEY (responsable_adopcion_id) REFERENCES voluntarios(id)
    ON DELETE SET NULL;

-- 2. acogidas: añadir las tres columnas FK que faltan
--    (voluntario_seguimiento_1_id ya existe como FK — no tocarlo)
ALTER TABLE acogidas
    ADD COLUMN IF NOT EXISTS voluntario_acogida_id UUID;

ALTER TABLE acogidas
    ADD COLUMN IF NOT EXISTS voluntario_seguimiento2_id UUID;

ALTER TABLE acogidas
    ADD COLUMN IF NOT EXISTS voluntario_sanitario_id UUID;

-- FK constraints (opcionales: ON DELETE SET NULL para preservar datos legacy)
ALTER TABLE acogidas
    ADD CONSTRAINT IF NOT EXISTS acogidas_voluntario_acogida_fk
    FOREIGN KEY (voluntario_acogida_id) REFERENCES voluntarios(id)
    ON DELETE SET NULL;

ALTER TABLE acogidas
    ADD CONSTRAINT IF NOT EXISTS acogidas_voluntario_seg2_fk
    FOREIGN KEY (voluntario_seguimiento2_id) REFERENCES voluntarios(id)
    ON DELETE SET NULL;

ALTER TABLE acogidas
    ADD CONSTRAINT IF NOT EXISTS acogidas_voluntario_sanitario_fk
    FOREIGN KEY (voluntario_sanitario_id) REFERENCES voluntarios(id)
    ON DELETE SET NULL;
