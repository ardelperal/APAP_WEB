"""Guard: every FROM line in Dockerfile must carry an @sha256: digest.

Issue: #338 — Docker base images pinned by tag instead of digest.
A mutable tag (e.g. `python:3.11-slim-bookworm`) can resolve to different
bytes over time. Each FROM must be pinned to an immutable content-addressable
digest so rebuilds are bit-for-bit reproducible.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCKERFILE = ROOT / "Dockerfile"


def test_dockerfile_every_from_has_sha256_digest() -> None:
    """Every FROM line in Dockerfile must end with @sha256:<64 hex chars>."""
    content = DOCKERFILE.read_text()
    from_lines: list[tuple[int, str]] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if re.match(r"^\s*FROM\s+", line, re.IGNORECASE):
            from_lines.append((i, line.strip()))

    assert from_lines, "No FROM lines found in Dockerfile"

    missing_digest: list[tuple[int, str]] = []
    for lineno, line in from_lines:
        # Allow "FROM scratch" etc. — scratch has no content to pin.
        if re.match(r"^\s*FROM\s+scratch\s", line, re.IGNORECASE):
            continue
        if "@sha256:" not in line:
            missing_digest.append((lineno, line))

    assert not missing_digest, (
        "The following FROM lines lack @sha256: digest:\n"
        + "\n".join(f"  line {no}: {ln}" for no, ln in missing_digest)
    )
