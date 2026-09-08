-- VOL-04 (#37) — add volunteer foreign-key columns to adopciones/acogidas.
-- PostgreSQL does not support ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS,
-- so every constraint is guarded through pg_constraint in an idempotent block.

ALTER TABLE adopciones
    ADD COLUMN IF NOT EXISTS responsable_adopcion_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'adopciones_responsable_adopcion_fk'
          AND conrelid = 'adopciones'::regclass
    ) THEN
        ALTER TABLE adopciones
            ADD CONSTRAINT adopciones_responsable_adopcion_fk
            FOREIGN KEY (responsable_adopcion_id) REFERENCES voluntarios(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

ALTER TABLE acogidas
    ADD COLUMN IF NOT EXISTS voluntario_acogida_id UUID;
ALTER TABLE acogidas
    ADD COLUMN IF NOT EXISTS voluntario_seguimiento2_id UUID;
ALTER TABLE acogidas
    ADD COLUMN IF NOT EXISTS voluntario_sanitario_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'acogidas_voluntario_acogida_fk'
          AND conrelid = 'acogidas'::regclass
    ) THEN
        ALTER TABLE acogidas
            ADD CONSTRAINT acogidas_voluntario_acogida_fk
            FOREIGN KEY (voluntario_acogida_id) REFERENCES voluntarios(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'acogidas_voluntario_seg2_fk'
          AND conrelid = 'acogidas'::regclass
    ) THEN
        ALTER TABLE acogidas
            ADD CONSTRAINT acogidas_voluntario_seg2_fk
            FOREIGN KEY (voluntario_seguimiento2_id) REFERENCES voluntarios(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'acogidas_voluntario_sanitario_fk'
          AND conrelid = 'acogidas'::regclass
    ) THEN
        ALTER TABLE acogidas
            ADD CONSTRAINT acogidas_voluntario_sanitario_fk
            FOREIGN KEY (voluntario_sanitario_id) REFERENCES voluntarios(id)
            ON DELETE SET NULL;
    END IF;
END
$$;
