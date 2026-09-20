#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_adoption.py
"""Fail-closed adoption preflight and scanner-image lock resolver."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from quality_policy import PolicyError, load_policy

COSMIC_RAY_VERSION = "8.7.0"
MUTATION_CONFIG = "cosmic-ray.toml"
DEV_LOCK = "requirements-dev.lock"
SECURITY_SOURCES = "security-images.sources.json"
SECURITY_LOCK = "security-images.lock.json"
QUALITY_POLICY = "quality-policy.json"
PYPROJECT = "pyproject.toml"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class AdoptionError(RuntimeError):
    """A required adoption artifact is absent or unverifiable."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdoptionError(
            f"required adoption asset is unavailable: {path.name}"
        ) from exc


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise AdoptionError(f"invalid JSON in {path.name}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise AdoptionError(f"{path.name} must contain a JSON object")
    return value


def _validate_mutation_config(root: Path) -> dict[str, Any]:
    path = root / MUTATION_CONFIG
    try:
        config = tomllib.loads(_read_text(path))
    except tomllib.TOMLDecodeError as exc:
        raise AdoptionError(f"invalid TOML in {MUTATION_CONFIG}: {exc}") from exc
    section = config.get("cosmic-ray")
    if not isinstance(section, dict):
        raise AdoptionError(f"{MUTATION_CONFIG} has no [cosmic-ray] table")
    required = ("module-path", "timeout", "test-command")
    missing = [name for name in required if not section.get(name)]
    distributor = section.get("distributor")
    if not isinstance(distributor, dict) or not distributor.get("name"):
        missing.append("cosmic-ray.distributor.name")
    if missing:
        raise AdoptionError(f"{MUTATION_CONFIG} is incomplete: {', '.join(missing)}")
    return section


def _validate_quality_policy_parity(root: Path, mutation: Mapping[str, Any]) -> None:
    try:
        policy = load_policy(root / QUALITY_POLICY)
    except PolicyError as exc:
        raise AdoptionError(str(exc)) from exc
    roots = policy["subjects"]["roots"]
    if len(roots) != 1 or mutation.get("module-path") != roots[0]:
        raise AdoptionError(
            f"{MUTATION_CONFIG} module-path must match quality policy subjects.roots"
        )
    try:
        pyproject = tomllib.loads(_read_text(root / PYPROJECT))
    except tomllib.TOMLDecodeError as exc:
        raise AdoptionError(f"invalid TOML in {PYPROJECT}: {exc}") from exc
    coverage = pyproject.get("tool", {}).get("coverage", {}).get("run", {})
    if not isinstance(coverage, dict) or coverage.get("source") != roots:
        raise AdoptionError(
            f"{PYPROJECT} coverage source must match quality policy subjects.roots"
        )


def _validate_dev_lock(root: Path) -> None:
    text = _read_text(root / DEV_LOCK).replace("\\\r\n", " ").replace("\\\n", " ")
    match = re.search(
        rf"(?m)^\s*cosmic-ray=={re.escape(COSMIC_RAY_VERSION)}\b([^\n]*)", text
    )
    if match is None or not re.search(r"--hash=sha256:[0-9a-f]{64}\b", match.group(1)):
        raise AdoptionError(
            f"{DEV_LOCK} must pin cosmic-ray=={COSMIC_RAY_VERSION} with a sha256 hash"
        )


def _security_sources(root: Path) -> dict[str, str]:
    raw = _read_json_object(root / SECURITY_SOURCES)
    sources: dict[str, str] = {}
    for name, source in sorted(raw.items()):
        if (
            not isinstance(name, str)
            or not isinstance(source, str)
            or ":" not in source
        ):
            raise AdoptionError(
                f"invalid scanner source in {SECURITY_SOURCES}: {name!r}"
            )
        if (
            "replace" in source.lower()
            or "latest" in source.lower()
            or "@sha256:" in source
        ):
            raise AdoptionError(
                f"scanner source {name} must be an exact version tag: {source}"
            )
        sources[name] = source
    if set(sources) != {"gitleaks", "trivy"}:
        raise AdoptionError(
            f"{SECURITY_SOURCES} must define exactly gitleaks and trivy"
        )
    return sources


def _security_lock(root: Path, sources: Mapping[str, str]) -> dict[str, dict[str, str]]:
    raw = _read_json_object(root / SECURITY_LOCK)
    if set(raw) != set(sources):
        raise AdoptionError(f"{SECURITY_LOCK} keys do not match {SECURITY_SOURCES}")
    locked: dict[str, dict[str, str]] = {}
    for name in sorted(sources):
        entry = raw[name]
        if not isinstance(entry, dict):
            raise AdoptionError(f"invalid lock entry for {name}")
        source = entry.get("source")
        digest = entry.get("digest")
        if (
            source != sources[name]
            or not isinstance(digest, str)
            or not DIGEST.fullmatch(digest)
        ):
            raise AdoptionError(f"unresolved or mismatched scanner lock for {name}")
        locked[name] = {"source": source, "digest": digest}
    return locked


def validate_adoption(root: Path) -> dict[str, dict[str, str]]:
    """Validate every artifact needed by mutation and security jobs."""
    mutation = _validate_mutation_config(root)
    _validate_quality_policy_parity(root, mutation)
    _validate_dev_lock(root)
    sources = _security_sources(root)
    return _security_lock(root, sources)


def resolve_security_images(
    sources: Mapping[str, str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, dict[str, str]]:
    """Resolve exact tags to registry manifest digests, failing on any ambiguity."""
    resolved: dict[str, dict[str, str]] = {}
    for name, source in sorted(sources.items()):
        command = [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            source,
            "--format",
            "{{json .Manifest.Digest}}",
        ]
        try:
            result = runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
            )
        except OSError as exc:
            raise AdoptionError(
                "docker buildx is required to resolve scanner digests"
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit {result.returncode}"
            raise AdoptionError(f"could not resolve {name} ({source}): {detail}")
        try:
            digest = json.loads(result.stdout.strip())
        except json.JSONDecodeError as exc:
            raise AdoptionError(
                f"registry returned invalid digest JSON for {name}"
            ) from exc
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise AdoptionError(
                f"registry returned an unverifiable digest for {name}: {digest!r}"
            )
        resolved[name] = {"source": source, "digest": digest}
    return resolved


def _write_lock(path: Path, lock: Mapping[str, Mapping[str, str]]) -> None:
    payload = json.dumps(lock, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resolve-security-images", action="store_true")
    group.add_argument("--print-image", choices=("gitleaks", "trivy"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.resolve_security_images:
            sources = _security_sources(root)
            lock = resolve_security_images(sources)
            _write_lock(root / SECURITY_LOCK, lock)
            print(f"wrote {SECURITY_LOCK} with {len(lock)} verified digests")
            return 0
        lock = validate_adoption(root)
        if args.print_image:
            entry = lock[args.print_image]
            print(f"{entry['source']}@{entry['digest']}")
        else:
            print("adoption preflight: complete")
        return 0
    except AdoptionError as exc:
        print(f"adoption preflight failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
