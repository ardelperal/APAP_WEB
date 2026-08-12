"""Per-run cosmic-ray config with substituted Unix-socket worker URLs (issue #545).

The committed ``docs/quality/cosmic-ray.toml`` carries an ``http``
distributor pointing at placeholder Unix domain sockets under
``/tmp/apap-cosmic-ray/``. The CI mutation job needs the actual paths
to live in a *per-run* temp directory so two concurrent jobs on the
same host (scheduled run on ``main`` plus a manual dispatch on a
feature branch -- the failure mode the issue body explicitly warns about
in the context of #532) cannot bind the same path.

This helper is the only sanctioned way to materialise the per-run
config. Stdlib-only on purpose: cosmic-ray is Linux-only (issue #431
Finding 1), and the committed ``docs/quality/cosmic-ray.toml`` is the
only template we ever read -- a 100-line file with a stable shape, so
a line-based rewrite is more reliable than the round-trip through a
TOML library would be. Two helpers the CI workflow calls directly:

- ``render_config(template_path, run_dir) -> Path`` -- writes a copy of
  the template to ``run_dir/cosmic-ray.toml`` with the worker URLs
  re-pointed at ``run_dir/wN.sock``, returning the path.
- ``summarise_session(session_db) -> dict`` -- reads the resulting
  session and reports the same health numbers
  ``scripts/check_mutation.py`` enforces (total / killed / survived /
  incompetent), so the operator can read off a real measurement instead
  of guessing whether the new distributor held up.
- ``is_session_healthy(summary) -> bool`` -- the same 20 % INCOMPETENT
  ceiling ``check_mutation.py`` enforces, exposed as a single boolean so
  the operator script can gate without re-implementing the policy.

Not in the pytest suite on purpose: cosmic-ray cannot execute mutants
on native Windows (issue #431, Finding 1), and the per-run generation
is exercised end-to-end by the CI ``mutation`` job itself. The
line-based rewrite path is unit-tested by
``tests/test_cosmic_ray_run_config.py`` (any platform), so the surface
that can fail outside Linux is pinned.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DEFAULT_WORKER_COUNT = 4
DEFAULT_SOCKET_TEMPLATE = "unix://{run_dir}/w{idx}.sock"


def _is_section_header(line: str) -> bool:
    """True when ``line`` opens a new TOML sub-section (``[foo.bar]`` etc.)."""
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _skip_distributor_http_block(
    lines: list[str], start: int
) -> int:
    """Return the index past the legacy ``[cosmic-ray.distributor.http]`` block.

    The block runs from ``start`` (the header line itself) up to but
    not including the next ``[``-bracketed section header. Used by
    the rewrite to swallow the old block once the synthesised one has
    been emitted in its place.
    """
    i = start + 1
    while i < len(lines) and not _is_section_header(lines[i]):
        i += 1
    return i


def _emit_distributor_header(
    out: list[str],
    lines: list[str],
    start: int,
) -> int:
    """Consume the ``[cosmic-ray.distributor]`` block and append the rewritten form.

    ``start`` is the index of the header line itself. Returns the
    index of the first line *not* consumed -- the next iteration of
    the outer loop picks up there.
    """
    out.append(lines[start])
    i = start + 1
    while i < len(lines):
        inner_stripped = lines[i].strip()
        if inner_stripped.startswith("name ") or inner_stripped.startswith("name="):
            out.append('name = "http"\n')
            i += 1
            continue
        # Comment + blank lines stay verbatim -- the operator's
        # context survives the rewrite so the rendered config reads
        # like the source the operator audited.
        if inner_stripped.startswith("#") or inner_stripped == "":
            out.append(lines[i])
            i += 1
            continue
        # The first non-blank, non-name, non-comment line is the start
        # of the next sub-section (typically the http sub-section
        # header) -- stop here and let the outer loop emit the
        # synthesised replacement.
        break
    return i


def _replace_distributor_block(
    template_lines: list[str],
    worker_urls: list[str],
) -> list[str]:
    """Rewrite the ``[cosmic-ray.distributor*]`` sections in ``template_lines``.

    The committed file looks like::

        [cosmic-ray]
        ...
        [cosmic-ray.distributor]
        name = "http"
        # (comment lines explaining the worker choice)
        [cosmic-ray.distributor.http]
        worker-urls = [
            "unix:///tmp/apap-cosmic-ray/w1.sock",
            ...
        ]
        [cosmic-ray.filters.operators-filter]
        ...

    We keep everything up to (and including) the ``[cosmic-ray.distributor]``
    header, replace ``name = "..."`` and all comments inside that block
    with ``name = "http"``, then synthesise a fresh
    ``[cosmic-ray.distributor.http]`` block whose ``worker-urls`` list
    points at the per-run dir. Everything from the next non-distributor
    ``[`` header onward is preserved verbatim.

    The logic is line-based rather than TOML-based because (a) the
    template is a small stable file, (b) the rewrite must keep comments
    the operator added around the distributor section -- a TOML
    round-trip would strip them -- and (c) it lets this script stay
    stdlib-only without dragging in a TOML write dependency that
    cosmic-ray's transitive ``toml`` package does not actually expose.
    """
    out: list[str] = []
    found_distributor = False
    i = 0
    while i < len(template_lines):
        line = template_lines[i]
        stripped = line.strip()

        # The legacy http sub-section is the block we are replacing.
        # Swallow it before the outer loop appends anything so the
        # synthesised block above is the only ``[cosmic-ray.distributor.http]``
        # the rendered file carries.
        if stripped == "[cosmic-ray.distributor.http]":
            i = _skip_distributor_http_block(template_lines, i)
            continue

        if stripped == "[cosmic-ray.distributor]" and not found_distributor:
            found_distributor = True
            i = _emit_distributor_header(out, template_lines, i)
            out.append("\n")
            out.append("[cosmic-ray.distributor.http]\n")
            out.append("worker-urls = [\n")
            for url in worker_urls:
                out.append(f'    "{url}",\n')
            out.append("]\n")
            out.append("\n")
            continue

        out.append(line)
        i += 1

    if not found_distributor:
        raise ValueError("template does not contain a [cosmic-ray.distributor] section")  # noqa: TRY003 — operator-facing diagnostic
    return out


def render_config(
    template_path: Path,
    run_dir: Path,
    *,
    worker_count: int = DEFAULT_WORKER_COUNT,
) -> Path:
    """Write a per-run cosmic-ray config with worker URLs re-pointed at ``run_dir``.

    The committed template's worker URLs are placeholders; this helper
    copies the template and rewrites the ``distributor.http.worker-urls``
    list so each entry points at ``run_dir/w{1..N}.sock``. The relative
    shape is preserved (4 entries by default) so the operator's mental
    model -- "4 workers, one per core" -- matches whatever this script
    emits.

    Parameters
    ----------
    template_path:
        Path to the committed ``docs/quality/cosmic-ray.toml`` (or any
        compatible cosmic-ray config that carries a
        ``[cosmic-ray.distributor]`` section).
    run_dir:
        Per-run directory the workers will bind their sockets in. Must
        already exist; the function writes ``run_dir/cosmic-ray.toml``.
    worker_count:
        Number of worker URLs to emit. The CI workflow uses
        ``DEFAULT_WORKER_COUNT``; lowering it is the lever if a future run
        shows the timeout / INCOMPETENT ceiling being tripped by CPU
        contention under 4-way parallel mutation execution.

    Returns
    -------
    Path
        The path to the per-run config file (i.e. ``run_dir/cosmic-ray.toml``).
    """
    if worker_count < 1:
        raise ValueError(f"worker_count must be >= 1, got {worker_count}")  # noqa: TRY003 — operator-facing diagnostic
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run_dir does not exist: {run_dir}")  # noqa: TRY003 — operator-facing diagnostic

    # POSIX-form the path regardless of host OS: cosmic-ray is Linux-only
    # (issue #431 Finding 1), so the per-run config is only ever read on
    # a POSIX filesystem. Normalising here keeps the helper testable on
    # Windows and produces portable URLs a human can grep without
    # escaping backslashes.
    posix_run_dir = Path(run_dir).as_posix()
    worker_urls = [
        DEFAULT_SOCKET_TEMPLATE.format(run_dir=posix_run_dir, idx=i)
        for i in range(1, worker_count + 1)
    ]

    template_lines = template_path.read_text(encoding="utf-8").splitlines(keepends=True)
    rewritten_lines = _replace_distributor_block(template_lines, worker_urls)

    out_path = run_dir / "cosmic-ray.toml"
    out_path.write_text("".join(rewritten_lines), encoding="utf-8")
    return out_path


def read_worker_urls(rendered_config: Path) -> list[str]:
    """Return the worker URL list from a previously-rendered per-run config.

    Provided so the CI workflow can read the same socket paths back out
    without re-deriving them, and so ``measure_mutation_parallelism.py``
    can re-use this helper to discover what the template produced.

    Uses line-based parsing (matching ``render_config``) so the helper
    does not depend on a TOML library -- a TOML round-trip would also
    serve, but the list-of-strings shape is small enough that a regex
    on ``worker-urls = [ ... ]`` is the simpler path.
    """
    import re

    in_block = False
    urls: list[str] = []
    for raw_line in rendered_config.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("worker-urls"):
            in_block = True
            # Inline form on the same line: ``worker-urls = ["a", "b"]``.
            if "[" in stripped and "]" in stripped:
                inside = stripped.split("[", 1)[1].rsplit("]", 1)[0]
                urls.extend(_extract_inline_strings(inside))
                return urls
            continue
        if not in_block:
            continue
        if stripped.startswith("]"):
            return urls
        # Continuation lines of a multi-line list.
        cleaned = stripped.rstrip(",").strip()
        if cleaned.startswith('"') and cleaned.endswith('"'):
            urls.append(cleaned.strip('"'))
    return urls


def _extract_inline_strings(payload: str) -> list[str]:
    """Split a TOML inline array payload into its quoted string entries."""
    pieces = [p.strip() for p in payload.split(",")]
    return [p.strip('"') for p in pieces if p]


def summarise_session(session_db: Path) -> dict[str, int]:
    """Return ``(total, killed, survived, incompetent, skipped, pending)`` for one session.

    Mirrors the read path of ``scripts/check_mutation.py`` exactly:
    SKIPPED rows (filtered by ``cr-filter-operators``) are excluded from
    the active total, and INCOMPETENT rows are reported separately so the
    operator can read off whether the 20 % ceiling is at risk.
    """
    if not session_db.exists():
        raise FileNotFoundError(f"session database missing: {session_db}")  # noqa: TRY003 — operator-facing diagnostic
    query = """
        SELECT wr.test_outcome AS test_outcome,
               wr.worker_outcome AS worker_outcome
        FROM work_items AS wi
        JOIN mutation_specs AS ms ON ms.job_id = wi.job_id
        LEFT JOIN work_results AS wr ON wr.job_id = wi.job_id
    """
    counts = {"killed": 0, "survived": 0, "incompetent": 0, "skipped": 0, "pending": 0}
    with sqlite3.connect(f"file:{session_db}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute(query).fetchall():
            worker_outcome = (row["worker_outcome"] or "").lower()
            test_outcome = (row["test_outcome"] or "").lower()
            if worker_outcome == "skipped":
                counts["skipped"] += 1
                continue
            if not test_outcome:
                counts["pending"] += 1
                continue
            counts[test_outcome] = counts.get(test_outcome, 0) + 1
    active_total = sum(v for k, v in counts.items() if k != "skipped")
    return {
        "total": active_total,
        "killed": counts["killed"],
        "survived": counts["survived"],
        "incompetent": counts["incompetent"],
        "skipped": counts["skipped"],
        "pending": counts["pending"],
    }


def is_session_healthy(summary: dict[str, int], *, incompetent_ceiling: float = 0.20) -> bool:
    """Return True iff ``summary`` passes ``check_mutation.py``'s health floor.

    Centralised so the measurement script and any future CI gate agree
    on what "healthy" means. The 20 % INCOMPETENT ceiling is the value
    hard-coded in ``scripts/check_mutation.py``: anything above it is
    treated as a broken runner, not a code regression.
    """
    total = summary["total"]
    if total == 0:
        return False
    if summary["pending"] > 0:
        return False
    if summary["incompetent"] / total > incompetent_ceiling:
        return False
    return summary["killed"] != 0


def _pin_output_encoding() -> None:
    """Reconfigure stdout/stderr to UTF-8 so non-ASCII messages print on every platform.

    Pin from issue #488: the CI runner is UTF-8 but Windows hosts default
    to cp1252, and ``print("§")`` raised UnicodeEncodeError from inside
    the helper -- turning a real error into a traceback at the worst
    possible moment. Every printing gate under ``scripts/`` calls this
    from its ``main()``; the regression pin lives in
    ``tests/test_gate_output_encoding.py`` and reads
    ``sys.stdout.reconfigure`` / ``sys.stderr.reconfigure`` as
    ``ast.Attribute`` chains, so this body has to keep both stream
    names spelled out rather than collapsing them through a loop.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the ``render`` CLI subcommand.

    Kept module-private on purpose: this script is meant to be called as
    a helper, not as a user-facing tool. ``measure_mutation_parallelism.py``
    is the operator-facing entry point; this one exists so the CI mutation
    step can materialise a per-run config in a single shell invocation.
    """
    parser = argparse.ArgumentParser(
        prog="python scripts/cosmic_ray_run_config.py",
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser(
        "render",
        help="Materialise a per-run cosmic-ray.toml with substituted worker URLs.",
    )
    render.add_argument(
        "--template",
        type=Path,
        required=True,
        help="Path to the committed cosmic-ray.toml (the source of truth).",
    )
    render.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Per-run directory the workers will bind their sockets in. Must exist.",
    )
    render.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Where to write the rendered config. Defaults to <run-dir>/cosmic-ray.toml.",
    )
    render.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKER_COUNT,
        help="Number of worker URLs to emit. Default matches the 4 vCPU of the runner.",
    )
    return parser.parse_args(argv)


def _render_command(args: argparse.Namespace) -> int:
    out_path = args.output or args.run_dir / "cosmic-ray.toml"
    written = render_config(
        args.template,
        args.run_dir,
        worker_count=args.workers,
    )
    if written != out_path:
        # Caller asked for a specific output path -- ``render_config``
        # always writes to <run_dir>/cosmic-ray.toml, so we move into
        # place if the paths differ. Keeps ``render_config``'s contract
        # simple (returns the canonical path) while letting CI ask for a
        # different file name without a separate code path.
        written = written.rename(out_path)
    print(str(out_path))
    return 0


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = _parse_args(argv)
    if args.command == "render":
        return _render_command(args)
    raise SystemExit(f"unknown command: {args.command!r}")  # noqa: TRY003 — argparse subparsers reject unknown commands upstream


__all__ = [
    "DEFAULT_SOCKET_TEMPLATE",
    "DEFAULT_WORKER_COUNT",
    "is_session_healthy",
    "read_worker_urls",
    "render_config",
    "summarise_session",
]


if __name__ == "__main__":
    raise SystemExit(main())
