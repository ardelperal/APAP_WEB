"""Mock auth_dependencies for detector14 fixture."""

from typing import Any, Protocol

from starlette.responses import Response


# Minimal mock of the auth dependencies to make the fixture self-contained.
class require_authorized_user(Protocol):
    def __call__(self, user: Any) -> Response | dict: ...


class require_writer_user(Protocol):
    def __call__(self, user: Any) -> Response | dict: ...


class require_developer_user(Protocol):
    def __call__(self, user: Any) -> Response | dict: ...
