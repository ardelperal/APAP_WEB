#!/usr/bin/env python3
# ci-pattern asset tests — host readback drift check (DysTelefonica/team-skills#138)
"""Executable suite for the host readback drift check (black-box, like CI).
Drift cases exit 1 naming the rule; fail-closed cases exit non-zero (HR-3)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ASSET = Path(__file__).resolve().parent.parent
SCRIPT = ASSET / "check_host_drift.py"
EXAMPLE_CONTRACT = ASSET / "host-contract.example.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
KINDS = ("repo", "labels", "branch-protection", "rulesets")


def base_contract() -> dict:
    return {
        "contract_version": 1,
        "labels": [{"name": "status:approved", "class": "host-enforced"}],
        "required_checks": [{"name": "branch-name", "class": "host-enforced"}],
        "merge_methods": {
            "allow_merge_commit": {"declared": True, "class": "host-enforced"},
            "allow_squash_merge": {"declared": False, "class": "host-enforced"},
            "allow_rebase_merge": {"declared": False, "class": "host-enforced"},
        },
        "protection": {
            "enforce_admins": {"declared": True, "class": "host-enforced"},
            "required_conversation_resolution": {"declared": True, "class": "host-enforced"},
        },
        "rulesets": [{"name": "default-branch", "enforcement": "active", "class": "host-enforced"}],
    }


def base_snapshots(**overrides: object) -> dict[str, str]:
    snaps: dict[str, object] = {
        "repo": {"allow_merge_commit": True, "allow_squash_merge": False, "allow_rebase_merge": False},
        "labels": [{"name": "status:approved"}],
        "branch-protection": {
            "enforce_admins": {"enabled": True},
            "required_conversation_resolution": {"enabled": True},
            "required_status_checks": {"contexts": ["branch-name"],
                                       "checks": [{"context": "branch-name", "app_id": -1}]},
        },
        "rulesets": [{"name": "default-branch", "enforcement": "active"}],
    }
    snaps.update(overrides)
    return {kind: json.dumps(snaps[kind]) for kind in KINDS}


def run_gate(contract: dict | str, snapshots: dict[str, str]) -> subprocess.CompletedProcess:
    """Run the script as CI would; a missing kind omits its ``--snapshot`` flag."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        contract_path = root / "contract.json"
        contract_path.write_text(
            contract if isinstance(contract, str) else json.dumps(contract, indent=2), encoding="utf-8")
        argv = [sys.executable, str(SCRIPT), "--contract", str(contract_path)]
        for kind in KINDS:
            if kind not in snapshots:
                continue
            path = root / f"{kind}.json"
            path.write_text(snapshots[kind], encoding="utf-8")
            argv += ["--snapshot", f"{kind}={path}"]
        return subprocess.run(argv, capture_output=True, text=True)


class DriftTests(unittest.TestCase):
    def test_declared_label_absent_from_host_exits_one(self) -> None:
        proc = run_gate(base_contract(), base_snapshots(labels=[]))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("label 'status:approved'", proc.stdout)
        self.assertIn("absent from the host", proc.stdout)

    def test_host_enforced_key_absent_from_snapshot_fails_closed(self) -> None:
        contract = base_contract()
        contract["protection"]["allow_force_pushes"] = {"declared": False, "class": "host-enforced"}
        bp = {"enforce_admins": {"enabled": True}}
        proc = run_gate(contract, base_snapshots(**{"branch-protection": bp}))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("'allow_force_pushes' is declared host-enforced but absent", proc.stderr)
        self.assertIn("absence is doubt", proc.stderr)

    def test_host_merge_method_not_declared_exits_one(self) -> None:
        contract = base_contract()
        contract["merge_methods"] = {"allow_merge_commit": {"declared": True, "class": "host-enforced"}}
        repo = {"allow_merge_commit": True, "allow_squash_merge": True, "allow_rebase_merge": False}
        proc = run_gate(contract, base_snapshots(repo=repo))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("merge method 'allow_squash_merge' is enabled on the host but not declared", proc.stdout)

    def test_documented_only_rules_listed_without_failure(self) -> None:
        contract = base_contract()
        contract["labels"].append({"name": "status:blocked", "class": "documented-only"})
        contract["protection"]["required_conversation_resolution"] = {
            "declared": True, "class": "documented-only"}
        bp = json.loads(base_snapshots()["branch-protection"])
        bp["required_conversation_resolution"] = {"enabled": False}
        proc = run_gate(contract, base_snapshots(**{"branch-protection": bp}))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("documented-only  label 'status:blocked'", proc.stdout)
        self.assertIn("documented-only  protection flag 'required_conversation_resolution'", proc.stdout)
        self.assertIn("VERDICT: PASS", proc.stdout)


class FailClosedTests(unittest.TestCase):
    def test_missing_unreadable_snapshot_and_bad_contract_exit_two(self) -> None:
        missing = base_snapshots()
        del missing["branch-protection"]
        proc = run_gate(base_contract(), missing)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("missing snapshots: ['branch-protection']", proc.stderr)
        unreadable = base_snapshots()
        unreadable["repo"] = "{not json"  # verbatim: not valid JSON
        proc = run_gate(base_contract(), unreadable)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("fail-closed", proc.stderr)
        self.assertIn("not valid JSON", proc.stderr)
        bad_class = base_contract()
        bad_class["labels"][0]["class"] = "maybe"
        proc = run_gate(bad_class, base_snapshots())
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("fail-closed", proc.stderr)


class ExampleContractTests(unittest.TestCase):
    def test_example_contract_passes_against_matching_host(self) -> None:
        argv = [sys.executable, str(SCRIPT), "--contract", str(EXAMPLE_CONTRACT)]
        for kind in KINDS:
            argv += ["--snapshot", f"{kind}={FIXTURES / (kind + '.json')}"]
        proc = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("documented-only  label 'status:blocked'", proc.stdout)
        self.assertIn("documented-only  protection flag 'required_conversation_resolution'", proc.stdout)
        self.assertIn("VERDICT: PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
