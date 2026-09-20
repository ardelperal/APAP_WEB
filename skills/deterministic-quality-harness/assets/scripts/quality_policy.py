#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/quality_policy.py
"""Load the canonical quality policy and bind evidence to candidate and scope identities."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "quality-policy.json"
REQUIRED_GATES = frozenset({"layers", "complexity", "crap", "dry", "mutation_sites", "mutation"})


class PolicyError(RuntimeError):
    """The canonical policy or its declared denominator is unusable."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"quality policy is unreadable: {exc}") from exc
    if not isinstance(policy, dict) or policy.get("schema") != "deterministic-quality-harness/quality-policy/v1":
        raise PolicyError("quality policy schema must be deterministic-quality-harness/quality-policy/v1")
    subjects = policy.get("subjects")
    gates = policy.get("gates")
    if not isinstance(subjects, dict) or not isinstance(gates, dict):
        raise PolicyError("quality policy requires subjects and gates objects")
    for field in ("roots", "suffixes", "exclude_parts"):
        value = subjects.get(field)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise PolicyError(f"quality policy subjects.{field} must be a non-empty string list")
    missing = REQUIRED_GATES - set(gates)
    if missing:
        raise PolicyError(f"quality policy is missing gates: {', '.join(sorted(missing))}")
    for gate in sorted(REQUIRED_GATES):
        config = gates[gate]
        if not isinstance(config, dict):
            raise PolicyError(f"quality policy gate '{gate}' must be an object")
        required = {"command": list, "owner": str, "non_ownership": list, "ceilings": dict}
        for field, expected in required.items():
            if field not in config or not isinstance(config[field], expected) or not config[field]:
                raise PolicyError(f"quality policy gate '{gate}' requires non-empty {field}")
        if not all(isinstance(item, str) and item for item in config["command"]):
            raise PolicyError(f"quality policy gate '{gate}' command must contain strings")
        if not all(isinstance(item, str) and item for item in config["non_ownership"]):
            raise PolicyError(f"quality policy gate '{gate}' non_ownership must contain strings")
    policy["_path"] = str(path.resolve())
    return policy


def subject_paths(root: Path, policy: dict) -> list[Path]:
    subjects = policy["subjects"]
    suffixes = tuple(subjects["suffixes"])
    excluded = frozenset(subjects["exclude_parts"])
    paths: set[Path] = set()
    for declared_root in subjects["roots"]:
        base = root / declared_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in suffixes and not excluded.intersection(path.relative_to(root).parts):
                paths.add(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def subject_manifest(
    root: Path, policy: dict, *, allow_empty: bool = False
) -> list[dict[str, str]]:
    paths = subject_paths(root, policy)
    if not paths and not allow_empty:
        raise PolicyError(f"quality policy found no eligible subjects under {root}")
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in paths
    ]


def _git_identity(root: Path) -> dict[str, str]:
    values: list[str] = []
    for revision in ("HEAD", "HEAD^{tree}"):
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", revision],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
        )
        values.append(result.stdout.strip() if result.returncode == 0 else "unversioned")
    return {"commit": values[0], "tree": values[1]}


def build_evidence(
    root: Path, policy: dict, gate: str, *, allow_empty: bool = False
) -> dict:
    if gate not in REQUIRED_GATES:
        raise PolicyError(f"gate '{gate}' is not governed by the quality policy")
    manifest = subject_manifest(root, policy, allow_empty=allow_empty)
    serializable_policy = {key: value for key, value in policy.items() if not key.startswith("_")}
    policy_identity = _sha256(_canonical(serializable_policy))
    manifest_identity = _sha256(_canonical(manifest))
    config = policy["gates"][gate]
    scope_identity = _sha256(_canonical({"policy": policy_identity, "manifest": manifest_identity}))
    command = list(config["command"])
    tool_path = root / command[1]
    if not tool_path.is_file():
        tool_path = DEFAULT_POLICY_PATH.parent / command[1]
    if not tool_path.is_file():
        raise PolicyError(f"gate '{gate}' tool is unavailable: {command[1]}")
    return {
        "candidate": _git_identity(root),
        "policy_identity": policy_identity,
        "scope_identity": scope_identity,
        "subject_manifest": manifest,
        "tool": {
            "gate": gate,
            "command": command,
            "sha256": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
        },
        "owner": config["owner"],
        "non_ownership": list(config["non_ownership"]),
    }


def bind_envelope(
    envelope: dict,
    root: Path,
    gate: str,
    *,
    checked: Iterable[str],
    skipped: Iterable[dict] = (),
    unclassified: Iterable[str] = (),
    policy: dict | None = None,
) -> dict:
    resolved_policy = policy or load_policy()
    expected_ceilings = resolved_policy["gates"][gate]["ceilings"]
    if envelope.get("ceilings") != expected_ceilings:
        raise PolicyError(f"gate '{gate}' ceilings drifted from quality policy")
    evidence = build_evidence(
        root, resolved_policy, gate, allow_empty=envelope.get("status") == "error"
    )
    manifest_paths = {item["path"] for item in evidence["subject_manifest"]}
    checked_set = set(checked)
    skipped_items = list(skipped)
    skipped_set = {item.get("path") for item in skipped_items}
    unclassified_set = set(unclassified)
    represented = checked_set | skipped_set | (unclassified_set & manifest_paths)
    if represented != manifest_paths:
        raise PolicyError(f"gate '{gate}' subject accounting does not match quality policy")
    if (checked_set | skipped_set) - manifest_paths:
        raise PolicyError(f"gate '{gate}' checked or skipped subjects are outside quality policy")
    if (checked_set & skipped_set) or (checked_set & unclassified_set) or (skipped_set & unclassified_set):
        raise PolicyError(f"gate '{gate}' subject accounting overlaps")
    envelope.update(evidence)
    envelope["subjects"] = {
        "checked": sorted(checked_set),
        "skipped": sorted(skipped_items, key=lambda item: (item.get("path", ""), item.get("reason", ""))),
        "unclassified": sorted(unclassified_set),
    }
    return envelope


def expected_subjects(root: Path, policy: dict | None = None) -> list[str]:
    resolved = policy or load_policy()
    return [path.relative_to(root).as_posix() for path in subject_paths(root, resolved)]
