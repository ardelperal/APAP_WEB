#!/usr/bin/env python3
"""Suite de tests de la CLI `ci-pattern` (assets/tests de la skill).

Ejecución: `python3 test-ci-pattern-cli.py` — stdlib exclusivamente, sin
instalación, apta para CI. El fichero de fixtures se construye en un directorio
temporal por test (repo destino falso); ningún test escribe fuera de `tmp`.

Cubre: validación de parámetros (válida + 4 formas inválidas), round-trip del
manifiesto, verify limpio, verify con drift (fichero modificado, gate sin
cablear, bloque de slice desfasado), status, stubs adopt/update.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = SKILL_ROOT / "assets" / "bin" / "ci-pattern"
SKILL_DIR = SKILL_ROOT


def _load_cli():
    spec = importlib.util.spec_from_loader(
        "ci_pattern_cli", importlib.machinery.SourceFileLoader("ci_pattern_cli", str(CLI_PATH))
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLI = _load_cli()

VALID_PARAMS = """\
# parámetros de ejemplo
P06_review_budget_lines: 400
P10_label_approval: status:approved
P18_health_url_var: MY_DEPLOY_HEALTH_URL
P21_smoke_user_agent: my-smoke/1
P45_deploy_image: ghcr.io/example/app
"""

INVALID = {
    "unknown_key": "P99_nonexistent: 1\n" + VALID_PARAMS,
    "missing_required": "P06_review_budget_lines: 400\nP10_label_approval: status:approved\n",
    "wrong_type": VALID_PARAMS.replace("P06_review_budget_lines: 400", 'P06_review_budget_lines: "cuatrocientos"'),
    "bad_regex": VALID_PARAMS + 'P01_branch_name_pattern: "([unclosed"\n',
    "bad_label": VALID_PARAMS.replace("status:approved", "approved"),
    "bad_path": VALID_PARAMS + "P41_gate_policy_path: /etc/passwd\n",
}


def sha(path):
    data = Path(path).read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_slice_block(repo, name, content, version="v1"):
    block = (
        f"<!-- personal-skills:slice:{name} @ {version} -->\n"
        f"{content}\n"
        f"<!-- /personal-skills:slice:{name} -->\n"
    )
    agents = Path(repo) / "AGENTS.md"
    agents.write_text(("previo\n\n" if agents.exists() else "") + block, encoding="utf-8")
    return "sha256:" + hashlib.sha256((content + "\n").encode("utf-8")).hexdigest()


def make_repo(tmp, params=None, jobs=("lint",), extra_jobs=(), slice_name="APAP_WEB", files=("scripts/check_pr_size.py",)):
    repo = Path(tmp) / "repo"
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "jobs:\n"
        + "".join(f"  {j}:\n    runs-on: ubuntu-24.04\n" for j in jobs),
        encoding="utf-8",
    )
    hashes = {}
    for rel in files:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}\n", encoding="utf-8")
        hashes[rel] = sha(p)
    slice_hash = write_slice_block(repo, slice_name, "contenido del slice\nsegunda línea\n")
    params_path = repo / "ci-pattern.yaml"
    params_path.write_text(params if params is not None else VALID_PARAMS, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "adopted_at": "2026-10-02T12:00:00Z",
        "canonical_version": "0.4",
        "canonical_source": {"repo": "DysTelefonica/team-skills", "path": "personal/ardelperal/ci-pattern"},
        "parameters": {"P23_required_jobs": list(jobs) + list(extra_jobs)},
        "files": hashes,
        "slice_blocks": {slice_name: slice_hash},
    }
    (repo / ".governance-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return repo, params_path


def run_cli(argv, env_extra=None):
    out, err = io.StringIO(), io.StringIO()
    env = dict(os.environ)
    env["CI_PATTERN_SKILL_DIR"] = str(SKILL_DIR)
    if env_extra:
        env.update(env_extra)
    old = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = CLI.main(argv)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return code, out.getvalue(), err.getvalue()


class ParamsValidateTests(unittest.TestCase):
    def test_valid_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp)
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 0, out)

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp, params=INVALID["unknown_key"])
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 1)
            self.assertIn("P99_nonexistent", out)

    def test_missing_required_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp, params=INVALID["missing_required"])
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 1)
            self.assertIn("P18_health_url_var", out)

    def test_wrong_type_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp, params=INVALID["wrong_type"])
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 1)
            self.assertIn("P06_review_budget_lines", out)
            self.assertIn("integer", out)

    def test_bad_regex_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp, params=INVALID["bad_regex"])
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 1)
            self.assertIn("P01_branch_name_pattern", out)

    def test_bad_label_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp, params=INVALID["bad_label"])
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 1)
            self.assertIn("P10_label_approval", out)
            self.assertIn("prefijo:valor", out)

    def test_absolute_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, params = make_repo(tmp, params=INVALID["bad_path"])
            code, out, _ = run_cli(["params", "validate", str(params)])
            self.assertEqual(code, 1)
            self.assertIn("P41_gate_policy_path", out)

    def test_missing_file_is_exit_3(self):
        code, _, _ = run_cli(["params", "validate", "/nonexistent/ci-pattern.yaml"])
        self.assertEqual(code, 3)


class ManifestRoundTripTests(unittest.TestCase):
    def test_roundtrip_preserves_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            loaded = CLI.load_manifest(repo)
            raw = json.loads((repo / ".governance-manifest.json").read_text())
            self.assertEqual(loaded, raw)
            self.assertTrue(all(v.startswith("sha256:") for v in loaded["files"].values()))
            self.assertTrue(all(v.startswith("sha256:") for v in loaded["slice_blocks"].values()))

    def test_write_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo2"
            repo.mkdir()
            manifest = {
                "schema_version": 1,
                "adopted_at": "2026-10-02T00:00:00Z",
                "canonical_version": "0.4",
                "canonical_source": {"repo": "r", "path": "p"},
                "parameters": {},
                "files": {"a.txt": "sha256:" + "0" * 64},
                "slice_blocks": {},
            }
            CLI.write_manifest(repo, manifest)
            self.assertEqual(CLI.load_manifest(repo), manifest)


class VerifyTests(unittest.TestCase):
    def test_clean_repo_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            code, out, _ = run_cli(["verify", str(repo)])
            self.assertEqual(code, 0, out)
            self.assertIn("limpio", out)

    def test_modified_file_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            (repo / "scripts" / "check_pr_size.py").write_text("# editado localmente\n")
            code, out, _ = run_cli(["verify", str(repo)])
            self.assertEqual(code, 1)
            self.assertIn("locally-modified", out)
            self.assertIn("check_pr_size.py", out)

    def test_missing_gate_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp, extra_jobs=["pr-size"])  # workflows solo tienen lint
            code, out, _ = run_cli(["verify", str(repo)])
            self.assertEqual(code, 1)
            self.assertIn("gate-not-wired", out)
            self.assertIn("pr-size", out)

    def test_stale_slice_block_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            write_slice_block(repo, "APAP_WEB", "contenido EDITADO localmente\n")
            code, out, _ = run_cli(["verify", str(repo)])
            self.assertEqual(code, 1)
            self.assertIn("locally-modified", out)
            self.assertIn("APAP_WEB", out)

    def test_stale_vs_canonical_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as canon:
                repo, _ = make_repo(tmp)
                # la canónica tiene otro contenido: el consumer quedó desfasado
                (Path(canon) / "APAP_WEB.md").write_text("versión canónica nueva\n")
                code, out, _ = run_cli(["verify", str(repo), "--slice-canonical", canon])
                self.assertEqual(code, 1)
                self.assertIn("stale-vs-canonical", out)

    def test_json_output_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            code, out, _ = run_cli(["verify", str(repo), "--json"])
            payload = json.loads(out)
            self.assertEqual(code, 0)
            self.assertTrue(payload["clean"])
            self.assertEqual(payload["findings"], [])
            self.assertEqual(payload["canonical_comparison"], "skipped")

    def test_missing_manifest_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "vacio"
            repo.mkdir()
            code, out, _ = run_cli(["verify", str(repo)])
            self.assertEqual(code, 3)
            self.assertIn("adopt", out)


class StatusAndStubsTests(unittest.TestCase):
    def test_status_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            code, out, _ = run_cli(["status", str(repo)])
            self.assertEqual(code, 0, out)
            self.assertIn("files", out)

    def test_status_without_manifest_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "vacio"
            repo.mkdir()
            code, _, _ = run_cli(["status", str(repo)])
            self.assertEqual(code, 3)

    def test_adopt_is_future_wave(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            code, out, _ = run_cli(["adopt", str(repo)])
            self.assertEqual(code, 4)

    def test_update_is_future_wave(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp)
            code, _, _ = run_cli(["update", str(repo)])
            self.assertEqual(code, 4)

    def test_usage_error_exit_2(self):
        code, _, _ = run_cli(["comando-inexistente"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
