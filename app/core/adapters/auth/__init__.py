"""Auth adapters (Phase 2: classic email/password).

The :class:`InsForgeAuthUsersAdapter` is the canonical ``AuthUsersPort``
implementation (M0/M1 work, in ``app.core.adapters.insforge``). Phase 2
adds the :class:`ClassicPasswordAuthPort` here as a small
``Argon2``-powered extension that supersedes ``InsForgeAuthUsersAdapter``
when ``APAP_AUTH_MODE=password`` (the route layer picks which port to
mount based on that env).
"""
