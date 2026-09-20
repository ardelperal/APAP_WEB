import json
import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_FILE = SKILL_ROOT / "SKILL.md"
ASSETS_ROOT = SKILL_ROOT / "assets"
EXEMPTIONS_FILE = Path(__file__).with_name("provenance-exemptions.json")


def _skill_text() -> str:
    return SKILL_FILE.read_text(encoding="utf-8")


def _skill_version() -> str:
    match = re.search(r'^\s*version:\s*["\']?([^"\'\s]+)', _skill_text(), re.MULTILINE)
    assert match, "SKILL.md frontmatter must declare metadata.version"
    return match.group(1)


def _local_markdown_targets() -> set[str]:
    text = _skill_text()
    linked = re.findall(r"\[[^]]+\]\((?!https?://|#)([^)#]+\.md)(?:#[^)]+)?\)", text)
    code_spans = re.findall(r"`([^`\s]+\.md)`", text)
    return set(linked + code_spans)


def test_runtime_contract_stays_compact() -> None:
    lines = _skill_text().splitlines()
    assert len(lines) <= 140, f"SKILL.md has {len(lines)} lines; move detail to references/"


def test_runtime_contract_preserves_required_sections() -> None:
    text = _skill_text()
    required = {
        "## Activation Contract",
        "## Hard Rules",
        "## Decision Gates",
        "## Execution Steps",
        "## Output Contract",
        "## Assets",
    }
    assert required <= set(text.splitlines())


def test_every_local_markdown_reference_exists() -> None:
    targets = _local_markdown_targets()
    assert targets, "SKILL.md must link to its detailed local references"
    missing = sorted(target for target in targets if not (SKILL_ROOT / target).is_file())
    assert not missing, f"Missing local references: {missing}"


def test_asset_catalogs_include_gate_liveness_test() -> None:
    assert "assets/tests/test_gate_liveness.py" in _skill_text()
    readme = (ASSETS_ROOT / "README.md").read_text(encoding="utf-8")
    assert "tests/test_gate_liveness.py" in readme


def test_asset_provenance_matches_skill_version_or_has_explicit_exemption() -> None:
    version = _skill_version()
    marker = f"HARNESS-PROVENANCE: deterministic-quality-harness v{version}"
    exemptions = json.loads(EXEMPTIONS_FILE.read_text(encoding="utf-8"))
    assert all(reason.strip() for reason in exemptions.values())

    asset_paths = sorted(
        path
        for path in ASSETS_ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
        and path.suffix != ".pyc"
    )
    relative_assets = {path.relative_to(SKILL_ROOT).as_posix() for path in asset_paths}
    assert set(exemptions) <= relative_assets, "Provenance exemptions must name existing assets"

    mismatches = []
    for path in asset_paths:
        relative = path.relative_to(SKILL_ROOT).as_posix()
        if relative in exemptions:
            continue
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            mismatches.append(relative)

    assert not mismatches, f"Assets without {marker!r}: {mismatches}"
