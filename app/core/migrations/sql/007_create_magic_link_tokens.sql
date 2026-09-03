-- M1 -- magic-link self-host auth (spec R3).
--
-- Idempotent: ``CREATE TABLE IF NOT EXISTS`` allows the adapter's
-- ``_ensure_schema`` to run on every connection without erroring on an
-- already-migrated database.
--
-- The table stores the persisted state of every magic-link request
-- issued by ``PostgresMagicLinkAdapter``. ``token_hash`` is the SHA-256
-- hex digest of the raw token; the raw token is NEVER persisted (the
-- transport delivers it out-of-band; only its hash reaches the table).
--
-- Columns:
--   email         TEXT NOT NULL
--                       — canonical email the link was issued for; the
--                         adapter revokes previous unconsumed rows for
--                         the same email on a new request.
--   token_hash    TEXT PRIMARY KEY
--                       — SHA-256 hex digest of the raw token; unique by
--                         construction (random 32-byte input).
--   requested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
--                       — row creation time.
--   expires_at    TIMESTAMPTZ NOT NULL
--                       — ``requested_at + ttl_seconds``; consume rejects
--                         rows where ``expires_at <= now()``.
--   consumed_at   TIMESTAMPTZ NULL
--                       — set to ``now()`` on first valid consume; the
--                         single-statement
--                         ``UPDATE ... RETURNING email`` is the
--                         atomicity boundary that prevents double-spend.
--
-- The partial index speeds up the per-request previous-row revoke
-- (``WHERE email = %s AND consumed_at IS NULL``) and the consume path
-- (``WHERE token_hash = %s AND consumed_at IS NULL``), which both
-- filter on the same partial predicate.

CREATE TABLE IF NOT EXISTS magic_link_tokens (
    email        TEXT NOT NULL,
    token_hash   TEXT PRIMARY KEY,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    consumed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS magic_link_tokens_email_open_idx
    ON magic_link_tokens(email)
    WHERE consumed_at IS NULL;
