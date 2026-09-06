"""Backward-compatibility shim for the auth-dependencies slice.

The implementation lives in :mod:`app.core.di.auth_dependencies_di`.
This shim re-exports the 9 public symbols plus ``log_safe`` and
``read_session_payload`` so the ~35 consumer files
(``app/core/admin_handlers.py``, ``app/core/auth_flow.py``,
``app/core/rbac.py``, every ``app/modules/*/routes.py`` and
``batch_routes.py``, and 16 ``tests/test_*.py`` files) keep working
without edits.

The two helpers are re-exported here because tests in
:mod:`tests.test_auth_dependencies` monkeypatch
``app.core.auth_dependencies.log_safe`` /
``.read_session_payload``. The di module looks them up through
``_shim().<name>`` at call time (see
:func:`app.core.di.auth_dependencies_di._shim` for the lazy-import
rationale — it removes the module-level DI↔shim cycle and the
order-dependent consumer import failure that came with it).

Epic #420, slice #420-7. Locked decisions live in engram
``sdd/auth-dependencies/decisions``. See
:mod:`app.core.di.auth_dependencies_di` for the docstrings,
signatures, the §32.P4 fix, and the fresh-process regression test.
"""

from app.core.di.auth_dependencies_di import *  # noqa: F401,F403
from app.core.di.local_postgres_di import (  # noqa: F401  - re-export so the ~35 consumer files
    # modules that switched to ``get_local_postgres_executor_dep``
    # in this InsForge deprecation migration do not have to import
    # from the di subpackage directly.
    get_local_postgres_executor_dep,
)
from app.core.logging import log_safe  # noqa: F401
from app.core.session import read_session_payload  # noqa: F401
