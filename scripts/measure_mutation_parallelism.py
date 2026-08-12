"""Operator-facing wall-clock measurement for the parallel cosmic-ray distributor (issue #545).

Runs a self-contained mutation session against the curated target set
in ``docs/quality/cosmic-ray.toml`` using the same ``http`` distributor
the CI mutation job now uses, prints how long the session took, and
tears everything down on exit. Sister script to
``scripts/cosmic_ray_run_config.py``: this one is the operator-facing
entry point; that one is the rendering helper the CI mutation step
uses.

Linux-only. cosmic-ray cannot execute mutants on native Windows (issue
#431, Finding 1) -- the script fails fast on any other platform rather
than letting ``cosmic-ray init`` produce a session whose 100 % of
mutants come back INCOMPETENT. Run on WSL or on the apap-coolify-noble
runner per ``docs/runbooks/mutation-testing.md``.

Use::

    python scripts/measure_mutation_parallelism.py

Exit code is 0 when the run finishes cleanly and the resulting session
passes ``is_session_healthy``'s check (INCOMPETENT < 20 %, no incomplete
jobs, at least one KILLED). Exit code 1 on any failure so CI can gate on
it.

The script does NOT update ``docs/quality/mutation-baseline.json``: that
file is only writable from the CI runner (per the ``PROVISIONAL`` header
in the baseline itself). What it does print is the wall-clock vs the
serial distributor's measured baseline (~3111 s on the same host, issue
#545 body), which is the read the issue body asks for.

Stdlib-only on top of the transitive ``toml`` dep already pulled in by
cosmic-ray; pulling in ``cosmic_ray`` itself at import time would
defeat the "ready to run" shape the operator expects.
"""
from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

# Local import is relative so the script works when invoked as
# ``python scripts/measure_mutation_parallelism.py`` from the repo root
# (the documented entry point per ``docs/runbooks/mutation-testing.md``).
# The `scripts/` directory is not a package on disk (no ``__init__.py``)
# so ``from scripts.cosmic_ray_run_config import ...`` would only work
# under pytest, which is not where this script is meant to be tested.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cosmic_ray_run_config import (  # noqa: E402 — sys.path tweak above
    DEFAULT_WORKER_COUNT,
    is_session_healthy,
    render_config,
    summarise_session,
)

#: Reference serial wall-clock in seconds for the speedup ratio. Default
#: matches the issue #545 body measurement (3111 s on the apap-coolify-noble
#: runner). Operator can override via ``--serial-baseline-s``.
DEFAULT_SERIAL_BASELINE_S = 3111.0


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _require_linux() -> None:
    """Fail fast on anything that isn't Linux; cosmic-ray cannot mutate there."""
    if sys.platform.startswith("linux"):
        return
    _eprint(
        f"FAIL: this script requires Linux (sys.platform={sys.platform!r}). "
        "cosmic-ray returns INCOMPETENT for 100 % of mutants on native "
        "Windows; cr-rate then reports a passing 0.00 anyway -- the exact "
        "false-green the mutation ratchet was written to catch "
        "(issue #431, Finding 1). On a Windows workstation use WSL per "
        "docs/runbooks/mutation-testing.md."
    )
    raise SystemExit(1)


def _spawn_workers_supervisor(
    rendered_config: Path,
    repo_root: Path,
    log_path: Path,
) -> subprocess.Popen[bytes]:
    """Background ``cr-http-workers``; it owns the worker lifecycle.

    The supervisor clones the repo (depth=1) per worker and starts a
    ``cosmic-ray http-worker --path <sock>`` inside each clone, so two
    workers mutating the same file do not race on disk. Killing the
    supervisor with SIGTERM cascades to the workers.

    Returns the Popen handle; caller is responsible for teardown.
    """
    log_fh = log_path.open("wb")
    # NEW_SESSION: the supervisor + its worker subtree get their own
    # process group, so an accidental Ctrl-C in the parent does not
    # orphan them -- teardown kills by explicit PID, not by signal
    # propagation that might miss a half-spawned worker.
    return subprocess.Popen(
        ["cr-http-workers", str(rendered_config), str(repo_root)],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop_workers_supervisor(proc: subprocess.Popen[bytes]) -> None:
    """Stop the supervisor; SIGTERM lets it clean up its worker children."""
    if proc.poll() is not None:
        _eprint(f"cr-http-workers: already exited (code {proc.returncode})")
        return
    try:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _eprint("cr-http-workers: did not exit on SIGTERM, sending SIGKILL")
            proc.kill()
            proc.wait(timeout=5)
    except ProcessLookupError:
        pass


def _run_cosmic_ray(
    cmd: Sequence[str],
    *,
    timeout_s: float = 60.0,
) -> int:
    """Run a cosmic-ray command and surface its exit code; fail loud on non-zero."""
    _eprint(f"$ {' '.join(cmd)}")
    completed = subprocess.run(cmd, check=False, timeout=timeout_s)
    if completed.returncode != 0:
        _eprint(
            f"FAIL: {' '.join(cmd[:2])} exited {completed.returncode}; "
            "see worker logs for the per-mutant error stream"
        )
    return completed.returncode


def _format_summary(
    workers_started: int,
    wall_clock_s: float,
    summary: dict[str, int],
    serial_baseline_s: float,
) -> str:
    total = summary["total"]
    incompetent = summary["incompetent"]
    survived = summary["survived"]
    killed = summary["killed"]
    speedup = serial_baseline_s / wall_clock_s if wall_clock_s > 0 else float("inf")
    ratio_incomp = incompetent / total if total else 0.0

    lines = [
        "",
        "=== cosmic-ray parallelism measurement (issue #545) ===",
        f"workers started:        {workers_started}",
        f"wall-clock:             {wall_clock_s:.1f} s",
        f"serial baseline:        {serial_baseline_s:.0f} s  (issue #545 body)",
        f"speedup:                {speedup:.2f}x",
        f"mutants measured:       {total}",
        f"killed:                 {killed}",
        f"survived:               {survived}",
        f"incompetent:            {incompetent}  ({ratio_incomp:.1%}; ceiling 20%)",
        "==========================================================",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _require_linux()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("docs/quality/cosmic-ray.toml"),
        help="Committed cosmic-ray.toml to drive the session. Defaults to the one in repo.",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Per-run temp directory for the rendered config + worker sockets. "
        "Defaults to a fresh tempfile.mkdtemp().",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=Path("measure-mutation.sqlite"),
        help="Where to write the cosmic-ray session database.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKER_COUNT,
        help="Number of workers to spawn. Default matches the 4 vCPU of the runner.",
    )
    parser.add_argument(
        "--serial-baseline-s",
        type=float,
        default=DEFAULT_SERIAL_BASELINE_S,
        help="Reference serial wall-clock in seconds for the speedup ratio. "
        "Default 3111 matches the issue #545 body measurement.",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Leave the session database on disk after the run for inspection.",
    )
    args = parser.parse_args(argv)

    config_path = args.config.resolve()
    if not config_path.exists():
        _eprint(f"FAIL: cosmic-ray config not found: {config_path}")
        return 1

    owns_run_dir = args.run_dir is None
    run_dir = (
        Path(tempfile.mkdtemp(prefix="cr-measure-"))
        if owns_run_dir
        else args.run_dir.resolve()
    )
    if not run_dir.is_dir():
        _eprint(f"FAIL: run_dir does not exist: {run_dir}")
        return 1

    session_path = args.session.resolve()
    if session_path.exists():
        session_path.unlink()
    log_dir = run_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    rendered = render_config(
        config_path,
        run_dir,
        worker_count=args.workers,
    )
    _eprint(f"rendered per-run config: {rendered}")
    _eprint(f"started cr-http-workers with {args.workers} workers on {run_dir}")

    supervisor = _spawn_workers_supervisor(rendered, Path.cwd(), log_dir / "cr-http-workers.log")
    try:
        # cr-http-workers needs time to clone the repo and bind each worker.
        # We give a fixed 15 s budget; on a healthy runner this is way more
        # than needed (sub-second per clone), but the budget exists to
        # surface a hung clone as a clear failure rather than a 60-minute
        # cosmic-ray exec that goes nowhere.
        time.sleep(15)

        rc = _run_cosmic_ray(
            ["cosmic-ray", "init", str(rendered), str(session_path)],
        )
        if rc != 0:
            return rc

        rc = _run_cosmic_ray(
            ["cr-filter-operators", str(session_path), str(rendered)],
        )
        if rc != 0:
            return rc

        started = time.monotonic()
        rc = _run_cosmic_ray(
            ["cosmic-ray", "exec", str(rendered), str(session_path)],
            timeout_s=7200.0,
        )
        wall_clock_s = time.monotonic() - started
        if rc != 0:
            return rc

        summary = summarise_session(session_path)
        print(
            _format_summary(
                workers_started=args.workers,
                wall_clock_s=wall_clock_s,
                summary=summary,
                serial_baseline_s=args.serial_baseline_s,
            )
        )

        if not is_session_healthy(summary):
            _eprint(
                "FAIL: session is not healthy (see summary above; check "
                "scripts/check_mutation.py for the exact threshold semantics)."
            )
            return 1
        return 0
    finally:
        _stop_workers_supervisor(supervisor)
        if session_path.exists() and not args.keep_session:
            try:
                session_path.unlink()
            except OSError as exc:
                _eprint(f"warning: could not remove {session_path}: {exc}")
        if owns_run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)
        else:
            # Leave the dir behind so the operator can inspect logs.
            _eprint(f"per-run artifacts left at: {run_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
