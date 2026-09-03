"""Magic-link self-host auth (M1).

Public surface:

- :class:`app.core.auth_magic.postgres_adapter.PostgresMagicLinkAdapter`
  — the local-backend persistence adapter (spec R1, R3).
- :class:`app.core.auth_magic.mail_transports.ConsoleMailTransport` —
  the dev/test transport that writes JSON lines to ``tests/mailbox.jsonl``
  (spec R2).
- :class:`app.core.auth_magic.mail_transports.SMTPMailTransport` — the
  M1.1 placeholder that raises :class:`NotImplementedError` until the
  real SMTP wiring lands.
- :func:`app.core.auth_magic.get_mail_transport.get_mail_transport` —
  process-scoped resolver that picks SMTP or console based on
  ``APAP_SMTP_HOST``.

F2 adds the FastAPI routes (``POST /auth/magic/start`` and
``GET /auth/magic/verify``) and the lifespan wiring. F1 ships only the
port contracts, the Postgres adapter, and the transport seam.
"""
