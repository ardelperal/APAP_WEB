#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/policy_time.py
"""Explicit, validated policy time shared by ratchet gates."""

from __future__ import annotations

import argparse
from datetime import date


class PolicyTimeError(ValueError):
    pass


def parse_policy_date(value: str) -> date:
    """Parse canonical YYYY-MM-DD without consulting the wall clock."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PolicyTimeError("policy date must be a valid YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise PolicyTimeError("policy date must use canonical YYYY-MM-DD format")
    return parsed


def add_policy_date_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--policy-date",
        required=True,
        type=parse_policy_date,
        metavar="YYYY-MM-DD",
        help="explicit policy evaluation date; recorded in every report",
    )
