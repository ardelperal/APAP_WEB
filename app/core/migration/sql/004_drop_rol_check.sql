-- Migration 004: drop the redundant CHECK constraint on usuarios_autorizados.rol.
--
-- The CHECK duplicated the Rol(StrEnum) (Rule 4 — audit engram:14516).
-- App-level validation in add_authorized_user is now the sole gate;
-- the constraint would not auto-update if Rol grew. DROP CONSTRAINT
-- IF EXISTS makes this safe on databases where the constraint was
-- already removed by a previous deploy.
ALTER TABLE usuarios_autorizados
    DROP CONSTRAINT IF EXISTS usuarios_autorizados_rol_check;
