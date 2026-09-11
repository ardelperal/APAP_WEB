#!/usr/bin/env python3
"""Create the ``apap-photos`` MinIO bucket.

Intended for CI use: reads ``MINIO_HOST_PORT``, ``S3_ACCESS_KEY``, and
``S3_SECRET_KEY`` from environment variables.

Usage::

    python scripts/create_minio_bucket.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from minio import Minio


def _pin_output_encoding() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _wait_for_minio_ready(host: str, *, timeout: int = 90) -> None:
    """Wait for MinIO to be ready to accept authenticated requests.

    The /minio/health/live endpoint is unauthenticated, but MinIO may
    still be initializing its auth layer after that check passes.  Retry
    the authenticated bucket_exists call until it succeeds or timeout.
    """
    _log = logging.getLogger(__name__)
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            # Try an unauthenticated probe first
            with urlopen(f"http://{host}/minio/health/live", timeout=2):
                pass
        except URLError:
            time.sleep(1)
            continue

        # Health endpoint OK — now try an authenticated call to confirm
        # auth is ready too.
        ready = False
        try:
            client = Minio(
                host,
                access_key=os.environ["S3_ACCESS_KEY"],
                secret_key=os.environ["S3_SECRET_KEY"],
                secure=False,
            )
            # A lightweight authenticated call — list buckets (returns empty list
            # or raises on auth failure).
            client.list_buckets()
            ready = True
        except Exception as exc:  # noqa: S110 — intentional retry-on-unknown-error
            _log.debug("MinIO auth probe failed: %s", exc)

        if ready:
            return  # MinIO is ready for authenticated operations
        time.sleep(1)

    # Last-ditch: show diagnostics
    _log.error("MinIO auth diagnostics:")
    _log.error("  host=%s", host)
    _log.error("  S3_ACCESS_KEY=%r", os.environ.get("S3_ACCESS_KEY", "<unset>"))
    _log.error("  S3_SECRET_KEY=<%d chars>", len(os.environ.get("S3_SECRET_KEY", "")))
    _log.error("  MINIO_HOST_PORT=%r", os.environ.get("MINIO_HOST_PORT", "<unset>"))
    raise MinioNotReadyError(timeout)


class MinioNotReadyError(Exception):
    """MinIO did not accept authenticated requests within the timeout."""

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        super().__init__(f"MinIO not ready after {timeout}s")


def main() -> None:
    _pin_output_encoding()
    host = os.environ["MINIO_HOST_PORT"]
    access_key = os.environ["S3_ACCESS_KEY"]
    secret_key = os.environ["S3_SECRET_KEY"]

    endpoint = f"127.0.0.1:{host}"

    print(f"Waiting for MinIO at {endpoint} to be ready...")
    print(f"  Credentials: access_key={access_key!r}")
    print(f"  MINIO_HOST_PORT={host!r}")
    _wait_for_minio_ready(endpoint)
    print("MinIO is ready for authenticated operations.")

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )

    bucket = "apap-photos"
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"Created bucket: {bucket}")
    else:
        print(f"Bucket already exists: {bucket}")


if __name__ == "__main__":
    main()
