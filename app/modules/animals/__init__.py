"""Animals feature module: routes for the basic CRUD (list, create, get, update, delete)."""

from app.modules.animals.service import get_animal_by_id

__all__ = ["get_animal_by_id"]
