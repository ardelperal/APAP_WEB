-- Issue #641 (M1, self-host-backend-coolify) — magic link tokens.
--
-- The magic link flow issues one-time tokens for passwordless login
-- and password reset. The raw token never touches persistent
-- storage: only its SHA-256 hash is stored, so a DB leak does not
-- expose live tokens.
--
-- Columns:
--   * ``token TEXT PRIMARY KEY`` — the SHA-256 hash of the raw
--     token. 64 chars hex.
--   * ``email TEXT NOT NULL`` — normalised to lower-case by the
--     application layer; the column is intentionally not UNIQUE
--     because a user may have multiple outstanding tokens at once.
--   * ``expires_at TIMESTAMPTZ NOT NULL`` — hard TTL (30 min by
--     default; configurable via the adapter).
--   * ``used_at TIMESTAMPTZ`` — NULL until the token is consumed.
--     Setting this is what makes the token one-time-use.
--   * ``created_at TIMESTAMPTZ NOT NULL DEFAULT now()`` — for the
--     admin panel ordering (most recent first).
--
-- Idempotent: ``CREATE TABLE IF NOT EXISTS`` is safe to re-run.

CREATE TABLE IF NOT EXISTS magic_link_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS magic_link_tokens_email_idx
    ON magic_link_tokens (email);

CREATE INDEX IF NOT EXISTS magic_link_tokens_expires_at_idx
    ON magic_link_tokens (expires_at);
