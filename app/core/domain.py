"""Domain schema bootstrap: animals, volunteers, volunteer_roles.

Source of truth for the SQL that creates the domain tables in the
InsForge backend. Mirrors the pattern in ``app.core.auth`` for
``authorized_users``: the SQL lives as a constant in Python so the
``CREATE TABLE`` definitions are versioned with the app, and the
``ensure_domain_schema`` function is the single entry point that
``app.main`` calls on startup.

The schema is intentionally minimal in this first slice (Fase 3,
schema-only): no triggers, no extra indices beyond what the constraints
imply, no related tables (animal_event_log, attachments) — those come in
later cycles (CRUD de animales, anexos via Storage bucket).
"""

from __future__ import annotations

from app.core.insforge import InsForgeClient

ANIMALS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chip_number TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    species TEXT NOT NULL CHECK (species IN ('CANINA', 'FELINA')),
    sex TEXT NOT NULL CHECK (sex IN ('M', 'H')),
    birth_date DATE,
    breed TEXT,
    is_mestizo BOOLEAN NOT NULL DEFAULT false,
    is_ppp BOOLEAN NOT NULL DEFAULT false,
    photo_url TEXT,
    has_chip_on_arrival BOOLEAN,
    chip_implant_date DATE,
    therapy_flag BOOLEAN NOT NULL DEFAULT false,
    death_date DATE,
    death_cause TEXT,
    euthanasia_type TEXT,
    ariac_notified BOOLEAN NOT NULL DEFAULT false,
    last_state_before_death TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

VOLUNTEERS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS volunteers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    dni TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

VOLUNTEER_ROLES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS volunteer_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    volunteer_id UUID NOT NULL REFERENCES volunteers(id),
    role_type TEXT NOT NULL CHECK (role_type IN ('intake', 'follow_up', 'foster_care', 'health')),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (volunteer_id, role_type)
)
"""


def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Order matters: ``volunteer_roles`` has a foreign key to
    ``volunteers``, so the parent table must be created first. ``animals``
    is independent of the other two and is created first for symmetry
    (most-frequently-written table at the top of the migration).
    """
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTEERS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTEER_ROLES_CREATE_TABLE_SQL)
