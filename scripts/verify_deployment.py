"""Poll the deployed health endpoint until the expected revision is live."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

import httpx


def _pin_output_encoding() -> None:
    """Make verifier output independent from the runner locale."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def wait_for_revision(
    url: str,
    expected_revision: str,
    *,
    attempts: int = 30,
    interval_seconds: float = 10.0,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Return the healthy response or raise after a bounded retry window."""
    last_error = "no response"
    with httpx.Client(timeout=10.0, transport=transport) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                body = response.json()
                if body.get("status") != "ok":
                    last_error = f"health status is {body.get('status')!r}"
                elif body.get("revision") != expected_revision:
                    last_error = (
                        f"revision is {body.get('revision')!r}, expected "
                        f"{expected_revision!r}"
                    )
                else:
                    return body
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)

            if attempt < attempts:
                sleep(interval_seconds)

    raise RuntimeError(
        f"deployment did not expose revision {expected_revision!r} after "
        f"{attempts} attempts: {last_error}"
    )


def main() -> int:
    """Parse CLI arguments and verify the deployed revision."""
    _pin_output_encoding()
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()

    body = wait_for_revision(
        args.url,
        args.revision,
        attempts=args.attempts,
        interval_seconds=args.interval,
    )
    print(f"deployment verified: {body}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
