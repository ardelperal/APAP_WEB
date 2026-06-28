"""Entry point para ``python -m migration``.

Este módulo existe para que el comando sea ejecutable desde la CLI sin
necesidad de un script shim. A partir de PR 1 de
``web-only-feature-preservation`` delega en ``migration.cli``
para soportar el subcomando ``reconcile`` con argparse. Los demás
subcomandos (``apply``, ``status``, ``init``) llegan en MIGRATION-01
PR 4/6 y se conectan al mismo ``build_parser``.
"""

from __future__ import annotations

import sys

from migration.cli import main as cli_main


def main() -> int:
    """Entry point. Delega al CLI con ``sys.argv[1:]``."""
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
