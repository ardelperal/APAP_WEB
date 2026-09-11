#!/usr/bin/env python3
"""Create the ``apap-photos`` MinIO bucket.

Intended for CI use: reads ``MINIO_HOST_PORT``, ``S3_ACCESS_KEY``, and
``S3_SECRET_KEY`` from environment variables.

Usage::

    python scripts/create_minio_bucket.py
"""
from __future__ import annotations

import os
import sys

from minio import Minio


def main() -> None:
    host = os.environ["MINIO_HOST_PORT"]
    access_key = os.environ["S3_ACCESS_KEY"]
    secret_key = os.environ["S3_SECRET_KEY"]

    endpoint = f"127.0.0.1:{host}"
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
