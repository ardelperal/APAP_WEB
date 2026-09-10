"""Validate APAP issue specifications and produce the historical ledger.

The checker owns structure, not product judgment. It can prove that a required
section exists and contains text; it cannot infer a requirement that an author
never recorded. Historical gaps therefore remain explicit instead of being
filled with generated prose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FORM_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"

REQUIRED_SECTIONS = (
    "Problema y contexto",
    "Evidencia verificable",
    "Alcance y no objetivos",
    "Criterios de aceptación",
    "Plan de validación",
    "Dependencias y riesgos",
)

EXPECTED_FORMS = {
    "bug_report.yml": "type:bug",
    "documentation.yml": "type:docs",
    "feature_request.yml": "type:feature",
    "maintenance.yml": "type:chore",
    "refactor.yml": "type:refactor",
}

SUPPORTED_TYPES = frozenset(EXPECTED_FORMS.values())
APPROVAL_LABEL = "status:approved"
AUTOMATED_ACTORS = frozenset({"dependabot[bot]"})
EMPTY_RESPONSES = frozenset({"", "_No response_"})
PAGE_SIZE = 100
REFERENCE_RE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+"
    r"(?:https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/issues/)?#?(?P<number>\d+)"
)

SIGNALS = {
    "evidence": re.compile(r"(?i)\bevidencia\b|\bevidence\b|reproducci[oó]n|reproduction"),
    "scope_or_non_goals": re.compile(
        r"(?i)\balcance\b|\bscope\b|fuera de alcance|out of scope|no objetivos?"
    ),
    "acceptance": re.compile(
        r"(?is)criterios? de aceptaci[oó]n|acceptance criteria|"
        r"\bdado\b.+\bcuando\b.+\bentonces\b|\bgiven\b.+\bwhen\b.+\bthen\b"
    ),
    "validation": re.compile(r"(?i)\bvalidaci[oó]n\b|\bverification\b|\btests?\b|\bpruebas?\b"),
    "dependencies_or_risks": re.compile(
        r"(?i)\bdependencias?\b|\bdependencies\b|\briesgos?\b|\brisks?\b|\bbloquea\b"
    ),
}


class GitHubApiError(RuntimeError):
    """Raised when GitHub cannot provide authoritative issue data."""

    def __init__(self, operation: str, target: str, detail: object = "") -> None:
        suffix = f": {detail}" if detail else ""
        super().__init__(f"GitHub API {operation} failed for {target}{suffix}")

    @classmethod
    def invalid_issue(cls, number: int) -> GitHubApiError:
        """Build an invalid single-issue payload error."""
        return cls("payload validation", f"issue #{number}")

    @classmethod
    def invalid_page(cls, page: int) -> GitHubApiError:
        """Build an invalid issue-page payload error."""
        return cls("payload validation", f"issue page {page}")


class FormLoadError(ValueError):
    """Raised when an issue form cannot be loaded as YAML."""

    def __init__(self, path: Path, detail: object) -> None:
        super().__init__(f"{path}: invalid issue form: {detail}")


class FormShapeError(TypeError):
    """Raised when an issue form has the wrong top-level shape."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path}: expected a YAML mapping")


def parse_sections(body: str) -> dict[str, str]:
    """Return H3 sections from a GitHub issue body."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def body_contract_errors(body: str) -> list[str]:
    """Return missing or empty canonical sections in declared order."""
    sections = parse_sections(body)
    return [
        heading
        for heading in REQUIRED_SECTIONS
        if sections.get(heading, "") in EMPTY_RESPONSES
    ]


def issue_contract_errors(issue: Mapping[str, Any]) -> list[str]:
    """Return actionable contract violations for one GitHub issue."""
    errors = [f"missing or empty section: {heading}" for heading in body_contract_errors(issue.get("body") or "")]
    labels = {
        label["name"] if isinstance(label, Mapping) else str(label)
        for label in issue.get("labels", [])
    }
    type_labels = labels & SUPPORTED_TYPES
    if len(type_labels) != 1:
        errors.append("requires exactly one supported type:* label")
    if APPROVAL_LABEL not in labels:
        errors.append(f"requires {APPROVAL_LABEL}")
    return errors


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except ImportError as exc:
        raise FormLoadError(path, "PyYAML is not installed") from exc
    except yaml.YAMLError as exc:
        raise FormLoadError(path, exc) from exc
    if not isinstance(data, Mapping):
        raise FormShapeError(path)
    return data


def _validate_form(path: Path, expected_label: str) -> list[str]:
    """Return contract violations for one existing issue form."""
    filename = path.name
    try:
        form = _load_yaml(path)
    except (OSError, FormLoadError, FormShapeError) as exc:
        return [str(exc)]
    violations: list[str] = []
    if form.get("labels") != [expected_label]:
        violations.append(f"{filename}: labels must be exactly [{expected_label!r}]")
    controls = {
        item.get("attributes", {}).get("label"): item
        for item in form.get("body", [])
        if isinstance(item, Mapping) and item.get("type") != "markdown"
    }
    for heading in REQUIRED_SECTIONS:
        control = controls.get(heading)
        if control is None:
            violations.append(f"{filename}: missing control {heading!r}")
        elif control.get("type") != "textarea":
            violations.append(f"{filename}: {heading!r} must be a textarea")
        elif control.get("validations", {}).get("required") is not True:
            violations.append(f"{filename}: {heading!r} must be required")
    return violations


def validate_forms(form_dir: Path = FORM_DIR) -> list[str]:
    """Return repository issue-form contract violations."""
    violations: list[str] = []
    present = {path.name for path in form_dir.glob("*.yml") if path.name != "config.yml"}
    missing = set(EXPECTED_FORMS) - present
    extra = present - set(EXPECTED_FORMS)
    violations.extend(f"missing issue form: {name}" for name in sorted(missing))
    violations.extend(f"unexpected issue form: {name}" for name in sorted(extra))

    for filename, expected_label in EXPECTED_FORMS.items():
        path = form_dir / filename
        if not path.exists():
            continue
        violations.extend(_validate_form(path, expected_label))

    config_path = form_dir / "config.yml"
    if not config_path.exists():
        violations.append("missing issue form config.yml")
    else:
        try:
            config = _load_yaml(config_path)
            if config.get("blank_issues_enabled") is not False:
                violations.append("config.yml: blank_issues_enabled must be false")
        except (OSError, FormLoadError, FormShapeError) as exc:
            violations.append(str(exc))
    return violations


def extract_closing_issue_numbers(body: str, repository: str) -> list[int]:
    """Extract same-repository issue numbers named by closing keywords."""
    owner, repo = repository.split("/", maxsplit=1)
    numbers: set[int] = set()
    for match in REFERENCE_RE.finditer(body):
        referenced_owner = match.group("owner")
        referenced_repo = match.group("repo")
        if referenced_owner and (referenced_owner.lower(), referenced_repo.lower()) != (
            owner.lower(),
            repo.lower(),
        ):
            continue
        numbers.add(int(match.group("number")))
    return sorted(numbers)


class GitHubClient:
    """Minimal read-only GitHub REST client."""

    def __init__(self, token: str = "", api_url: str = "https://api.github.com") -> None:
        self._token = token
        self._api_url = api_url.rstrip("/")

    def get(self, path: str) -> tuple[Any, Mapping[str, str]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "APAP_WEB-issue-spec-check",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        # The base URL is fixed by GitHub Actions or the caller; arbitrary
        # user-supplied schemes never enter this boundary.
        request = urllib.request.Request(  # noqa: S310
            f"{self._api_url}{path}", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return json.load(response), dict(response.headers)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise GitHubApiError("read", path, exc) from exc

    def issue(self, repository: str, number: int) -> Mapping[str, Any]:
        payload, _headers = self.get(f"/repos/{repository}/issues/{number}")
        if not isinstance(payload, Mapping) or payload.get("number") != number:
            raise GitHubApiError.invalid_issue(number)
        return payload

    def issues(self, repository: str, cutoff: int) -> list[Mapping[str, Any]]:
        issues: list[Mapping[str, Any]] = []
        page = 1
        while True:
            payload, _headers = self.get(
                f"/repos/{repository}/issues?state=all&sort=created&direction=asc"
                f"&per_page={PAGE_SIZE}&page={page}"
            )
            if not isinstance(payload, list):
                raise GitHubApiError.invalid_page(page)
            issues.extend(
                item
                for item in payload
                if isinstance(item, Mapping)
                and "pull_request" not in item
                and int(item.get("number", cutoff + 1)) <= cutoff
            )
            if len(payload) < PAGE_SIZE:
                break
            page += 1
        return sorted(issues, key=lambda item: int(item["number"]))


def validate_pr_event(event: Mapping[str, Any], client: GitHubClient) -> list[str]:
    """Validate every issue that a human PR declares it will close."""
    pull_request = event.get("pull_request") or {}
    actor = (pull_request.get("user") or {}).get("login", "")
    if actor in AUTOMATED_ACTORS:
        return []
    repository = (event.get("repository") or {}).get("full_name", "")
    if not repository or "/" not in repository:
        return ["event does not identify repository.full_name"]
    numbers = extract_closing_issue_numbers(pull_request.get("body") or "", repository)
    if not numbers:
        return ["PR body must close at least one approved issue"]
    violations: list[str] = []
    for number in numbers:
        issue = client.issue(repository, number)
        if "pull_request" in issue:
            violations.append(f"#{number}: reference resolves to a pull request")
            continue
        # Closed approved issues predate full section requirements (issue #641)
        if issue.get("state") == "closed" and APPROVAL_LABEL in _labels(issue):
            continue
        violations.extend(f"#{number}: {error}" for error in issue_contract_errors(issue))
    return violations


def _labels(issue: Mapping[str, Any]) -> set[str]:
    return {
        label["name"] if isinstance(label, Mapping) else str(label)
        for label in issue.get("labels", [])
    }


def baseline_record(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Build one body-free, evidence-bound historical ledger record."""
    body = issue.get("body") or ""
    sections = parse_sections(body)
    labels = _labels(issue)
    type_labels = sorted(labels & SUPPORTED_TYPES)
    missing_sections = body_contract_errors(body)
    missing_labels = []
    if len(type_labels) != 1:
        missing_labels.append("exactly-one-supported-type")
    if APPROVAL_LABEL not in labels:
        missing_labels.append(APPROVAL_LABEL)
    return {
        "number": issue["number"],
        "url": issue["html_url"],
        "state": issue["state"],
        "title": issue["title"],
        "type": type_labels[0] if len(type_labels) == 1 else "not-inferable",
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "canonical_sections": {
            heading: "present" if sections.get(heading, "") not in EMPTY_RESPONSES else "absent"
            for heading in REQUIRED_SECTIONS
        },
        "semantic_signals": {
            name: "detected" if pattern.search(body) else "not-inferable"
            for name, pattern in SIGNALS.items()
        },
        "workflow_ready": not missing_sections and not missing_labels,
        "missing_sections": missing_sections,
        "missing_labels": missing_labels,
    }


def write_baseline(
    issues: Iterable[Mapping[str, Any]], output: Path, repository: str, cutoff: int, as_of: str
) -> None:
    """Write deterministic JSON Lines: one metadata row, then one row per issue."""
    records = [baseline_record(issue) for issue in issues]
    metadata = {
        "kind": "metadata",
        "schema_version": 1,
        "repository": repository,
        "cutoff_issue": cutoff,
        "as_of": as_of,
        "issue_count": len(records),
    }
    rows = [metadata, *records]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _report(violations: Sequence[str]) -> int:
    for violation in violations:
        print(f"issue-spec: {violation}", file=sys.stderr)
    if violations:
        print(f"issue-spec: failed with {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("issue-spec: contract satisfied")
    return 0


def _pin_output_encoding() -> None:
    """Pin gate output to UTF-8 on every supported workstation locale."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("forms", help="validate repository issue forms")
    pr_event = subparsers.add_parser("pr-event", help="validate issues linked by a PR event")
    pr_event.add_argument("event", type=Path)
    baseline = subparsers.add_parser("baseline", help="write the historical issue ledger")
    baseline.add_argument("--repository", required=True)
    baseline.add_argument("--cutoff", required=True, type=int)
    baseline.add_argument("--as-of", required=True)
    baseline.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _pin_output_encoding()
    args = _parser().parse_args(argv)
    if args.command == "forms":
        return _report(validate_forms())
    client = GitHubClient(
        token=os.environ.get("GITHUB_TOKEN", ""),
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    if args.command == "pr-event":
        event = json.loads(args.event.read_text(encoding="utf-8"))
        return _report(validate_pr_event(event, client))
    issues = client.issues(args.repository, args.cutoff)
    write_baseline(issues, args.output, args.repository, args.cutoff, args.as_of)
    print(f"issue-spec: wrote {len(issues)} historical issues to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
