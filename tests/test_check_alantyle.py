"""Tests para el detector de anti-patrones documentation-alan-style §10.

Cubre los nueve códigos ALAN001-ALAN009 con casos positivos y
negativos, el mecanismo de escape ``<!-- alantyle-ignore -->`` y el
contrato CLI (exit codes 0/1/2).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_alantyle import (
    ACRONYM_WHITELIST,
    EXIT_OK,
    EXIT_USAGE_ERROR,
    EXIT_VIOLATIONS,
    Violation,
    find_violations,
    scan_markdown_content,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_alantyle.py"


def _scan(content: str, file_name: str = "test.md") -> list[Violation]:
    """Escanea el contenido markdown y devuelve las violaciones."""
    return scan_markdown_content(Path(file_name), content)


def _violations_for(code: str, content: str) -> list[Violation]:
    return [v for v in _scan(content) if v.code == code]


# --- ALAN001: frontmatter incompleto ---------------------------------------


def test_alan001_flags_missing_top_level_keys() -> None:
    """Falta `description` y `license`; se reportan dos violaciones."""
    content = (
        "---\n"
        "name: ejemplo\n"
        "---\n"
        "# Title\n"
    )
    matches = _violations_for("ALAN001", content)
    messages = " | ".join(v.message for v in matches)
    assert len(matches) >= 2, messages
    assert any("description" in v.message for v in matches)
    assert any("license" in v.message for v in matches)


def test_alan001_flags_missing_metadata_keys() -> None:
    """Falta metadata.author y metadata.version; se reportan ambos."""
    content = (
        "---\n"
        "name: ejemplo\n"
        "description: doc de prueba\n"
        "license: MIT\n"
        "metadata:\n"
        "  author: alguien\n"
        "---\n"
        "# Title\n"
    )
    matches = _violations_for("ALAN001", content)
    assert any("metadata.version" in v.message for v in matches), matches


def test_alan001_does_not_flag_complete_frontmatter() -> None:
    """Frontmatter completo: cero violaciones ALAN001."""
    content = (
        "---\n"
        "name: ejemplo\n"
        "description: doc de prueba\n"
        "license: MIT\n"
        "metadata:\n"
        "  author: alguien\n"
        "  version: 1.0.0\n"
        "---\n"
        "# Title\n"
    )
    matches = _violations_for("ALAN001", content)
    assert matches == [], matches


def test_alan001_skips_files_without_frontmatter() -> None:
    """Un markdown sin fence ``---`` al inicio no entra en ALAN001."""
    content = "# Title\n\nSin frontmatter.\n"
    assert _violations_for("ALAN001", content) == []


# --- ALAN002: emoji decorativo ---------------------------------------------


def test_alan002_flags_emoji_in_body() -> None:
    """El cohete en una línea de cuerpo dispara ALAN002."""
    content = "# Title\n\nAquí va un cohete decorativo: 🚀\n"
    matches = _violations_for("ALAN002", content)
    assert len(matches) == 1, matches
    assert matches[0].line == 3


def test_alan002_ignores_emoji_inside_code_block() -> None:
    """El emoji dentro de un bloque de código NO dispara ALAN002."""
    content = "# Title\n\n```bash\n# 🚀 no es decorativo aquí\necho hi\n```\n"
    assert _violations_for("ALAN002", content) == []


def test_alan002_honors_alantyle_ignore_marker() -> None:
    """El marcador genérico suprime ALAN002 en esa línea."""
    content = "# Title\n\nAquí va un cohete decorativo: 🚀 <!-- alantyle-ignore -->\n"
    assert _violations_for("ALAN002", content) == []


def test_alan002_honors_code_specific_ignore_marker() -> None:
    """El marcador específico ALAN002 suprime solo ese código."""
    content = "# Title\n\nAquí va un cohete decorativo: 🚀 <!-- alantyle-ignore:ALAN002 -->\n"
    assert _violations_for("ALAN002", content) == []


def test_alan002_does_not_flag_plain_text() -> None:
    """Texto sin emoji no dispara ALAN002."""
    content = "# Title\n\nSolo texto neutro, sin iconos.\n"
    assert _violations_for("ALAN002", content) == []


# --- ALAN003: ALL CAPS fuera de la whitelist ------------------------------


def test_alan003_flags_non_whitelisted_allcaps() -> None:
    """``AMAZING`` (no whitelisted) dispara ALAN003."""
    content = "# Title\n\nThis guide is AMAZING.\n"
    matches = _violations_for("ALAN003", content)
    assert len(matches) == 1, matches
    assert matches[0].message.startswith("secuencia en mayúsculas 'AMAZING'")


def test_alan003_accepts_whitelisted_acronyms() -> None:
    """Los acrónimos whitelisted (HTTP, MCP, etc.) NO disparan ALAN003."""
    content = (
        "# Title\n\n"
        "HTTP 200. MCP server. SQL query. INSFORGE client. "
        "API endpoint. PR review. URL shortener. SHA digest.\n"
    )
    assert _violations_for("ALAN003", content) == []


def test_alan003_acronym_followed_by_digit_is_not_flagged() -> None:
    """``ALAN001`` y ``SHA256`` tienen letras mayúsculas seguidas de
    dígitos. No hay límite de palabra entre la última letra y el primer
    dígito, así que la regex ``\\b[A-Z]{2,}\\b`` no las cuenta."""
    content = "# Title\n\nCódigos ALAN001 y SHA256.\n"
    assert _violations_for("ALAN003", content) == []


def test_alan003_ignore_marker_suppresses_one_line() -> None:
    """El marcador genérico suprime ALAN003 en esa línea."""
    content = "# Title\n\nAcción FINAL <!-- alantyle-ignore -->\n"
    assert _violations_for("ALAN003", content) == []


def test_alan003_does_not_flag_sentence_case_headings() -> None:
    """Headings en sentence case no contienen secuencias ALL CAPS."""
    content = "# Title\n\n## Quick start\n\nBien.\n"
    assert _violations_for("ALAN003", content) == []


@pytest.mark.parametrize(
    "keyword",
    ["GIVEN", "WHEN", "THEN", "AND", "DADO", "CUANDO", "ENTONCES"],
)
def test_alan003_accepts_openspec_scenario_markers(keyword: str) -> None:
    """Los marcadores estructurales de escenarios no son énfasis en prosa."""
    for marker in (keyword, f"**{keyword}**"):
        content = f"# Title\n\n- {marker} se cumple la precondición\n"
        assert _violations_for("ALAN003", content) == [], marker


def test_alan003_still_flags_scenario_words_used_as_prose_emphasis() -> None:
    """La excepción estructural no relaja las mismas palabras en prosa."""
    content = "# Title\n\nThis happens WHEN the condition changes.\n"
    matches = _violations_for("ALAN003", content)
    assert [match.code for match in matches] == ["ALAN003"]


# --- ALAN003: inline code masking (issue #578) -----------------------------


def test_alan003_ignores_allcaps_inside_inline_code() -> None:
    """Keywords SQL dentro de backticks son código, no prosa (issue #578)."""
    content = (
        "# Title\n\n"
        "Validación: `SELECT id FROM animales WHERE id = $1 AND activo = true`.\n"
    )
    assert _violations_for("ALAN003", content) == []


def test_alan003_flags_allcaps_outside_inline_code_same_line() -> None:
    """El masking solo cubre el span entre backticks; la prosa de la misma
    línea sigue evaluándose."""
    content = "# Title\n\nUsa `SELECT 1` pero el término AMAZING queda fuera.\n"
    matches = _violations_for("ALAN003", content)
    assert [m.message.split("'")[1] for m in matches] == ["AMAZING"]


def test_alan003_inline_code_mask_preserves_columns() -> None:
    """Las columnas reportadas coinciden con la línea cruda tras el masking."""
    content = "# Title\n\n`SELECT FROM` y luego WHERE en prosa.\n"
    matches = _violations_for("ALAN003", content)
    assert len(matches) == 1
    # "WHERE" empieza en la columna 20 de la línea cruda.
    line = content.splitlines()[2]
    assert matches[0].column == line.index("WHERE") + 1


# --- ALAN003: spec-context whitelist (issue #578) --------------------------


def _scan_as(content: str, file_name: str) -> list[Violation]:
    return [
        v
        for v in scan_markdown_content(Path(file_name), content)
        if v.code == "ALAN003"
    ]


@pytest.mark.parametrize(
    "keyword",
    ["MUST", "SHALL", "SHOULD", "MAY", "NOT", "GIVEN", "WHEN", "THEN"],
)
def test_alan003_spec_context_allows_rfc2119_and_bdd(keyword: str) -> None:
    """Bajo openspec/ las keywords RFC 2119 y BDD son lenguaje semántico de
    spec, no emph (issue #578)."""
    content = f"# Title\n\nEl sistema {keyword} validar la entrada.\n"
    assert _scan_as(content, "openspec/specs/foo/spec.md") == []


@pytest.mark.parametrize(
    "keyword",
    ["DEBE", "DEBEN", "NO", "YA", "DOS", "SIN", "PASA", "FALLA"],
)
def test_alan003_spec_context_allows_spanish_scenario_vocab(keyword: str) -> None:
    """El vocabulario de escenario en castellano es legítimo bajo openspec/."""
    content = f"# Title\n\n- THEN el resultado {keyword} correcto.\n"
    assert _scan_as(content, "openspec/changes/x/specs/y/spec.md") == []


@pytest.mark.parametrize(
    "keyword",
    ["MUST", "SHALL", "NOT", "WHEN", "THEN"],
)
def test_alan003_docs_still_flag_emph_outside_openspec(keyword: str) -> None:
    """Fuera de openspec/ las mismas palabras siguen siendo emph y se
    reportan; el guardrail de docs permanece activo (issue #578)."""
    content = f"# Title\n\nEl sistema {keyword} validar la entrada.\n"
    matches = _scan_as(content, "docs/guide.md")
    assert [m.message.split("'")[1] for m in matches] == [keyword]


# --- Exclusión de archive (issue #578) -------------------------------------


def test_archive_paths_are_excluded(tmp_path: Path) -> None:
    """openspec/changes/archive es histórico inmutable y queda fuera del gate."""
    from scripts.check_alantyle import _is_excluded_path

    archived = tmp_path / "openspec" / "changes" / "archive" / "x" / "spec.md"
    active = tmp_path / "openspec" / "changes" / "live" / "specs" / "spec.md"
    assert _is_excluded_path(archived) is True
    assert _is_excluded_path(active) is False


# --- ALAN004: lenguaje ambiguo ---------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "we recommend",
        "best practice",
        "sería bueno",
        "podría",
        "would be",
        "could potentially",
        "maybe consider",
        "it's a good idea",
    ],
)
def test_alan004_flags_each_ambiguous_phrase(phrase: str) -> None:
    """Cada frase de la lista de la skill dispara ALAN004."""
    content = f"# Title\n\n{phrase} hacer esto así.\n"
    matches = _violations_for("ALAN004", content)
    assert len(matches) == 1, f"phrase={phrase!r} matches={matches}"
    assert phrase in matches[0].message


def test_alan004_does_not_flag_imperative() -> None:
    """Una frase en imperativo directo no dispara ALAN004."""
    content = "# Title\n\nUse pytest para correr los tests.\n"
    assert _violations_for("ALAN004", content) == []


def test_alan004_ignore_marker_specific_to_alan004() -> None:
    """El marcador específico ALAN004 suprime la detección."""
    content = "# Title\n\nwe recommend pip install foo <!-- alantyle-ignore:ALAN004 -->\n"
    assert _violations_for("ALAN004", content) == []


# --- ALAN005: marketing fluff ----------------------------------------------


@pytest.mark.parametrize(
    "word",
    [
        "amazing",
        "powerful",
        "world-class",
        "game-changer",
        "easy to use",
        "simple yet",
        "guaranteed",
        "seamless",
        "cutting-edge",
        "next-generation",
        "revolutionary",
    ],
)
def test_alan005_flags_each_marketing_word(word: str) -> None:
    """Cada palabra de la lista de marketing fluff dispara ALAN005."""
    content = f"# Title\n\nThis tool is {word}.\n"
    matches = _violations_for("ALAN005", content)
    assert len(matches) == 1, f"word={word!r} matches={matches}"


def test_alan005_does_not_flag_neutral_vocabulary() -> None:
    """Vocabulario neutro no dispara ALAN005."""
    content = "# Title\n\nLa herramienta procesa los datos.\n"
    assert _violations_for("ALAN005", content) == []


def test_alan005_ignores_word_inside_code_block() -> None:
    """Una palabra de marketing dentro de un bloque de código NO dispara
    ALAN005 (las herramientas reales pueden nombrar APIs así)."""
    content = "# Title\n\n```bash\n# use the amazing-cli\n```\n"
    assert _violations_for("ALAN005", content) == []


# --- ALAN006: más de seis enlaces externos ---------------------------------


def test_alan006_flags_seven_external_links() -> None:
    """Siete enlaces externos disparan ALAN006 una sola vez."""
    body = "\n".join(f"[link {i}](https://example{i}.com)" for i in range(7))
    content = f"# Title\n\n{body}\n"
    matches = _violations_for("ALAN006", content)
    assert len(matches) == 1, matches
    assert "7" in matches[0].message


def test_alan006_accepts_six_external_links() -> None:
    """Seis enlaces externos NO disparan ALAN006."""
    body = "\n".join(f"[link {i}](https://example{i}.com)" for i in range(6))
    content = f"# Title\n\n{body}\n"
    assert _violations_for("ALAN006", content) == []


def test_alan006_counts_only_http_or_https() -> None:
    """Los enlaces relativos y los anclas no cuentan para ALAN006."""
    body = "\n".join(f"[link {i}](relative-{i}.md)" for i in range(10))
    content = f"# Title\n\n{body}\n"
    assert _violations_for("ALAN006", content) == []


# --- ALAN007: párrafo > 200 chars sin punto --------------------------------


def test_alan007_flags_long_paragraph_without_period() -> None:
    """Un párrafo largo sin punto dispara ALAN007 en su primera línea."""
    body = (
        "Lorem ipsum dolor sit amet consectetur adipiscing elit, sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua, ut "
        "enim ad minim veniam, quis nostrud exercitation ullamco laboris "
        "nisi ut aliquip ex ea commodo consequat duis aute irure dolor in "
        "reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla"
    )
    content = f"# Title\n\n{body}\n"
    matches = _violations_for("ALAN007", content)
    assert len(matches) == 1, matches


def test_alan007_accepts_long_paragraph_with_period() -> None:
    """Un párrafo largo con punto NO dispara ALAN007."""
    body = (
        "Lorem ipsum dolor sit amet. Consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna "
        "aliqua. Ut enim ad minim veniam. Quis nostrud exercitation."
    )
    content = f"# Title\n\n{body}\n"
    assert _violations_for("ALAN007", content) == []
def test_alan007_does_not_flag_short_paragraphs() -> None:
    """Párrafos cortos (<= 200 chars) no disparan ALAN007."""
    content = "# Title\n\nPárrafo breve.\n\nOtro párrafo breve.\n"
    assert _violations_for("ALAN007", content) == []


@pytest.mark.parametrize(
    "body",
    [
        "| Columna | Valor |\n|---|---|\n" + "| dato | valor largo |\n" * 20,
        "\n".join(f"- Elemento estructural {index}" for index in range(30)),
        "\n".join(f"> Línea citada {index}" for index in range(30)),
    ],
)
def test_alan007_ignores_non_paragraph_markdown_blocks(body: str) -> None:
    """Tablas, listas y citas no se concatenan como párrafos de prosa."""
    content = f"# Title\n\n{body}\n"
    assert _violations_for("ALAN007", content) == []


def test_alan007_breaks_at_heading() -> None:

    """Un heading rompe el párrafo, así que cada sección se mide aparte."""
    long_para = "x" * 250
    content = f"# Title\n\n{long_para}\n\n## Section\n\n{long_para}.\n"
    matches = _violations_for("ALAN007", content)
    # Solo el primer párrafo (sin punto) debe disparar; el segundo tiene
    # punto y no dispara.
    assert len(matches) == 1, matches
    assert matches[0].line == 3


# --- ALAN008: TOC auto-generada --------------------------------------------


def test_alan008_flags_toc_html_comment() -> None:
    """El marcador ``<!-- toc -->`` cerca del top dispara ALAN008."""
    content = "# Title\n\n<!-- toc -->\n\n- Item 1\n- Item 2\n"
    matches = _violations_for("ALAN008", content)
    assert len(matches) == 1, matches
    assert matches[0].line == 3


def test_alan008_flags_toc_tag() -> None:
    """El marcador ``<TOC>`` también dispara ALAN008."""
    content = "# Title\n\n<TOC>\n\n## Section\n"
    matches = _violations_for("ALAN008", content)
    assert len(matches) == 1, matches


def test_alan008_does_not_flag_legitimate_index() -> None:
    """Una lista explícita NO es un marcador de TOC auto-generada."""
    content = "# Title\n\n- Section A\n- Section B\n\n## Section A\n"
    assert _violations_for("ALAN008", content) == []


def test_alan008_ignores_marker_below_top_limit() -> None:
    """El marcador por debajo de la línea 50 NO entra en ALAN008."""
    body = "\n".join("# filler" for _ in range(60))
    content = f"{body}\n<!-- toc -->\n"
    assert _violations_for("ALAN008", content) == []


# --- ALAN009: instalación al final ----------------------------------------


def test_alan009_flags_install_heading_at_end() -> None:
    """Un heading ``## Installation`` tras la mitad dispara ALAN009."""
    body = "\n".join(f"# Section {i}\n\nFiller.\n" for i in range(6))
    content = f"# Title\n\n{body}\n## Installation\n\nLast steps.\n"
    matches = _violations_for("ALAN009", content)
    assert len(matches) == 1, matches


def test_alan009_accepts_install_heading_at_top() -> None:
    """Un heading ``## Installation`` temprano NO dispara ALAN009."""
    content = (
        "# Title\n"
        "\n"
        "## Installation\n"
        "\n"
        "Quick start.\n"
        "\n"
        "## Other section\n"
        "\n"
        "Details.\n"
    )
    assert _violations_for("ALAN009", content) == []


def test_alan009_accepts_no_install_heading() -> None:
    """Un documento sin sección de instalación NO dispara ALAN009."""
    content = "# Title\n\n## Quick path\n\nSteps.\n\n## Reference\n\nDetails.\n"
    assert _violations_for("ALAN009", content) == []


# --- Mecanismo de escape global --------------------------------------------


def test_ignore_marker_suppresses_all_detectors_on_line() -> None:
    """Una línea con ``<!-- alantyle-ignore -->`` no emite violaciones."""
    content = (
        "# Title\n\n"
        "This is AMAZING. <!-- alantyle-ignore -->\n"
        "we recommend. <!-- alantyle-ignore -->\n"
        "amazing tool. <!-- alantyle-ignore -->\n"
    )
    matches = _scan(content)
    assert matches == [], matches


def test_ignore_marker_specific_to_one_code_does_not_suppress_others() -> None:
    """Un marcador ``ALAN004`` suprime ALAN004 pero no los demás códigos."""
    content = (
        "# Title\n\n"
        "This is amazing. <!-- alantyle-ignore:ALAN005 -->\n"
        "we recommend running it.\n"
    )
    matches = _scan(content)
    codes = sorted({v.code for v in matches})
    assert "ALAN005" not in codes
    assert "ALAN004" in codes


# --- Contrato CLI ---------------------------------------------------------


def test_cli_exit_zero_when_no_violations(tmp_path: Path) -> None:
    clean = tmp_path / "clean.md"
    clean.write_text(
        "# Title\n\nPárrafo breve en sentence case.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(clean)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_OK, (
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cli_exit_one_when_violations_present(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.md"
    dirty.write_text(
        "# Title\n\nThis is AMAZING.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(dirty)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_VIOLATIONS, (
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ALAN003" in result.stderr


def test_cli_exit_two_on_usage_error() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_USAGE_ERROR, (
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cli_recurses_into_directories(tmp_path: Path) -> None:
    nested = tmp_path / "sub"
    nested.mkdir()
    dirty = nested / "deep.md"
    dirty.write_text("# Title\n\nThis is AMAZING.\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_VIOLATIONS, (
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cli_ignores_non_markdown_files(tmp_path: Path) -> None:
    """Pasar un `` ``.py`` no produce error ni violaciones."""
    py_file = tmp_path / "script.py"
    py_file.write_text("EXIT_OK = 0\nAMAZING = True\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(py_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_OK, (
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


# --- Regresiones del gate bloqueante (issue #582) ---------------------------
#
# Estos tests corren el CLI real y pinea que tres correcciones estructurales
# del detector (inline-code masking, whitelist spec-context, exclusión de
# archive/) sigan activas. Si alguien las desactiva, un CI que hoy pasa
# empezaría a fallar y este test detectaría la regresión antes de que
# llegue a main.


def test_cli_inline_code_masking_prevents_sql_false_positive(
    tmp_path: Path,
) -> None:
    """SQL dentro de backticks no dispara ALAN003 (issue #578).

    Si alguien elimina la llamada a ``_mask_inline_code`` dentro de
    ``_check_allcaps``, palabras como FROM/WHERE/AND dentro de ``SELECT ...``
    dispararían la violación y este test fallaría.
    """
    doc = tmp_path / "guide.md"
    doc.write_text(
        "# Title\n\n"
        "Validación: `SELECT id FROM animales WHERE id = $1 AND activo = true`.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(doc)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_OK, (
        f"inline-code masking se desactivó: stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_cli_spec_context_whitelist_allows_rfc2119_in_openspec(
    tmp_path: Path,
) -> None:
    """RFC 2119 + BDD bajo openspec/ no se reportan como emph (issue #578).

    Crea un archivo cuya ruta contiene ``openspec`` en ``Path.parts``;
    las keywords MUST/SHALL/GIVEN/WHEN/THEN deben pasar gracias al
    frozenset independiente ``_SPEC_CONTEXT_KEYWORDS``. Si alguien lo
    elimina, el test falla con violaciones ALAN003.
    """
    spec = tmp_path / "openspec" / "specs" / "foo" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "# Title\n\n"
        "El sistema MUST validar la entrada. "
        "**GIVEN** un usuario, WHEN recibe payload, THEN responde 201.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(spec)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_OK, (
        f"spec-context whitelist se desactivó: stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_cli_archive_exclusion_skips_historical_changes(tmp_path: Path) -> None:
    """``openspec/changes/archive/`` queda fuera del gate (issue #578).

    Crea un árbol con: (a) un archivo en ``archive/`` con una violación
    ALAN003 que DEBE ignorarse, y (b) un archivo en un change activo
    sin violaciones. El resultado debe ser exit 0. Si alguien quita
    ``archive`` de ``_EXCLUDED_DIR_SEGMENTS``, la violación del histórico
    rompe el gate.
    """
    archived = tmp_path / "openspec" / "changes" / "archive" / "x" / "spec.md"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        "# Title\n\nThis is AMAZING.\n",
        encoding="utf-8",
    )
    active = tmp_path / "openspec" / "changes" / "live" / "specs" / "live" / "spec.md"
    active.parent.mkdir(parents=True)
    active.write_text(
        "# Title\n\nTexto limpio en sentence case.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_OK, (
        f"archive exclusion se desactivó: stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_cli_real_alant003_violation_still_fails(tmp_path: Path) -> None:
    """Anti-patrón real (EMPH no whitelisted) sigue fallando el gate.

    Pin contra alguien que desactive el detector (e.g. un ``return []``
    silencioso al inicio de ``_check_allcaps``). Si el detector deja de
    reportar, este test falla.
    """
    dirty = tmp_path / "guide.md"
    dirty.write_text(
        "# Title\n\nThis is AMAZING.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(dirty)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_VIOLATIONS, (
        f"el detector no reportó ALAN003: stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )
    assert "ALAN003" in result.stderr


# --- find_violations sobre archivos ---------------------------------------


def test_find_violations_returns_sorted_output(tmp_path: Path) -> None:
    """Los hallazgos salen ordenados por archivo y línea."""
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("# Title\n\nThis is AMAZING.\n", encoding="utf-8")
    b.write_text("# Title\n\nThis is POWERFUL.\n", encoding="utf-8")
    result = find_violations([tmp_path])
    lines = [v.line for v in result]
    files = [v.file.name for v in result]
    assert files == sorted(files), files
    assert lines == sorted(lines), lines


# --- Sanity de la whitelist ------------------------------------------------


def test_acronym_whitelist_contains_skill_listed_entries() -> None:
    """La whitelist incluye literalmente los siete acrónimos de §10."""
    expected = {"HTTP", "MCP", "SQL", "INSFORGE", "API", "PR", "URL", "SHA"}
    assert expected.issubset(ACRONYM_WHITELIST), (
        f"missing from whitelist: {expected - ACRONYM_WHITELIST}"
    )


def test_expanded_whitelist_accepts_common_technical_acronyms() -> None:
    """Las abreviaturas técnicas comunes no disparan ALAN003 (§10 skill)."""
    allowed = (
        "ACCDB ACID AGI AI AMQP APAP APM ARG ARIAC ASGI AWS AZURE "
        "BD BDD BFF BI BLOCKER CD CDN CET CIDR CLI CMD CODEOWNERS COM CORS CSP CRUD CSRF CSS CSV CTE "
        "DAG DAO DB DDD DDL DELETE DI DIP DNI DNS DOCX DOB DOM DRF DSN EHR ELT EOL ERD ETL EU EXE "
        "FAQ FK FTP FTS FSO GCP GDPR GET GMT GNU GRPC GUID HEAD HMAC HIPAA HSTS HTMX HTTPX HTTPS "
        "IaaS ID IEEE IMAP INFO INFORGE IP ISO JS JSONB JWE JWS JWT K8S KB KPI LF LINUX LLM LOC LSP LTS MD ML MQTT "
        "MSACCESS MVC MVCC NASA NFKD NIE NIF NIST NLP NOSQL OCR OECD OOM OPTIONS ORM OS OSS "
        "PaaS PATCH PDF PEP PG PHI PID PII PK PKCE PNG POC POP POSIX POST PTY PUT PWA PYTHONHASHSEED PYTHONPATH QA "
        "RAG RBAC RDBMS RDD REQ REST RFC RIAC RLS ROI SAAS SDD SDK SEO SIGINT SLA SLI SLO SMTP SOA SOAP SOC SOLID SOX SPA "
        "SSL SSH STDERR STDIN STDOUT SVG TBD TCP TDD TLD TLS TOCTOU TS TSV TTL UA UAT UDP UI UK UN URI URN "
        "USA UTC UUID UX VBA VPN VPS WHO WIP WS WSL WSS WWW XSS YAML YYYY"
    ).split()
    for acronym in allowed:
        line = f"ejemplo con {acronym} permitido"
        assert _violations_for("ALAN003", f"# Title\n\n{line}\n") == [], acronym

    headers = "WWW-Authenticate y X-Request-ID son cabeceras permitidas"
    assert _violations_for("ALAN003", f"# Title\n\n{headers}\n") == []


# --- Whitelist v2 (issue #572): SQL keywords + APAP_WEB domain terms -------


@pytest.mark.parametrize(
    "acronym",
    [
        # SQL / DB keywords (issue #572, categoría 1)
        "ALTER",
        "AUTOINCREMENT",
        "BOOLEAN",
        "CASCADE",
        "CRAP",
        "CREATE",
        "DEFAULT",
        "DISTINCT",
        "DROP",
        "EXISTS",
        "FALSE",
        "INSERT",
        "NOW",
        "NULL",
        "REFERENCES",
        "RESTRICT",
        "RETURNING",
        "SELECT",
        "SET",
        "TABLE",
        "TIMESTAMP",
        "TRUE",
        "UNIQUE",
        "UPDATE",
        # Severidad + estados de CI (issue #572, categorías 1+2)
        "BLOCKED",
        "CRITICAL",
        "FAIL",
        "HIGH",
        "LOW",
        "MEDIUM",
        "PASS",
        "PENDING",
        # Marcadores técnicos heredados (issue #572)
        "XXX",
    ],
)
def test_whitelist_v2_accepts_sql_and_ci_terms(acronym: str) -> None:
    """Los keywords SQL y estados de CI no disparan ALAN003 (issue #572).

    Categoría 1 del issue #572: ``NULL``, ``DEFAULT``, ``CASCADE``,
    ``AUTOINCREMENT``, etc. son keywords reservados del estándar SQL/ANSI
    que aparecen en prosa cuando los docs describen constraints y
    queries; tratarlos como emph generaba falsos positivos.
    """
    content = f"# Title\n\ncaso aislado con {acronym} en docs\n"
    matches = _violations_for("ALAN003", content)
    assert matches == [], f"acronym={acronym!r} matches={matches}"


@pytest.mark.parametrize(
    "acronym",
    [
        # Términos del dominio APAP_WEB (issue #572, categoría 2)
        "ADOPT",
        "BASELINE",
        "CANINA",
        "CC",
        "DOC",
        "FELINA",
        "FOSTER",
        "HEALTH",
        "IA",
        "LIFECYCLE",
        "MIGRATION",
        "NCHIP",
        "RED",
        "REPORT",
        "SALUD",
        "SKILL",
        "VOL",
        "XX",
    ],
)
def test_whitelist_v2_accepts_apap_domain_terms(acronym: str) -> None:
    """Los términos del dominio APAP_WEB no disparan ALAN003 (issue #572).

    Categoría 2 del issue #572: ``LIFECYCLE``, ``FOSTER``, ``CANINA``,
    ``FELINA``, ``VOL``, ``NCHIP``, ``CC`` son del dominio semántico del
    proyecto (gestión de protectoras de animales). ``XX`` es el
    placeholder de ``D-XX`` (ADR) y ``feature-XX-*``. ``RED`` es la fase
    RED de TDD. ``REPORT`` es el prefijo de issues de informes.
    """
    content = f"# Title\n\ncaso de uso con {acronym} en dominio\n"
    assert _violations_for("ALAN003", content) == [], acronym


def test_whitelist_v2_does_not_relax_emph_words() -> None:
    """La whitelist final no relaja palabras genéricas usadas como énfasis."""
    emph_words = (
        "IF",
        "NOT",
        "NO",
        "FROM",
        "WHERE",
        "IN",
        "ON",
        "OR",
        "AND",
        "IS",
        "ONE",
        "AS",
        "BY",
        "ONLY",
        "NEVER",
        "HARD",
        "FINAL",
        "BEFORE",
        "AFTER",
        "ALWAYS",
        "ANY",
        "NOTE",
        "TODO",
        "FIXME",
        "MUST",
        "SHALL",
        "SHOULD",
        "GIVEN",
        "WHEN",
        "THEN",
        "DE",
        "EN",
        "ES",
        "EL",
        "LA",
        "POR",
        "PARA",
    )
    for word in emph_words:
        assert word not in ACRONYM_WHITELIST, (
            f"emph word {word!r} leaked into the whitelist — fix the "
            "document or use a selective ignore instead"
        )


@pytest.mark.parametrize(
    "acronym",
    [
        "ADD",
        "ASC",
        "BEGIN",
        "BIGSERIAL",
        "CHECK",
        "COLUMN",
        "COMMIT",
        "CONSTRAINT",
        "COUNT",
        "DATE",
        "DATEDIFF",
        "DESC",
        "DOMAIN",
        "EXTENSION",
        "GROUP",
        "HAVING",
        "ILIKE",
        "INDEX",
        "INNER",
        "INT",
        "INTEGER",
        "INTERVAL",
        "INTO",
        "JOIN",
        "LAST",
        "LIMIT",
        "NULLS",
        "ORDER",
        "ROLLBACK",
        "SAVEPOINT",
        "SCHEMA",
        "SEED",
        "SERIAL",
        "SUM",
        "TEXT",
        "TIMESTAMPTZ",
        "TRANSACTION",
        "TRIGGER",
        "TRUNCATE",
        "TYPE",
        "UNION",
        "VIEW",
    ],
)
def test_whitelist_v3_accepts_sql_db_terms(acronym: str) -> None:
    """Los tipos y keywords SQL/DB no disparan ALAN003."""
    assert _violations_for("ALAN003", f"# Title\n\n{acronym}\n") == []


@pytest.mark.parametrize(
    "acronym",
    [
        "ACOGIDA",
        "ADM",
        "ADOPTADO",
        "ADOPTION",
        "ALBERGUE",
        "AVES",
        "CANCELADA",
        "COMPLETADA",
        "CONTRATO",
        "ENTREGADO",
        "FALLECIDO",
        "FICHERO",
        "FIMPLANTACIONCHIP",
        "IFI",
        "INCOHERENTE",
        "INTAKE",
        "MANUAL",
        "MATERIAL",
        "OPERADOR",
        "PARIDAD",
        "PENDIENTE",
        "PPP",
        "PTE",
        "READONLY",
        "REMOVIDO",
        "REPORTE",
        "REPORTES",
        "RESPONSABLE",
        "SEGUIMIENTO",
        "TERAPIA",
        "TERAPIAS",
        "VOLUNTARIOS",
    ],
)
def test_whitelist_v3_accepts_apap_domain_terms(acronym: str) -> None:
    """Los nombres del dominio APAP_WEB no disparan ALAN003."""
    assert _violations_for("ALAN003", f"# Title\n\n{acronym}\n") == []


@pytest.mark.parametrize(
    "acronym",
    [
        "CATALOG",
        "CP",
        "CRIT",
        "DD",
        "DM",
        "DS",
        "ENV",
        "EST",
        "FE",
        "FIDELITY",
        "FOUNDATION",
        "GAP",
        "GC",
        "HOME",
        "IDINTAKE",
        "IDENTRADA",
        "IDADOPCION",
        "IDRIAC",
        "IDFOSTER",
        "IDCONTRATOACOGIDA",
        "NCONTRATOENTRADA",
        "NCONTRATOACOGIDA",
        "IFC",
        "LEUC",
        "LH",
        "MM",
        "REG",
        "ROUTE",
        "SB",
        "SCOPE",
        "SECRET",
        "SERVICE",
        "TASK",
        "UP",
        "WORKER",
    ],
)
def test_whitelist_v3_accepts_repo_internal_terms(acronym: str) -> None:
    """Los IDs, prefijos y nombres internos del repo no disparan ALAN003."""
    assert _violations_for("ALAN003", f"# Title\n\n{acronym}\n") == []


@pytest.mark.parametrize(
    "acronym",
    [
        "ACQUISITION",
        "ADDED",
        "ADDITIONS",
        "ADMIN",
        "ALLOW",
        "APPROVED",
        "ARCHIVED",
        "CHILD",
        "CLOSED",
        "DELETED",
        "DENY",
        "DEVELOPER",
        "DISABLED",
        "DONE",
        "DORMANT",
        "DRAFT",
        "ENABLED",
        "FIXED",
        "GREEN",
        "IMPLEMENTED",
        "INCOMPETENT",
        "KILLED",
        "MERGED",
        "OPEN",
        "PROVISIONAL",
        "READER",
        "REDACTED",
        "REFACTOR",
        "REJECT",
        "ROTA",
        "SKIPPED",
        "STACK",
        "SUGGESTION",
        "SUPERSEDED",
        "TRACKED",
        "UPDATED",
        "WARN",
        "WARNING",
    ],
)
def test_whitelist_v3_accepts_status_role_and_change_terms(acronym: str) -> None:
    """Los estados, roles y marcadores de cambio no disparan ALAN003."""
    assert _violations_for("ALAN003", f"# Title\n\n{acronym}\n") == []


@pytest.mark.parametrize(
    "acronym",
    [
        "AA",
        "CAS",
        "CTA",
        "FD",
        "ISP",
        "PERMISSIONS",
        "RQ",
        "SECURITY",
        "SMS",
        "SO",
        "USERNAME",
        "WCAG",
        "YY",
    ],
)
def test_whitelist_v3_accepts_specific_technical_terms(acronym: str) -> None:
    """Las abreviaturas técnicas verificadas en el repo no disparan ALAN003."""
    assert _violations_for("ALAN003", f"# Title\n\n{acronym}\n") == []
