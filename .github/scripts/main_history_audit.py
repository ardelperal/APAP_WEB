"""Issue #986 — auditoría post-hoc de push directos a `main`.

Recorre los últimos ``$LIMIT`` commits de ``origin/main`` y reporta los que NO
son alcanzables desde el primer padre de ``main`` ni desde el segundo padre
de un merge commit de PR en ``main``. El script sale ``0`` siempre (la
auditoría es informativa) y consolida los hallazgos en una issue de
seguimiento. Force-push con reescritura de ``main`` NO se detecta; el
ruleset ``main-maintainers-and-admins-merge`` era su defensa (#892 lo
desactivó), y este workflow NO lo sustituye.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Offender:
    sha: str
    subject: str
    via_pr_number: int | None
    note: str


# --- git ------------------------------------------------------------------


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def _recent_main(limit: int) -> list[tuple[str, str]]:
    """Últimos ``limit`` commits de ``origin/main`` como ``(sha, subject)``."""
    out: list[tuple[str, str]] = []
    for line in _git(
        ["log", "origin/main", f"-{limit}", "--format=%H%x09%s"]
    ).splitlines():
        sha, _, subject = line.partition("\t")
        if sha:
            out.append((sha.strip(), subject.strip()))
    return out


def _expected_set(limit: int) -> set[str]:
    """Conjunto de SHAs que NO son push directo: first-parent + rama de PR mergeada."""
    first_parent = {
        s.strip()
        for s in _git(
            ["log", "origin/main", f"-{limit}", "--first-parent", "--format=%H"]
        ).splitlines()
        if s.strip()
    }
    seconds: list[str] = []
    for line in _git(
        ["log", "origin/main", f"-{limit * 4}", "--merges", "--format=%H%x09%P"]
    ).splitlines():
        _, _, parents = line.partition("\t")
        plist = parents.split()
        if len(plist) >= 2:
            seconds.append(plist[1])
    if not seconds:
        return first_parent
    ancestors = subprocess.run(
        ["git", "rev-list", *seconds], capture_output=True, text=True, check=True
    ).stdout
    return first_parent | {s.strip() for s in ancestors.splitlines() if s.strip()}


# --- API ------------------------------------------------------------------


def _api(url: str, token: str, payload: dict[str, object] | None = None) -> object:
    """GET si ``payload`` es None, si no POST JSON. Tolerante a fallos puntuales."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "apap-main-audit",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"WARN: API {url} failed: {exc}\n")
        return {}


# --- Clasificación --------------------------------------------------------


def _classify(sha: str, subject: str, expected: set[str]) -> Offender | None:
    """Devuelve ``Offender`` si el commit es un push directo, si no ``None``."""
    if sha in expected:
        return None
    pulls_raw = _api(
        f"https://api.github.com/repos/{os.environ['REPO']}/commits/{sha}/pulls",
        os.environ["GH_TOKEN"],
    )
    pulls = pulls_raw if isinstance(pulls_raw, list) else []
    if any(p.get("merge_commit_sha") == sha for p in pulls):
        return None
    pr_number = (
        pulls[0].get("number") if pulls and isinstance(pulls[0].get("number"), int) else None
    )
    note = (
        "PR sin merge_commit_sha coincidente"
        if pulls
        else "sin PR vinculada"
    )
    return Offender(sha=sha, subject=subject, via_pr_number=pr_number, note=note)


# --- Issue ---------------------------------------------------------------


def _find_open(title: str, repo: str, token: str) -> dict[str, object] | None:
    query = f'repo:{repo} is:issue is:open in:title "{title}"'
    payload = _api(
        f"https://api.github.com/search/issues?q={urllib.parse.quote(query)}&per_page=10",
        token,
    )
    items = payload.get("items", []) if isinstance(payload, dict) else []
    for item in items:
        if isinstance(item, dict) and item.get("title") == title:
            return item
    return None


def _body(offenders: list[Offender]) -> str:
    import datetime as _dt

    today = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    lines = [
        "# Push directo a `main` detectado",
        "",
        "Issue creada por `.github/workflows/main-audit.yml`. La auditoría es",
        "**post-hoc y no bloqueante**: alerta al mantenedor, no falla. El",
        "ruleset `main-maintainers-and-admins-merge` sigue desactivado",
        "(#892); reactivarlo reintroduciría la fricción `--admin` que #892",
        "cerró.",
        "",
        f"## Hallazgos del run {today}",
        "",
    ]
    if offenders:
        lines.append("| SHA | Subject | Vía API |")
        lines.append("| --- | --- | --- |")
        for offender in offenders:
            via = (
                f"PR #{offender.via_pr_number}"
                if offender.via_pr_number is not None
                else "—"
            )
            lines.append(
                f"| `{offender.sha[:12]}` | {offender.subject} | {via} "
                f"({offender.note}) |"
            )
    else:
        lines.append("Sin infractores nuevos en este run.")
    lines.extend(
        [
            "",
            "## Procedimiento",
            "",
            "1. Para cada SHA, decidir:",
            "   - **Falso positivo documentado**: añadir el SHA a la lista",
            "     de conocidos en #986 y archivarlo con un comentario.",
            "   - **Push directo real**: revertir con un PR revert o",
            "     documentar la excepción en #986.",
            "2. Cerrar la issue solo cuando el último run no tenga",
            "   hallazgos pendientes.",
            "",
        ]
    )
    return "\n".join(lines)


# --- Entrada -------------------------------------------------------------


def main() -> int:
    repo = os.environ["REPO"]
    token = os.environ["GH_TOKEN"]
    title = os.environ.get(
        "ISSUE_TITLE", "chore(gobernanza): push directo detectado en main"
    )
    limit = int(os.environ.get("LIMIT", "30"))

    recent = _recent_main(limit)
    if not recent:
        sys.stderr.write("No commits fetched; nothing to do.\n")
        return 0

    expected = _expected_set(limit)
    offenders = [
        offender
        for sha, subject in recent
        if (offender := _classify(sha, subject, expected)) is not None
    ]

    sys.stderr.write(
        f"Inspected {len(recent)} commits; {len(offenders)} offender(s).\n"
    )
    if not offenders:
        sys.stderr.write("No offenders; nothing to do.\n")
        return 0

    body = _body(offenders)
    existing = _find_open(title, repo, token)
    if existing is not None and isinstance(existing.get("number"), int):
        _api(
            f"https://api.github.com/repos/{repo}/issues/{existing['number']}",
            token,
            payload={"body": body},
        )
        sys.stderr.write(f"Reconciled tracking issue #{existing['number']}.\n")
    else:
        created = _api(
            f"https://api.github.com/repos/{repo}/issues",
            token,
            payload={"title": title, "body": body},
        )
        sys.stderr.write(f"Created tracking issue #{created.get('number')}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
