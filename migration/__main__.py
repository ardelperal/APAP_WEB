"""Entry point para ``python -m migration``.

Este módulo existe para que el comando sea ejecutable desde la CLI sin
necesidad de un script shim. Delega en ``migration.cli``, cuyo
``build_parser`` expone los subcomandos actuales del ETL:
``reconcile``, ``apply`` (con ``--direction web-to-legacy`` para el
camino inverso de PR6/M2), ``status`` y ``ensure-bucket``.
"""

from __future__ import annotations

import sys

from migration.cli import main as cli_main


def main() -> int:
    """Entry point. Delega al CLI con ``sys.argv[1:]``."""
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
