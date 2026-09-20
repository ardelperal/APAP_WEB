# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""Deliberately broken domain module. Every import below must be reported by check_layers.py."""

import fastapi  # purity:domain — a pure layer must not touch a framework

from app.expedientes.domain import Expediente  # slice:lanzadera->expedientes
from app.lanzadera.adapters.repo import UserRepo  # direction:domain->adapters


class User:
    def __init__(self, repo: UserRepo, expediente: Expediente, app: fastapi.FastAPI) -> None:
        self.repo = repo
        self.expediente = expediente
        self.app = app
