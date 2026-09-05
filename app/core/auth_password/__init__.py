"""Classic email/password auth slice (Phase 2 of self-host #641).

Three routes (POST /auth/login, /auth/forgot-password,
/auth/reset-password) on top of :class:`ClassicPasswordAuthPort`.
Wired into ``app.main.create_app`` via :func:`register_password_routes`.
"""
