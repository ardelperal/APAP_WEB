# D-20 — Stack base: FastAPI + HTMX + Jinja2 + InsForge

## Decision

El stack canónico de APAP_WEB es:

- **Backend**: FastAPI + Pydantic, sin ORM (DAO directo a InsForge vía HTTPX en [`app/core/insforge.py`](../../app/core/insforge.py)).
- **Frontend**: HTMX + Jinja2 server-rendered + Tailwind v4.
- **Backend BaaS**: InsForge (Postgres + auth + storage) — accedido desde Python, no desde el SDK TS (el proyecto no tiene `package.json`).
- **Auth**: Google OAuth vía InsForge (`exchange_insforge_oauth_code`) + allowlist en tabla `authorized_users`.
- **Despliegue**: Coolify + Dockerfile, webhook en `push` a `main` (ver D-30).

Detalle completo en [`architecture-insforge-stack.md`](../architecture-insforge-stack.md).

## Quick path

- FastAPI + HTMX + Jinja2 + InsForge = stack aceptado.
- Backend sin ORM; DAO directo a InsForge.
- Sin frontend Node (`package.json` no existe).

## Problem statement

Sin un stack fijado, cada contribuidor introduce una nueva tecnología "porque es mejor", lo que genera fragmentación, fricción de onboarding y deuda de mantenimiento. El equipo es pequeño y la operativa diaria no tolera decisiones de stack tomadas PR a PR.

## Evidence and scope

- [`pyproject.toml`](../../pyproject.toml) fija las versiones pineadas: FastAPI 0.136.x, Pydantic 2.13.x, HTTPX 0.28.x, python-multipart 0.0.32.
- [`Dockerfile`](../../Dockerfile) produce el contenedor de despliegue.
- [`app/main.py`](../../app/main.py) es el entrypoint FastAPI.
- [`app/core/insforge.py`](../../app/core/insforge.py) es el cliente Python de InsForge.
- [`tailwindcss/`](../../tailwindcss/) contiene la configuración CSS-first de Tailwind v4.
- [`architecture-insforge-stack.md`](../architecture-insforge-stack.md) documenta el contrato de infra.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| FastAPI + HTMX + InsForge (aceptada) | Server-rendered; bajo acoplamiento; ecosistema Python. | Sin SPA; menos herramientas "modernas". |
| Django + DRF + PostgreSQL directo (rechazada) | Maduro; admin incluido. | ORM pesado; menos flexible para BaaS. |
| Next.js + Supabase (rechazada) | Frontend rico; realtime fácil. | Duplica stack (TS + Python); sin justificación para audiencia actual. |
| Rails + Hotwire (rechazada) | Similar a FastAPI + HTMX. | Ecosistema Ruby menos familiar para el equipo. |

## Goals

- Stack único y pineado; sin decisiones tomadas por PR individual.
- InsForge absorbe infra (Postgres, Auth, Storage) — el equipo no opera un Postgres propio.
- Tailwind CSS-first (v4) sin tooling Node complejo en el pipeline principal.

## Non-goals

- Reescribir el stack en una release futura.
- Adoptar un ORM sobre InsForge (se mantiene DAO directo).
- Introducir un frontend React/SPA por defecto.

## Non-negotiable invariants

- **Regla D-21**: CodeGraph es el read path principal.
- **Regla D-30**: pre-MVP single branch (todo va a `main`).
- **Regla D-37**: identificadores técnicos en inglés.

## Consequences

- [`pyproject.toml`](../../pyproject.toml) está pineado; actualizar versiones requiere PR explícito.
- El deploy va por Coolify con webhook en `push` a `main` (ver [`Dockerfile`](../../Dockerfile) + Coolify `apap-web`).
- Sin `package.json` en la raíz; Tailwind vive en [`tailwindcss/`](../../tailwindcss/) como subproyecto.
- Las variables de entorno de InsForge se configuran en Coolify, nunca en el repo.

## When this changes

- Si InsForge deja de cubrir una capacidad crítica (auth, storage), se evalúa un reemplazo BaaS.
- Si el equipo crece y necesita un frontend con más estado cliente, se abre D-STACK-02 con la justificación.