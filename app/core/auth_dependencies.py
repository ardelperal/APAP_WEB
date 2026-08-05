"""Backward-compatibility shim for the auth-dependencies slice.

The actual implementation lives in :mod:`app.core.di.auth_dependencies_di`.
This shim re-exports the 9 public symbols plus the two helper
dependencies (``log_safe`` and ``read_session_payload``) so:

  - the 19 consumer files keep working without edits;
  - the existing tests that ``monkeypatch`` ``log_safe`` /
    ``read_session_payload`` on this module's namespace (e.g.
    ``tests/test_auth_dependencies.py``) keep seeing the patched
    version when the di module's functions reference the symbol
    through the shim at call time.

Why the helpers are re-exported here: the existing tests in
:mod:`tests.test_auth_dependencies` monkeypatch these names on
``app.core.auth_dependencies`` (the historical home of the deps,
locked by ``tests/test_auth_dependencies.py``). Without re-exporting
the helpers here, those monkeypatches would no longer affect the
di module's function calls, and the tests would fail without
modifying the test files (which the slice's refactor budget forbids).

The di module imports this shim as ``_shim`` and resolves
``log_safe`` / ``read_session_payload`` through ``_shim.<name>``
inside each function body — the lookup is at call time, so the
monkeypatch on the shim's module attribute is observed.

See :mod:`app.core.di.auth_dependencies_di` for the docstrings,
signatures, and the §32.P4 fix landing on this slice.

Epic #420, slice #420-7. Locked decisions live in engram
``sdd/auth-dependencies/decisions``.
"""

# Imports below are read at call time by the di module's functions
# (see the ``from app.core import auth_dependencies as _shim`` import in
# :mod:`app.core.di.auth_dependencies_di`). They MUST be imported BEFORE
# the ``import *`` from the di module so the shim's namespace carries
# both names when the di module's functions look them up.
from app.core.di.auth_dependencies_di import *  # noqa: F401,F403
from app.core.logging import log_safe  # noqa: F401
from app.core.session import read_session_payload  # noqa: F401
