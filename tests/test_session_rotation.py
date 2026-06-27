"""Regression test for SESSION_SECRET rotation (PR-3 of hardening-2026-q2).

Spec REQ-2 mandates that rotating APAP_SESSION_SECRET invalidates every
cookie signed with the previous secret. The mechanism is mechanical:
itsdangerous uses the secret in the HMAC, so a different secret produces
a different signature and read_session returns None. This file pins that
property at the unit level so the operator runbook keeps working.
"""

from __future__ import annotations

from app.core.session import read_session, write_session


def test_rotation_invalidates_old_cookies() -> None:
    """Cookie firmada con v1 lee None cuando se verifica con v2."""
    payload = {"email": "u@e.com", "rol": "key_user", "user_id": "u-1"}
    old = write_session(payload, secret="v1")
    assert read_session(old, secret="v1") == payload
    assert read_session(old, secret="v2") is None, (
        "rotar el secret debe invalidar todas las cookies previas "
        "(primitive que el runbook aprovecha para force-logout)"
    )


def test_rotation_is_reversible() -> None:
    """Revertir el secret restaura la verificacion de las cookies antiguas."""
    payload = {"email": "u@e.com", "rol": "key_user", "user_id": "u-1"}
    old = write_session(payload, secret="v1")
    assert read_session(old, secret="v2") is None
    assert read_session(old, secret="v1") == payload, (
        "rollback del secret restaura la verificacion; no hay perdida de datos"
    )


def test_rotation_invalidates_todas_las_cookies() -> None:
    """La rotacion invalida cookies CON y SIN el flag is_authorized."""
    with_flag = write_session(
        {"email": "u@e.com", "rol": "key_user", "is_authorized": True}, secret="v1"
    )
    without_flag = write_session(
        {"email": "u@e.com", "rol": "key_user"}, secret="v1"
    )
    assert read_session(with_flag, secret="v2") is None
    assert read_session(without_flag, secret="v2") is None, (
        "un solo cambio de secret invalida TODO (no distingue por payload)"
    )
