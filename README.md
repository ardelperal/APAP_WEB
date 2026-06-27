# APAP_WEB

Web application for APAP (Asociación para la Atención de Personas con Autismo y otros
Trastornos del Desarrollo), built on FastAPI + Tailwind v4 + PostgreSQL/InsForge.

## Stack

- **Backend**: FastAPI 0.137+, Pydantic 2.13+, async SQL via httpx.
- **Templates**: Jinja2 with `Jinja2Templates.TemplateResponse(request=...)`.
- **Frontend CSS**: Tailwind v4 (CSS-first, no `tailwind.config.js`).
- **Auth**: Google OAuth 2.0 with PKCE, session cookies signed via
  `itsdangerous.URLSafeTimedSerializer`.
- **Database**: InsForge (PostgREST-compatible PostgreSQL BaaS).

## Local development

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Run tests
pytest

# Run dev server
uvicorn app.main:app --reload
```

## Docker

Multi-stage build (Node 20 + Python 3.11 slim). Build:

```bash
docker build -t apap-web:dev .
docker run --rm -p 8000:8000 --env-file .env apap-web:dev
```

## Environment variables

| Key | Purpose |
| --- | --- |
| `APAP_INSFORGE_URL` | InsForge base URL (PostgREST). |
| `APAP_INSFORGE_SERVICE_KEY` | InsForge service key (server-side, never client-exposed). |
| `APAP_GOOGLE_CLIENT_ID` | Google OAuth client ID. |
| `APAP_GOOGLE_CLIENT_SECRET` | Google OAuth client secret. |
| `APAP_GOOGLE_REDIRECT_URI` | OAuth callback URL, must match Google console. |
| `APAP_SESSION_SECRET` | Symmetric key for session cookie signing. |
| `APAP_INITIAL_ADMIN_EMAIL` | Email pre-seeded in `authorized_users` on first boot. |

## Session secret rotation

Rotating `APAP_SESSION_SECRET` is the only mechanism that produces an
atomic, system-wide force-logout of every active user at once. The
flip of `payload.get("is_authorized", ...)` to `False` (PR-3 of
hardening-2026-q2, Rule 6 of `AGENTS.md`) closes the up-to-7-day
window where a deactivated user kept a valid session — but it does
NOT remediate pre-fix cookies already in flight. Those remain valid
until their max-age expires or until the secret is rotated.

For the full operator procedure — when to rotate, pre-deploy
checklist, Coolify steps, verification criteria, and rollback — see
[`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md).

## License

Proprietary. (c) APAP.
