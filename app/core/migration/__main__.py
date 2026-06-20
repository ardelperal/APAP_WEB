"""Entry point para ``python -m app.core.migration``.

Este módulo existe para que el comando sea ejecutable desde la CLI sin
necesidad de un script shim. La implementación completa del CLI
(argparse, subcomandos, exit codes) llega en un slice posterior; por
ahora simplemente imprime un placeholder y sale con código 0, lo
suficiente para que ``python -m app.core.migration`` funcione como
smoke test de que el módulo está bien instalado.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Entry point mínimo. Devuelve 0 para que ``python -m ...`` no falle."""
    sys.stderr.write(
        "apap-migrate: skeleton listo. CLI completa llega en un slice posterior.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
