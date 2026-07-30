"""Mock auth_dependencies for detector14 negative fixture."""

from typing import Any, Protocol

from starlette.responses import Response


class require_authorized_user(Protocol):
    def __call__(self, user: Any) -> Response | dict: ...


class require_writer_user(Protocol):
    def __call__(self, user: Any) -> Response | dict: ...


class require_developer_user(Protocol):
    def __call__(self, user: Any) -> Response | dict: ...


# AuthenticatedUser would be the proper type
class AuthenticatedUser(dict):
    """TypedDict substitute for fixture: has user_id and email keys."""
