"""Wall-clock measurement for the parallel cosmic-ray distributor (issue #545).

Runs a self-contained mutation session against the pilot module
(``migration/derivation.py``) using the same ``http`` distributor the CI
mutation job now uses, prints how long it took and how many workers
actually carried the load, and tears everything down on exit. Not part of
pytest on purpose: cosmic-ray cannot execute mutants on native Windows
(issue #431, Finding 1), so the script is documented for Linux / WSL per
``docs/runbooks/mutation-testing.md``.

Use::

    python scripts/measure_mutation_parallelism.py

Exit code is 0 when the run finishes cleanly and the resulting session is
healthy by ``scripts/check_mutation.py``'s standard (INCOMPETENT < 20%,
no incomplete jobs). Exit code 1 on any failure so CI can gate on it.

The script does NOT update ``docs/quality/mutation-baseline.json``: that
file is only writable from the CI runner (per the ``PROVISIONAL`` header
in the baseline itself). What it does print is the wall-clock vs the
serial distributor's measured baseline (~3111 s on the same host, issue
#545 body), which is the read the issue body asks for.

Stdlib-only on purpose: this is a measurement tool, not product code,
and pulling in cosmic-ray or aiohttp at import time would defeat the
"ready to run" shape the operator expects.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

#: Default pilot module. The curated target set in
#: ``docs/quality/cosmic-ray.toml`` has five entries; the pilot is the
#: smallest one with the highest mutation density (233 mutants) and a
#: dedicated unit test suite that runs in under a second -- a one-module
#: session is the fastest read that still stresses the distributor.
DEFAULT_PILOT_MODULE = "migration/derivation.py"

#: Default ports, mirroring ``[cosmic-ray.distributor.http]`` in
#: ``docs/quality/cosmic-ray.toml``. Kept in sync with that file by
#: convention; we re-derive the count by counting lines rather than
#: hard-coding it twice. If the ports drift between this script and the
#: TOML, the operator will see the mismatch in the printed summary.
DEFAULT_PORTS: tuple[int, ...] = (9876, 9877, 9878, 9879)

#: Maximum seconds to wait for a worker port to accept a TCP connect
#: before failing fast. 30 s is generous: each worker process binds
#: inside a fraction of a second on a healthy runner. A 30 s ceiling is
#: the difference between a wedged-port bug that surfaces immediately
#: and one that quietly times out the whole job.
WORKER_STARTUP_TIMEOUT_S = 30.0


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _read_distributor_urls(toml_path: Path) -> list[str]:
    """Return the ``[cosmic-ray.distributor.http] worker-urls`` list.

    A stdlib TOML parser is overkill for the four-line shape we need.
    Reading line-by-line keeps the script dependency-free and survives
    comments, whitespace, and re-ordering.
    """
    in_section = False
    urls: list[str] = []
    for raw in toml_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_section = line == "[cosmic-ray.distributor.http]"
            continue
        if not in_section:
            continue
        if line.startswith("worker-urls"):
            # The list spans subsequent lines until the next non-list entry.
            after_eq = line.split("=", 1)[1].strip()
            if after_eq.startswith("["):
                # Single-line list form, e.g. ``worker-urls = ["a", "b"]``.
                inline = after_eq.strip("[]")
                urls.extend(_extract_inline_strings(inline))
                in_section = False
            continue
        # Continuation lines of a multi-line list. Stops at the first
        # non-quoted, non-comma line.
        stripped = line.rstrip(",")
        if stripped.startswith('"') and stripped.endswith('"'):
            urls.append(stripped.strip('"'))
        elif stripped:
            # Anything else ends the list (next key, comment, blank).
            break
    return urls


def _extract_inline_strings(payload: str) -> list[str]:
    pieces = [p.strip() for p in payload.split(",")]
    return [p.strip('"') for p in pieces if p]


def _ports_from_urls(urls: Iterable[str]) -> list[int]:
    ports: list[int] = []
    for url in urls:
        # urlparse imports 4 things we don't otherwise need; keep the
        # tail-split to stay stdlib-light and predictable.
        tail = url.rsplit(":", 1)[-1]
        tail = tail.rstrip("/")
        try:
            ports.append(int(tail))
        except ValueError:
            _eprint(f"warning: ignoring worker URL with non-integer port: {url}")
    return sorted(ports)


def _can_connect(host: str, port: int, timeout_s: float = 1.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_for_workers(host: str, ports: Sequence[int]) -> list[int]:
    """Block until every port accepts a TCP connect or the budget runs out.

    Returns the list of ports that came up. Empty list means at least
    one worker failed to start -- the caller decides whether to abort.
    """
    deadline = time.monotonic() + WORKER_STARTUP_TIMEOUT_S
    up: list[int] = []
    remaining = list(ports)
    while remaining and time.monotonic() < deadline:
        still_pending: list[int] = []
        for port in remaining:
            if _can_connect(host, port):
                up.append(port)
            else:
                still_pending.append(port)
        remaining = still_pending
        if remaining:
            time.sleep(1.0)
    return sorted(up)


def _start_worker(port: int, log_path: Path) -> subprocess.Popen[bytes]:
    """Launch one ``cosmic-ray http-worker`` and capture its PID for teardown."""
    log_fh = log_path.open("wb")
    # NEW_SESSION: the worker gets its own process group so a stray Ctrl-C
    # in the parent does not orphan the worker -- the cleanup loop kills
    # by explicit PID, not by signal propagation.
    return subprocess.Popen(
        ["cosmic-ray", "http-worker", "--port", str(port)],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop_worker(proc: subprocess.Popen[bytes], label: str) -> None:
    if proc.poll() is not None:
        _eprint(f"worker {label}: already exited (code {proc.returncode})")
        return
    try:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        _eprint(f"worker {label}: stopped")
    except ProcessLookupError:
        pass


def _write_measure_config(
    src_toml: Path,
    dst: Path,
    pilot_module: str,
    ports: Sequence[int],
) -> None:
    """Copy ``src_toml`` to ``dst`` with ``module-path`` overridden to one file.

    Overriding ``module-path`` is what keeps the session small enough to
    finish on a workstation in a few minutes. The test-command stays
    intact because cosmic-ray executes the same command for every
    mutant regardless of source module (verified at
    cosmic_ray/commands/execute.py:49 in 8.7.0, unchanged since 8.4.6).
    """
    text = src_toml.read_text(encoding="utf-8")
    rewritten: list[str] = []
    in_module_path = False
    for raw in text.splitlines(keepends=True):
        stripped = raw.lstrip()
        if stripped.startswith("module-path") or stripped.startswith("module-path "):
            in_module_path = True
            rewritten.append(f'module-path = ["{pilot_module}"]\n')
            continue
        if in_module_path:
            # Consume continuation lines of the original multi-line list.
            if stripped.startswith('"') or stripped.startswith("'"):
                continue
            in_module_path = False
        rewritten.append(raw)
    dst.write_text("".join(rewritten), encoding="utf-8")


def _measure_session_health(session_sqlite: Path) -> tuple[int, int, int, int]:
    """Return ``(total, killed, survived, incompetent)`` from the sqlite session.

    Mirrors the read path of ``scripts/check_mutation.py`` -- we want the
    same row semantics so a measurement run that is "healthy" here is
    healthy there. ``INCOMPETENT`` is the only outcome we surface to the
    operator: it is the ceiling check_mutation.py actually enforces.
    """
    if not session_sqlite.exists():
        raise FileNotFoundError(f"{session_sqlite}: session database missing")
    query = """
        SELECT wr.test_outcome AS test_outcome,
               wr.worker_outcome AS worker_outcome
        FROM work_items AS wi
        JOIN mutation_specs AS ms ON ms.job_id = wi.job_id
        LEFT JOIN work_results AS wr ON wr.job_id = wi.job_id
    """
    counts = {"killed": 0, "survived": 0, "incompetent": 0, "skipped": 0, "pending": 0}
    with sqlite3.connect(f"file:{session_sqlite}?mode=ro", uri=True) as connection:
        for row in connection.execute(query).fetchall():
            test_outcome = (row["test_outcome"] or "").lower()
            worker_outcome = (row["worker_outcome"] or "").lower()
            if worker_outcome == "skipped":
                counts["skipped"] += 1
                continue
            if not test_outcome:
                counts["pending"] += 1
                continue
            counts[test_outcome] = counts.get(test_outcome, 0) + 1
    total_active = sum(v for k, v in counts.items() if k != "skipped")
    return (
        total_active,
        counts["killed"],
        counts["survived"],
        counts["incompetent"],
    )


def _format_summary(
    workers_started: int,
    workers_actually_up: int,
    wall_clock_s: float,
    total: int,
    killed: int,
    survived: int,
    incompetent: int,
    serial_baseline_s: float,
) -> str:
    speedup = serial_baseline_s / wall_clock_s if wall_clock_s > 0 else float("inf")
    ratio_incomp = incompetent / total if total else 0.0
    return textwrap.dedent(
        f"""
        === cosmic-ray parallelism measurement (issue #545) ===
        workers started:        {workers_started}
        workers actually up:    {workers_actually_up}
        wall-clock:             {wall_clock_s:.1f} s
        serial baseline:        {serial_baseline_s:.0f} s  (issue #545 body)
        speedup:                {speedup:.2f}x
        mutants measured:       {total}
        killed:                 {killed}
        survived:               {survived}
        incompetent:            {incompetent}  ({ratio_incomp:.1%}; ceiling 20%)
        ==========================================================
        """
    ).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "quality" / "cosmic-ray.toml",
        help="Source cosmic-ray.toml to derive ports and the test-command.",
    )
    parser.add_argument(
        "--module",
        default=DEFAULT_PILOT_MODULE,
        help="Module to mutate. Defaults to the pilot "
        f"({DEFAULT_PILOT_MODULE!r}).",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=Path("measure-mutation.sqlite"),
        help="Where to write the cosmic-ray session database.",
    )
    parser.add_argument(
        "--serial-baseline-s",
        type=float,
        default=3111.0,
        help="Reference serial wall-clock in seconds for the speedup ratio. "
        "Default 3111 matches the issue #545 body measurement.",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Leave the session database on disk after the run for inspection.",
    )
    args = parser.parse_args(argv)

    config_path = args.config
    if not config_path.exists():
        _eprint(f"FAIL: cosmic-ray config not found: {config_path}")
        return 1

    ports = _ports_from_urls(_read_distributor_urls(config_path)) or list(DEFAULT_PORTS)
    _eprint(f"using {len(ports)} workers on ports {ports} from {config_path}")

    with tempfile.TemporaryDirectory(prefix="cr-measure-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        measure_config = tmp_dir / "cosmic-ray.toml"
        _write_measure_config(config_path, measure_config, args.module, ports)

        session_path = args.session.resolve()
        if session_path.exists():
            session_path.unlink()
        log_dir = tmp_dir / "logs"
        log_dir.mkdir()

        workers: list[tuple[int, subprocess.Popen[bytes]]] = []
        try:
            for port in ports:
                proc = _start_worker(port, log_dir / f"worker-{port}.log")
                workers.append((port, proc))
            _eprint(f"started {len(workers)} workers; waiting for ports to accept TCP")
            up = _wait_for_workers("127.0.0.1", ports)
            if len(up) != len(ports):
                _eprint(
                    f"FAIL: only {len(up)}/{len(ports)} workers came up within "
                    f"{WORKER_STARTUP_TIMEOUT_S:.0f}s -- aborting before exec"
                )
                for port, _proc in workers:
                    _eprint(f"  worker log port={port}: {log_dir / f'worker-{port}.log'}")
                return 1

            init_cmd = ["cosmic-ray", "init", str(measure_config), str(session_path)]
            _eprint(f"$ {' '.join(init_cmd)}")
            if subprocess.run(init_cmd, check=False).returncode != 0:
                _eprint("FAIL: cosmic-ray init exited non-zero")
                return 1

            filter_cmd = ["cr-filter-operators", str(session_path), str(measure_config)]
            _eprint(f"$ {' '.join(filter_cmd)}")
            if subprocess.run(filter_cmd, check=False).returncode != 0:
                _eprint("FAIL: cr-filter-operators exited non-zero")
                return 1

            exec_cmd = ["cosmic-ray", "exec", str(measure_config), str(session_path)]
            _eprint(f"$ {' '.join(exec_cmd)}")
            started = time.monotonic()
            result = subprocess.run(exec_cmd, check=False)
            wall_clock_s = time.monotonic() - started
            if result.returncode != 0:
                _eprint(
                    f"FAIL: cosmic-ray exec exited non-zero (code {result.returncode}); "
                    "see worker logs for the per-mutant error stream"
                )
                return 1

            total, killed, survived, incompetent = _measure_session_health(session_path)
            print(
                _format_summary(
                    workers_started=len(workers),
                    workers_actually_up=len(up),
                    wall_clock_s=wall_clock_s,
                    total=total,
                    killed=killed,
                    survived=survived,
                    incompetent=incompetent,
                    serial_baseline_s=args.serial_baseline_s,
                )
            )

            ratio_incomp = incompetent / total if total else 0.0
            if total == 0 or ratio_incomp > 0.20:
                _eprint(
                    f"FAIL: session not trustworthy (INCOMPETENT={ratio_incomp:.1%} > 20%)"
                )
                return 1
            return 0
        finally:
            for port, proc in workers:
                _stop_worker(proc, f"port={port}")
            if session_path.exists() and not args.keep_session:
                try:
                    session_path.unlink()
                except OSError as exc:
                    _eprint(f"warning: could not remove {session_path}: {exc}")
            # Best-effort flush of any backgrounded cosmic-ray children that
            # outlived their Popen handle. Reap zombies so the runner's
            # process table does not fill up across repeated invocations.
            try:
                os.waitpid(0, os.WNOHANG)
            except ChildProcessError:
                pass
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
