#!/usr/bin/env python3
# ci-pattern asset — fail-closed host readback drift check (DysTelefonica/team-skills#138)
"""Compare the declared host contract against JSON snapshots of the host API.

Every documented rule — label, required check, merge method, ruleset,
protection flag — is classified in the contract (see
``host-contract.example.json``) as ``host-enforced`` (the host API must
show it) or ``documented-only`` (documentation only; MUST NOT be described
as a gate; HR-34). The caller captures host API responses with read-only
GETs and passes them as snapshot files (``--snapshot kind=path``, all four
kinds required); the script never touches the network, never mutates the
host, never probes a write. Drift (exit 1) is either direction: a
``host-enforced`` declaration the host does not show or shows with a
different value, or an enforced required check / merge method / protection
flag the contract does not declare; ``documented-only`` entries are listed
and never judged. Missing/unreadable/malformed contract or snapshot is
doubt, and doubt fails closed (HR-3). Exit codes: 0 no drift; 1 drift
findings; 2 fail-closed.
"""
import argparse
import json
import sys
from pathlib import Path

HOST_ENFORCED = "host-enforced"
DOCUMENTED_ONLY = "documented-only"
CLASSES = frozenset({HOST_ENFORCED, DOCUMENTED_ONLY})
MERGE_METHOD_KEYS = frozenset({"allow_merge_commit", "allow_squash_merge", "allow_rebase_merge", "allow_update_branch", "allow_auto_merge"})
PROTECTION_KEYS = frozenset({"enforce_admins", "required_linear_history", "required_conversation_resolution", "allow_force_pushes", "allow_deletions"})
RULESET_ENFORCEMENTS = frozenset({"active", "evaluate", "disabled"})
SNAPSHOT_KINDS = ("repo", "labels", "branch-protection", "rulesets")

class ContractError(Exception):
    """A condition the check refuses to interpret; maps to exit 2."""

def load_json(path: str, what: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"unreadable {what} '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"{what} '{path}' is not valid JSON: {exc}") from exc

def validate_contract(data: object) -> dict:
    """Validate the declared contract; every structural doubt raises (exit 2)."""
    if not isinstance(data, dict) or data.get("contract_version") != 1:
        raise ContractError("contract must be an object with contract_version 1")
    known = {"contract_version", "labels", "required_checks", "merge_methods", "rulesets", "protection"}
    if set(data) - known:
        raise ContractError(f"contract has unknown keys: {sorted(set(data) - known)}")
    contract: dict = {"labels": {}, "required_checks": {}, "merge_methods": {}, "protection": {}, "rulesets": []}
    for where in ("labels", "required_checks"):
        entries = data.get(where, [])
        if not isinstance(entries, list):
            raise ContractError(f"{where} must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"] or entry.get("class") not in CLASSES:
                raise ContractError(f"{where}: every entry needs a non-empty 'name' and 'class' one of {sorted(CLASSES)}")
            if entry["name"] in contract[where]:
                raise ContractError(f"{where}: duplicate name '{entry['name']}'")
            contract[where][entry["name"]] = entry["class"]
    for where, keys in (("merge_methods", MERGE_METHOD_KEYS), ("protection", PROTECTION_KEYS)):
        section = data.get(where, {})
        if not isinstance(section, dict) or set(section) - keys:
            raise ContractError(f"{where} must be an object with keys from {sorted(keys)}")
        for key, value in section.items():
            if not isinstance(value, dict) or not isinstance(value.get("declared"), bool) or value.get("class") not in CLASSES:
                raise ContractError(f"{where}[{key}] must be {{'declared': bool, 'class': {sorted(CLASSES)}}}")
            contract[where][key] = (value["declared"], value["class"])
    rulesets = data.get("rulesets", [])
    if not isinstance(rulesets, list):
        raise ContractError("rulesets must be a list")
    for entry in rulesets:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"] or entry.get("enforcement") not in RULESET_ENFORCEMENTS or entry.get("class") not in CLASSES:
            raise ContractError(f"rulesets: bad entry {entry!r} (need 'name', "
                                f"'enforcement' one of {sorted(RULESET_ENFORCEMENTS)}, 'class' one of {sorted(CLASSES)})")
        contract["rulesets"].append((entry["name"], entry["enforcement"], entry["class"]))
    return contract

def load_snapshots(pairs: list[str]) -> dict:
    """Load the four required JSON snapshots; a missing one is doubt (HR-3)."""
    given: dict[str, str] = {}
    for pair in pairs:
        kind, sep, path = pair.partition("=")
        if not sep or kind not in SNAPSHOT_KINDS or kind in given:
            raise ContractError(f"--snapshot must be <kind>=<path>, kind one of {list(SNAPSHOT_KINDS)}, no duplicates")
        given[kind] = path
    missing = [kind for kind in SNAPSHOT_KINDS if kind not in given]
    if missing:
        raise ContractError(f"missing snapshots: {missing}; a snapshot that cannot be read is doubt, not a pass (HR-3)")
    snaps = {kind: load_json(path, f"snapshot '{kind}'") for kind, path in given.items()}
    if not isinstance(snaps["repo"], dict) or not isinstance(snaps["branch-protection"], dict) \
            or not isinstance(snaps["labels"], list) or not isinstance(snaps["rulesets"], list):
        raise ContractError("snapshots: 'repo'/'branch-protection' must be objects, 'labels'/'rulesets' lists")
    for where, keys in (("repo", MERGE_METHOD_KEYS), ("branch-protection", PROTECTION_KEYS)):
        for key in keys & set(snaps[where]):
            value = snaps[where][key]
            if not isinstance(value, bool) and not (
                    isinstance(value, dict) and isinstance(value.get("enabled"), bool)):
                raise ContractError(f"snapshot '{where}': unexpected value for '{key}': {value!r}")
    return snaps

def host_flag(value: object) -> bool:
    """Accept a raw boolean or the branch-protection ``{"enabled": bool}`` shape."""
    if isinstance(value, bool):
        return value
    return bool(isinstance(value, dict) and isinstance(value.get("enabled"), bool) and value["enabled"])

def _flags_drift(section: dict, host: dict, keys: frozenset, noun: str,
                 ok: list, documented: list, findings: list) -> None:
    for key in sorted(keys):
        entry = section.get(key)
        if entry is not None and entry[1] == HOST_ENFORCED and key not in host:
            raise ContractError(
                f"snapshot '{noun}': '{key}' is declared host-enforced but absent from the host snapshot; "
                "absence is doubt, not evidence (HR-3)")
        host_val = host_flag(host.get(key))
        if entry is None:
            if host_val:
                findings.append(f"{noun} '{key}' is enabled on the host but not declared in the contract")
        elif entry[1] == DOCUMENTED_ONLY:
            documented.append(f"{noun} '{key}' (declared {entry[0]})")
        elif host_val != entry[0]:
            findings.append(f"{noun} '{key}' is declared {entry[0]} but the host reports {host_val}")
        else:
            ok.append(f"{noun} '{key}' matches the host")

def compare(contract: dict, snaps: dict) -> tuple[list[str], list[str], list[str]]:
    ok: list[str] = []
    documented: list[str] = []
    findings: list[str] = []
    repo, bp = snaps["repo"], snaps["branch-protection"]
    host_labels = {e["name"] for e in snaps["labels"]
                   if isinstance(e, dict) and isinstance(e.get("name"), str)}
    for name, cls in contract["labels"].items():
        if cls == DOCUMENTED_ONLY:
            documented.append(f"label '{name}'")
        elif name not in host_labels:
            findings.append(f"label '{name}' is declared host-enforced but is absent from the host")
        else:
            ok.append(f"label '{name}' matches the host")
    rsc = bp.get("required_status_checks") if isinstance(bp.get("required_status_checks"), dict) else {}
    host_contexts = {c for c in (rsc.get("contexts") or []) if isinstance(c, str)}
    host_contexts |= {c["context"] for c in (rsc.get("checks") or []) if isinstance(c, dict) and isinstance(c.get("context"), str)}
    declared_checks = contract["required_checks"]
    for name, cls in declared_checks.items():
        if cls == DOCUMENTED_ONLY:
            documented.append(f"required check '{name}'")
        elif name not in host_contexts:
            findings.append(f"required check '{name}' is declared host-enforced but the host does not require it")
        else:
            ok.append(f"required check '{name}' matches the host")
    for name in sorted(host_contexts - set(declared_checks)):
        findings.append(f"required check '{name}' is required on the host but not declared in the contract")
    _flags_drift(contract["merge_methods"], repo, MERGE_METHOD_KEYS, "merge method", ok, documented, findings)
    _flags_drift(contract["protection"], bp, PROTECTION_KEYS, "protection flag", ok, documented, findings)
    host_rs = {e["name"]: e.get("enforcement") for e in snaps["rulesets"]
               if isinstance(e, dict) and isinstance(e.get("name"), str)}
    for name, enforcement, cls in contract["rulesets"]:
        if cls == DOCUMENTED_ONLY:
            documented.append(f"ruleset '{name}'")
        elif name not in host_rs:
            findings.append(f"ruleset '{name}' is declared host-enforced but is absent from the host")
        elif host_rs[name] != enforcement:
            findings.append(f"ruleset '{name}' is declared with enforcement '{enforcement}' "
                            f"but the host reports '{host_rs[name]}'")
        else:
            ok.append(f"ruleset '{name}' matches the host")
    return ok, documented, findings

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only drift check: declared host contract vs JSON snapshots of the host API (HR-34).")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--snapshot", action="append", default=[], metavar="KIND=PATH")
    args = parser.parse_args()
    try:
        contract = validate_contract(load_json(args.contract, "contract"))
        snaps = load_snapshots(args.snapshot)
        ok, documented, findings = compare(contract, snaps)
    except ContractError as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 2
    print("HOST READBACK REPORT")
    for line in ok:
        print(f"  ok  {line}")
    print(f"documented-only rules (listed, not judged): {len(documented)}")
    for line in documented:
        print(f"  documented-only  {line}")
    for line in findings:
        print(f"  DRIFT  {line}")
    print("VERDICT: FAIL" if findings else "VERDICT: PASS")
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
