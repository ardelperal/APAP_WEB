-- M2 -- classic email/password auth (spec R1).
--
-- Idempotent: ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` is supported
-- by Postgres 9.6+. The applied-migrations table tracks which files have
-- run; re-running this slice is a no-op once ``applied=007_add_password_hash.sql``.
--
-- Columns:
--   password_hash           TEXT
--                                — argon2id-encoded password digest, NULL when the
--                                  user authenticates only via magic-link or
--                                  Google OAuth. NULL means "no password set" —
--                                  POST /auth/login returns 401 with
--                                  ``{"error":"invalid_credentials"}`` for that
--                                  user (spec AS2.4).
--   password_reset_token    TEXT
--                                — 32-byte URL-safe token, single-use, NULL when
--                                  no reset is pending. Always written together
--                                  with ``password_reset_expires_at``.
--   password_reset_expires_at TIMESTAMPTZ
--                                — ``now() + 30min`` when the token is minted.
--                                  POST /auth/reset-password rejects rows where
--                                  ``password_reset_expires_at <= now()``.
--
-- All three columns are nullable so existing magic-link / OAuth users are
-- unaffected (spec AS1.1 — "migration adds the column without breaking
-- existing rows").
ALTER TABLE usuarios_autorizados
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

ALTER TABLE usuarios_autorizados
    ADD COLUMN IF NOT EXISTS password_reset_token TEXT;

ALTER TABLE usuarios_autorizados
    ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMPTZ;
