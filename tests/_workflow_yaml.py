"""Structured access to GitHub Actions workflow YAML (issue #963).

The workflow tests in ``tests/test_ci_workflow.py`` used to analyse the
YAML as text: substring asserts, ``workflow.index(...)`` cuts and the
``_trigger_lines`` indent parser. A textual assert on YAML is not
deterministic with respect to structure — an innocuous comment or
indentation change could turn a test red (or green) without any
behavioural change. This module is the structured replacement.

PyYAML note: YAML 1.1 resolves the bare ``on:`` key as the boolean
``True``, so ``load()`` normalizes it back to ``"on"`` for every caller.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: Directory that holds the repository's workflow files.
WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def load(path: Path) -> dict[str, Any]:
    """Parse a workflow file into a dict, mapping the ``True`` key back to ``on``."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise AssertionError(f"{path} is not a YAML mapping (got {type(doc).__name__})")
    if True in doc:
        doc["on"] = doc.pop(True)
    return doc


def on_triggers(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the workflow's ``on:`` mapping (empty when none is declared)."""
    triggers = doc.get("on")
    return triggers if isinstance(triggers, dict) else {}


def job(doc: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Return the job mapping for ``job_id``, failing loudly when absent."""
    jobs = doc.get("jobs") or {}
    if job_id not in jobs:
        raise AssertionError(f"job {job_id!r} not found; jobs: {sorted(jobs)}")
    return jobs[job_id]


def steps(job_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a job's step mappings (empty when the job declares none)."""
    value = job_entry.get("steps")
    if not value:
        return []
    return [step for step in value if isinstance(step, dict)]


def find_step(job_entry: dict[str, Any], name_substring: str) -> dict[str, Any]:
    """Return the first step whose ``name`` contains ``name_substring``."""
    for step in steps(job_entry):
        if name_substring in str(step.get("name", "")):
            return step
    raise AssertionError(
        f"no step with name containing {name_substring!r}; steps: "
        f"{[str(step.get('name', '<unnamed>')) for step in steps(job_entry)]}"
    )


def needs(job_entry: dict[str, Any]) -> list[str]:
    """Return a job's ``needs`` as a list (normalizing the scalar form)."""
    value = job_entry.get("needs")
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def permissions(doc_or_job: dict[str, Any]) -> dict[str, str]:
    """Return a workflow's or job's ``permissions`` as a scope->level mapping.

    The string forms GitHub accepts (``read-all`` / ``write-all``) do not
    enumerate scopes, so they are returned as ``{"*": <form>}``.
    """
    value = doc_or_job.get("permissions")
    if value is None:
        return {}
    if isinstance(value, str):
        return {"*": str(value)}
    return {str(scope): str(level) for scope, level in value.items()}


def concurrency(doc_or_job: dict[str, Any]) -> dict[str, Any] | str | None:
    """Return a workflow's or job's ``concurrency`` value as declared."""
    return doc_or_job.get("concurrency")


def runs_text(job_entry: dict[str, Any]) -> str:
    """Concatenate a job's step ``run:`` bodies, one per line.

    Command assertions may stay textual, but scoped to the ``run`` fields
    (never the whole file), so YAML comments and job-level syntax cannot
    satisfy or break them.
    """
    return "\n".join(str(step.get("run", "")) for step in steps(job_entry))


def job_text(job_entry: dict[str, Any]) -> str:
    """Structure-derived text of a job: every scalar leaf as ``key: value``.

    Replacement for the old text slicing: only actual YAML structure can
    satisfy or break a substring assertion over this text — YAML comments
    never appear, and indentation is not part of the output. Container
    keys are emitted as ``key:`` lines so key-presence assertions (e.g.
    ``"permissions:" in text``) keep working; list scalars are emitted
    bare, in document order.
    """
    lines: list[str] = []

    def walk(node: object, key: str | None) -> None:
        if isinstance(node, dict):
            if key is not None:
                lines.append(f"{key}:")
            for child_key, value in node.items():
                walk(value, str(child_key))
        elif isinstance(node, list):
            if key is not None:
                lines.append(f"{key}:")
            for item in node:
                walk(item, None)
        else:
            lines.append(f"{key}: {node}" if key is not None else str(node))

    walk(job_entry, None)
    return "\n".join(lines)


def find_value(node: object, key: str) -> object | None:
    """First scalar value stored under ``key`` anywhere in the structure.

    Returns ``None`` when the key is absent (a stored ``None`` is
    indistinguishable from absence, which no workflow in this repository
    relies on).
    """
    if isinstance(node, dict):
        if key in node:
            return node[key]
        return next(
            (
                found
                for value in node.values()
                if (found := find_value(value, key)) is not None
            ),
            None,
        )
    if isinstance(node, list):
        return next(
            (
                found
                for item in node
                if (found := find_value(item, key)) is not None
            ),
            None,
        )
    return None
