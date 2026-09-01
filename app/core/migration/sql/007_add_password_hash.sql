-- Issue #641 (M1, self-host-backend-coolify) — classic email/password auth.
--
-- Adds three nullable columns to ``usuarios_autorizados``:
--
--   * ``password_hash TEXT`` — argon2id hash. ``NULL`` means the user
--     has no password set (OAuth-only user; classic login is
--     disabled for that user). The local ``ClassicPasswordAuthPort``
--     refuses to verify a NULL hash.
--
--   * ``email_verified_at TIMESTAMPTZ`` — set after the user confirms
--     their email via the magic link flow. Out of scope for M1
--     (enforcement); the column exists so the next epic that adds
--     email verification enforcement does not need a migration.
--
--   * ``failed_attempts INTEGER NOT NULL DEFAULT 0`` — counter for
--     future rate-limiting. Out of scope for M1 (enforcement); the
--     column exists so the next epic that adds rate limiting does
--     not need a migration.
--
-- Idempotent: ``ADD COLUMN IF NOT EXISTS`` is supported by Postgres
-- 9.6+, so the migration is safe to re-run on an already-migrated DB.

ALTER TABLE usuarios_autorizados
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

ALTER TABLE usuarios_autorizados
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

ALTER TABLE usuarios_autorizados
    ADD COLUMN IF NOT EXISTS failed_attempts INTEGER NOT NULL DEFAULT 0;
