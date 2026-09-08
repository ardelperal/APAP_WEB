"""Coverage for ``migration.cli_ensure_bucket.run_ensure_bucket``.

Post-M0 (LocalBackend runtime), the bucket concept is retired; this
command is a backward-compat shim that keeps the operator-facing
``apap-migrate ensure-bucket`` output format stable while delegating to
``migration.bootstrap.check_private_bucket`` (see that function's
docstring for the retirement rationale). This module's only
responsibility left to test is: it calls the shim and formats the
result, unconditionally returning 0.
"""

from __future__ import annotations

import argparse
import io

from migration.cli import main
from migration.cli_ensure_bucket import run_ensure_bucket


def test_run_ensure_bucket_formats_the_shim_result_and_returns_zero() -> None:
    stream = io.StringIO()
    args = argparse.Namespace(bucket_name="apap-photos")

    rc = run_ensure_bucket(args, stream=stream)

    assert rc == 0
    output = stream.getvalue()
    assert "bucket=apap-photos" in output
    assert "isPublic=false" in output


def test_run_ensure_bucket_defaults_stream_to_stdout(capsys) -> None:
    args = argparse.Namespace(bucket_name="apap-photos")

    rc = run_ensure_bucket(args)

    assert rc == 0
    assert "bucket=apap-photos" in capsys.readouterr().out


def test_cli_main_dispatches_ensure_bucket(capsys) -> None:
    """``apap-migrate ensure-bucket <name>`` reaches run_ensure_bucket via main()."""
    rc = main(["ensure-bucket", "some-other-bucket"])

    assert rc == 0
    assert "bucket=some-other-bucket" in capsys.readouterr().out
