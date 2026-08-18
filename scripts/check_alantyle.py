"""Linter for §10 anti-patterns of the documentation-alan-style skill (v2.2).

Detecta nueve violaciones en archivos markdown:

- ALAN001: frontmatter YAML sin los campos obligatorios
  (name, description, license, metadata.author, metadata.version).
- ALAN002: emojis decorativos en headings o cuerpo.
- ALAN003: ALL CAPS fuera de los acrónimos técnicos y nombres propios
  whitelisted (HTTP, MCP, SQL, etc.; la lista no es cerrada).
- ALAN004: lenguaje ambiguo (we recommend, best practice, sería
  bueno, podría, etc.) en lugar de imperativo directo.
- ALAN005: marketing fluff (amazing, powerful, world-class, etc.).
- ALAN006: más de seis enlaces externos en un mismo archivo.
- ALAN007: párrafos de más de doscientos caracteres sin punto y aparte.
- ALAN008: tabla de contenidos auto-generada cerca del top del documento.
- ALAN009: sección de instalación al final del documento.

Solo dependencias de la biblioteca estándar. Uso::

    python scripts/check_alantyle.py <ruta> [<ruta>...]

``<ruta>`` puede ser un archivo ``.md`` o un directorio (recursivo).

Exit codes:

    0 — sin violaciones
    1 — violaciones encontradas
    2 — error de uso (sin argumentos)

Ignorar violaciones: añadir al final de la línea el marcador
``<!-- alantyle-ignore -->`` para suprimir todos los detectores sobre esa
línea, o ``<!-- alantyle-ignore:ALANxxx -->`` para suprimir solo un código.
El propio marcador no se evalúa.

Tests: ``tests/test_check_alantyle.py``. Integración CI:
``.github/workflows/ci.yml::lint.job.steps[alantyle-lint]`` (issues
#559, #571, #572; ADR d-42).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    """Un hallazgo emitido por el detector.

    ``code`` es el código ALANxxx; ``line`` y ``column`` son 1-based.
    ``message`` está redactado en castellano peninsular formal (usted).
    """

    file: Path
    line: int
    column: int
    code: str
    message: str


# Constantes: exit codes, whitelist, umbrales y patrones regex.
EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE_ERROR = 2

# Whitelist de acrónimos técnicos y nombres de dominio.
#
# Justificación por categoría:
#   - SQL/DB: ANSI SQL estándar, extensiones comunes y tipos de PostgreSQL.
#   - HTTP/security: métodos, protocolos y controles de seguridad web.
#   - Cloud/infrastructure: proveedores, redes y servicios de plataforma.
#   - Languages/tools: formatos, runtimes, estándares y herramientas.
#   - Quality/status: arquitectura, CI, roles y estados de revisión.
#   - APAP_WEB domain: gestión de protectoras y nombres heredados de Access.
#   - Repo internal: IDs, prefijos de requisitos, columnas y constantes.
#
# Las palabras genéricas de énfasis (IF, NOT, FROM, TODO, etc.) quedan fuera:
# se redactan en minúsculas o se suprimen por línea con una directiva selectiva.
_SQL_DB_WHITELIST = frozenset(
    {
        "ACCDB", "ACID", "ADD", "ALTER", "ASC", "AUTOINCREMENT", "BD",
        "BEGIN", "BIGSERIAL", "BOOLEAN", "CASCADE", "CHECK", "COLUMN",
        "COMMIT", "CONFLICT", "CONSTRAINT", "COUNT", "CREATE", "CTE",
        "DAO", "DATE", "DATEDIFF", "DB", "DDL", "DEFAULT", "DELETE",
        "DESC", "DISTINCT", "DOMAIN", "DROP", "DSN", "EXISTS",
        "EXTENSION", "FALSE", "FK", "FTS", "GROUP", "HAVING", "ILIKE",
        "INDEX", "INNER", "INSERT", "INT", "INTEGER", "INTERVAL", "INTO",
        "JOIN", "JSONB", "LAST", "LIMIT", "MSACCESS", "MVCC", "NOSQL",
        "NOW", "NULL", "NULLS", "ORDER", "ORM", "PG", "PK", "RDBMS",
        "REFERENCES", "RESTRICT", "RETURNING", "ROLLBACK", "SAVEPOINT",
        "SCHEMA", "SEED", "SELECT", "SERIAL", "SET", "SQL", "SUM",
        "TABLE", "TEXT", "TIMESTAMP", "TIMESTAMPTZ", "TRANSACTION",
        "TRIGGER", "TRUE", "TRUNCATE", "TYPE", "UNION", "UNIQUE",
        "UPDATE", "UUID", "VIEW",
    }
)

_HTTP_SECURITY_WHITELIST = frozenset(
    {
        "API", "CORS", "CRUD", "CSP", "CSRF", "DNI", "GDPR", "GET",
        "HEAD", "HIPAA", "HMAC", "HSTS", "HTTP", "HTTPS", "HTTPX", "JWE",
        "JWS", "JWT", "NIE", "NIF", "NIST", "OPTIONS", "PATCH", "PHI",
        "PII", "PKCE", "POST", "PUT", "RBAC", "REDACTED", "REST", "RFC",
        "RLS", "SECURITY", "SOAP", "SSL", "TLS", "URI", "URL", "URN",
        "USERNAME", "XSS",
    }
)

_CLOUD_INFRASTRUCTURE_WHITELIST = frozenset(
    {
        "AMQP", "AWS", "AZURE", "CDN", "CIDR", "DNS", "FTP", "GCP",
        "GRPC", "IaaS", "IMAP", "INFORGE", "INSFORGE", "IP", "K8S",
        "MQTT", "PaaS", "SAAS", "SMTP", "SMS", "SSH", "TCP", "UDP",
        "VPN", "VPS", "WS", "WSS", "WWW",
    }
)

_LANGUAGE_FORMAT_TOOL_WHITELIST = frozenset(
    {
        "AA", "AGI", "AI", "ASCII", "ASGI", "AST", "BMP", "CAS", "CET",
        "CLI", "CMD", "COM", "CSS", "CSV", "CTA", "DOCX", "DOM", "DRF",
        "EHR", "ELT", "EOL", "ERD", "ETL", "EU", "EXE", "FAQ", "FD",
        "FSO", "GMT", "GNU", "GUID", "HTML", "HTMX", "IA", "ID", "IEEE",
        "INFO", "ISO", "JS", "JSON", "KB", "LF", "LINUX", "LLM", "LOC",
        "LSP", "LTS", "MCP", "MD", "ML", "NASA", "NFKD", "NLP", "OCR",
        "OECD", "OK", "OOM", "OS", "OSS", "PDF", "PEP", "PID", "PNG",
        "POP", "POSIX", "PTY", "PWA", "PYTHONHASHSEED", "PYTHONPATH", "RQ",
        "SDK", "SEO", "SIGINT", "SO", "SPA", "STDERR", "STDIN", "STDOUT",
        "SVG", "TBD", "TLD", "TOML", "TS", "TSV", "TTL", "UA", "UK",
        "UN", "USA", "UTC", "UTF", "VBA", "WCAG", "WHO", "WSL", "XML",
        "YAML", "YYYY",
    }
)

_QUALITY_STATUS_WHITELIST = frozenset(
    {
        "ACQUISITION", "ADDED", "ADDITIONS", "ADMIN", "ADR", "AGENTS",
        "ALLOW", "APM", "APPROVED", "ARCHIVED", "ARG", "BASELINE", "BDD",
        "BFF", "BI", "BLOCKED", "BLOCKER", "CC", "CD", "CHANGELOG", "CHILD",
        "CI", "CLOSED", "CODEBASE", "CODEOWNERS", "CONTRIBUTING", "CRAP",
        "CRITICAL", "DAG", "DDD", "DELETED", "DENY", "DEVELOPER", "DI",
        "DIP", "DISABLED", "DOC", "DOCS", "DONE", "DORMANT", "DRAFT",
        "ENABLED", "FAIL", "FIXED", "GREEN", "GUIDE", "HIGH", "IMPLEMENTED",
        "INCOMPETENT", "ISP", "KILLED", "KPI", "LOW", "MEDIUM", "MERGED",
        "MVC", "MVP", "OPEN", "OPENSPEC", "PASS", "PENDING", "POC", "PR",
        "PROBLEMS", "PROVISIONAL", "QA", "RAG", "RDD", "READER", "README",
        "RED", "REFACTOR", "REJECT", "REQ", "ROI", "ROTA", "SDD", "SHA",
        "SKILL", "SKIPPED", "SLA", "SLI", "SLO", "SOA", "SOC", "SOLID",
        "SOX", "STACK", "SUGGESTION", "SUPERSEDED", "TDD", "TOC", "TOCTOU",
        "TRACKED", "UAT", "UI", "UPDATED", "UX", "WARN", "WARNING", "WIP",
        "XX", "XXX",
    }
)

_APAP_DOMAIN_WHITELIST = frozenset(
    {
        "ACOGIDA", "ADM", "ADOPT", "ADOPTADO", "ADOPTION", "ALBERGUE", "APAP",
        "ARIAC", "AVES", "CANCELADA", "CANINA", "COMPLETADA", "CONTRATO", "CP",
        "DOB", "ENTREGADO", "FALLECIDO", "FELINA", "FICHERO",
        "FIMPLANTACIONCHIP", "FOSTER", "HEALTH", "IDCONTRATOACOGIDA",
        "IDADOPCION", "IDENTRADA", "IDFOSTER", "IDINTAKE", "IDRIAC", "IFC",
        "IFI", "INCOHERENTE", "INTAKE", "LEUC", "LH", "LIFECYCLE", "MANUAL",
        "MATERIAL", "MIGRATION", "NCHIP", "NCONTRATOACOGIDA",
        "NCONTRATOENTRADA", "OPERADOR", "PARIDAD", "PENDIENTE", "PPP", "PTE",
        "READONLY", "REMOVIDO", "REPORT", "REPORTE", "REPORTES", "RESPONSABLE",
        "RIAC", "SALUD", "SEGUIMIENTO", "TERAPIA", "TERAPIAS", "VOL",
        "VOLUNTARIOS",
    }
)

_REPO_INTERNAL_WHITELIST = frozenset(
    {
        "CATALOG", "CRIT", "DD", "DM", "DS", "ENV", "EST", "FE", "FIDELITY",
        "FOUNDATION", "GAP", "GC", "HOME", "MM", "PERMISSIONS", "REG", "ROUTE",
        "SB", "SCOPE", "SECRET", "SERVICE", "TASK", "UP", "WORKER", "YY",
    }
)

ACRONYM_WHITELIST: frozenset[str] = frozenset().union(
    _SQL_DB_WHITELIST,
    _HTTP_SECURITY_WHITELIST,
    _CLOUD_INFRASTRUCTURE_WHITELIST,
    _LANGUAGE_FORMAT_TOOL_WHITELIST,
    _QUALITY_STATUS_WHITELIST,
    _APAP_DOMAIN_WHITELIST,
    _REPO_INTERNAL_WHITELIST,
)

# Palabras permitidas SOLO en contexto de spec (archivos bajo openspec/).
# Los specs usan RFC 2119 (MUST/SHALL/...) y Given/When/Then por diseño
# (per openspec/config.yaml rules.specs); son lenguaje semántico de spec,
# no énfasis editorial. En docs/ estas mismas palabras siguen siendo emph
# y el guardrail test_whitelist_v2_does_not_relax_emph_words las protege:
# este frozenset es independiente de ACRONYM_WHITELIST y solo aplica bajo
# openspec/ (ver _is_spec_context).
_SPEC_CONTEXT_KEYWORDS = frozenset({
    # RFC 2119 (inglés)
    "MUST", "SHALL", "SHOULD", "MAY", "NOT",
    # RFC 2119 (equivalentes en castellano, idioma de los specs del repo)
    "DEBE", "DEBEN", "NO", "PUEDE", "PUEDEN", "TIENE", "TIENEN",
    # BDD / Gherkin
    "GIVEN", "WHEN", "THEN", "AND", "BUT", "SCENARIO", "FEATURE",
    "BACKGROUND", "EXAMPLES", "OUTLINE", "DADO", "CUANDO", "ENTONCES",
    # conectores y cuantificadores comunes en prosa de spec
    "IF", "WHERE", "IS", "IN", "ON", "AS", "BY", "FOR", "TO", "OF",
    "WITH", "WITHOUT", "AFTER", "BEFORE", "ONLY", "NEVER", "ALWAYS",
    "ANY", "ALL", "EACH", "OR", "NEW", "SUCH", "THAT", "THIS", "FROM",
    "DO", "DOES", "NOTHING", "OPTIONAL", "PLUS", "BOTH", "HARD",
    "FACTUAL", "ERROR", "FAILS", "CANNOT", "FIRST", "SECOND", "WEB",
    # vocabulario de escenario en castellano (idioma de los specs del repo):
    # marcadores de resultado y cuantificadores dentro de pasos Given/When/Then
    "YA", "DOS", "OTRA", "OTRAS", "OTRO", "OTROS", "TODAS", "TODOS",
    "SIN", "ANTES", "DESPUES", "EXISTE", "EXISTEN", "PASA", "FALLA",
    "HAY", "TIENE", "TIENEN",
    # prefijos de escenario / work-unit / requisito del flujo OpenSpec
    "QG", "SCN", "MUT", "PROP", "WU", "RISK", "MOD", "MSITES", "XCUT",
    "ADAPT", "COMPLIANT", "MODIFIED", "HOOK", "DRY", "VERIFICATION",
    "CANCELLATION", "NOTE",
})


def _is_spec_context(file: Path) -> bool:
    """True si el archivo vive bajo openspec/ (specs persistentes o changes).

    Los specs usan RFC 2119 y Given/When/Then por diseño; esas palabras son
    lenguaje semántico de spec, no énfasis editorial. Fuera de openspec/ el
    detector aplica la whitelist estricta (ACRONYM_WHITELIST) y sigue
    reportando esas palabras como emph.
    """
    return "openspec" in file.parts

# ALAN002: code-point ranges de emojis decorativos. Cubre BMP (Misc
# Symbols) y supplementary planes (Pictographs, Emoticons, Transport,
# Symbols Extended-A, Regional Indicators para banderas).
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F680-\U0001F6FF"  # Transport and Map
    "\U0001F700-\U0001F77F"  # Alchemical
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\u2600-\u26FF"          # Misc Symbols
    "\U0001F1E6-\U0001F1FF"  # Regional Indicators (banderas)
    "]"
)

# ALAN003: palabras enteramente en mayúsculas (2+ letras ASCII). Las
# secuencias seguidas de dígitos (ALAN001, SHA256, etc.) no se
# contabilizan porque no hay límite de palabra entre la letra final y
# el dígito inicial.
_ALLCAPS_WORD_RE = re.compile(r"\b[A-Z]{2,}\b")

# Inline code (`...`): el contenido dentro de backticks es código, no prosa.
# Los detectores de estilo no deben evaluarlo (queries SQL, identificadores,
# keywords RFC 2119 dentro de ejemplos de código, etc.).
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _mask_inline_code(raw: str) -> str:
    """Reemplaza spans de inline code por espacios de igual longitud.

    Preserva la longitud de la línea para que las columnas reportadas por
    los detectores sigan coincidiendo con la línea cruda. Los detectores de
    prosa evalúan la línea enmascarada, nunca la cruda.
    """
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group()), raw)

# Los marcadores GIVEN/WHEN/THEN (y su equivalente en castellano) son
# estructura de escenarios OpenSpec, no énfasis en prosa. La excepción
# exige el formato exacto de item en negrita y solo cubre el marcador;
# cualquier otra secuencia ALL CAPS de la misma línea sigue evaluándose.
_OPEN_SPEC_SCENARIO_RE = re.compile(
    r"^\s*-\s+(?:\*\*(?P<bold>GIVEN|WHEN|THEN|AND|DADO|CUANDO|ENTONCES)\*\*"
    r"|(?P<plain>GIVEN|WHEN|THEN|AND|DADO|CUANDO|ENTONCES)\b)"
)

# ALAN007 solo evalúa párrafos de prosa. Tablas, listas, citas, HTML y
# bloques indentados son estructuras markdown independientes y no deben
# concatenarse como si fueran un único párrafo.
_MARKDOWN_LIST_ITEM_RE = re.compile(r"^(?:[-+*]|\d+[.)])\s")


# ALAN004: frases ambiguas (substring case-insensitive). El conjunto
# refleja la skill §10 más las formas coloquiales que la skill prohíbe
# explícitamente.
_AMBIGUOUS_PHRASES: tuple[str, ...] = (
    "we recommend",
    "best practice",
    "sería bueno",
    "podría",
    "would be",
    "could potentially",
    "maybe consider",
    "it's a good idea",
)

# ALAN005: palabras y frases de marketing fluff (case-insensitive).
_MARKETING_PHRASES: tuple[str, ...] = (
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
)
_MARKETING_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in _MARKETING_PHRASES) + r")\b",
    re.IGNORECASE,
)

# ALAN006: enlace markdown con destino http(s)://.
_EXTERNAL_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")

# ALAN008: marcadores de TOC auto-generada. La búsqueda se limita a las
# primeras cincuenta líneas (heurística de la skill §10).
_TOC_MARKER_RE = re.compile(r"<!--\s*toc\s*-->|<TOC>", re.IGNORECASE)

# ALAN009: heading de instalación (## Installation o ## Install).
_INSTALL_HEADING_RE = re.compile(r"^##\s+(Installation|Install)\s*$", re.IGNORECASE)

# Umbrales de los detectores que evalúan tamaño agregado.
_PARAGRAPH_MAX_CHARS = 200
_MAX_EXTERNAL_LINKS = 6
_TOC_SCAN_LIMIT = 50
# Mínimo de líneas para que el detector ALAN009 (instalación al final) evalúe
# mitad-de-documento; por debajo de este umbral no hay "final" significativo.
_MIN_LINES_FOR_INSTALL_AT_END = 4

# Campos de frontmatter obligatorios (skill §10).
_REQUIRED_FRONTMATTER_TOP_KEYS: tuple[str, ...] = (
    "name",
    "description",
    "license",
)
_REQUIRED_FRONTMATTER_META_KEYS: tuple[str, ...] = (
    "author",
    "version",
)

# Marcadores de escape por línea. ``_IGNORE_ALL`` suprime cualquier
# detector sobre la línea; ``_IGNORE_CODE`` se construye con el código
# específico (ALANxxx).
_IGNORE_ALL = "<!-- alantyle-ignore -->"


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: la salida no debe depender del locale."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


# Directorios excluidos del gate por convención. ``archive`` cubre
# openspec/changes/archive: cambios ya cerrados, registros históricos
# inmutables que no deben re-editarse para satisfacer el linter (ADR d-42).
_EXCLUDED_DIR_SEGMENTS = frozenset({"archive"})


def _is_excluded_path(path: Path) -> bool:
    """True si el path vive bajo un directorio excluido del gate."""
    return bool(_EXCLUDED_DIR_SEGMENTS.intersection(path.parts))


def _iter_markdown_paths(targets: list[Path]) -> list[Path]:
    """Expande los argumentos a archivos ``.md`` ordenados.

    Acepta archivos sueltos (solo ``.md``; otros sufijos se ignoran) y
    directorios (recorrido recursivo). El resto de sufijos cae en
    silencio para que el operador pueda pasar paths heterogéneos sin
    filtrarlos a mano. Los paths bajo un directorio excluido
    (``_EXCLUDED_DIR_SEGMENTS``, p. ej. openspec/changes/archive) se
    descartan: son registros históricos inmutables fuera del gate.
    """
    out: list[Path] = []
    for target in targets:
        if target.is_file():
            if target.suffix == ".md" and not _is_excluded_path(target):
                out.append(target)
            continue
        if target.is_dir():
            out.extend(
                sorted(
                    p
                    for p in target.rglob("*.md")
                    if not _is_excluded_path(p)
                )
            )
    return out


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_block_lines(lines: list[str]) -> set[int]:
    """Devuelve los índices (0-based) de las líneas dentro de un bloque
    de código delimitado por fences ````.

    Las propias líneas de fence (apertura y cierre) entran en el
    conjunto para que ningún detector evalúe sus marcadores. Los bloques
    indentados (4+ espacios) se ignoran a propósito: la skill apunta
    a markdown estándar y los fences cubren el caso común.
    """
    out: set[int] = set()
    in_block = False
    for idx, raw in enumerate(lines):
        if raw.lstrip().startswith("```"):
            in_block = not in_block
            out.add(idx)
            continue
        if in_block:
            out.add(idx)
    return out


def _line_ignored(raw: str, code: str | None = None) -> bool:
    """True si la línea lleva un marcador ``alantyle-ignore``.

    ``code=None`` evalúa el marcador genérico; un código explícito
    (``ALANxxx``) acepta tanto el genérico como el específico de ese
    código. La comprobación es de substring sobre la línea cruda.
    """
    return _IGNORE_ALL in raw or (
        code is not None and f"<!-- alantyle-ignore:{code} -->" in raw
    )


def _parse_frontmatter(lines: list[str]) -> tuple[list[str], int] | None:
    """Devuelve ``(cuerpo, índice_exclusivo_del_cierre)`` si el archivo
    arranca con un frontmatter YAML entre dos líneas ``---``.

    Retorna ``None`` cuando el archivo no empieza por fence ``---`` o
    cuando no se encuentra el cierre antes del fin de archivo.
    """
    if not lines or lines[0].rstrip() != "---":
        return None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip() == "---":
            return lines[1:idx], idx
    return None


def _parse_frontmatter_keys(body: list[str]) -> tuple[set[str], set[str]]:
    """Devuelve ``(top_keys, metadata_keys)`` observadas en el cuerpo.

    ``top_keys`` contiene las claves al inicio de línea (indentación
    cero) distintas de ``metadata``. ``metadata_keys`` contiene las
    claves que aparecen indentadas bajo un bloque ``metadata:``
    previamente abierto. El estado del bloque se cierra cuando vuelve
    a aparecer una línea sin indentar.
    """
    top: set[str] = set()
    meta: set[str] = set()
    in_metadata = False
    for raw in body:
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(stripped)
        if indent == 0:
            in_metadata = False
            if ":" not in stripped:
                continue
            key = stripped.split(":", 1)[0].strip()
            if key == "metadata":
                in_metadata = True
                continue
            top.add(key)
        elif in_metadata and ":" in stripped:
            meta.add(stripped.split(":", 1)[0].strip())
    return top, meta


def _check_frontmatter(file: Path, lines: list[str]) -> list[Violation]:
    """ALAN001: frontmatter sin los campos obligatorios.

    Solo dispara cuando el archivo arranca con un frontmatter YAML
    entre dos líneas ``---``. Reporta cada campo ausente como una
    violación separada en la línea 1 (apertura del frontmatter).
    """
    front = _parse_frontmatter(lines)
    if front is None:
        return []
    body, _end = front
    top, meta = _parse_frontmatter_keys(body)
    out: list[Violation] = []
    for missing in _REQUIRED_FRONTMATTER_TOP_KEYS:
        if missing in top:
            continue
        out.append(
            Violation(
                file=file,
                line=1,
                column=1,
                code="ALAN001",
                message=(
                    f"frontmatter incompleto: falta el campo obligatorio {missing!r} "
                    "(skill documentation-alan-style §10)"
                ),
            )
        )
    for missing in _REQUIRED_FRONTMATTER_META_KEYS:
        if missing in meta:
            continue
        out.append(
            Violation(
                file=file,
                line=1,
                column=1,
                code="ALAN001",
                message=(
                    f"frontmatter incompleto: falta metadata.{missing} "
                    "(skill documentation-alan-style §10)"
                ),
            )
        )
    return out


def _check_emoji(
    file: Path, lines: list[str], skip: set[int]
) -> list[Violation]:
    """ALAN002: un emoji decorativo aparece en una línea fuera de un
    bloque de código que no esté marcada con ``alantyle-ignore``.
    """
    out: list[Violation] = []
    for idx, raw in enumerate(lines):
        if idx in skip:
            continue
        if _line_ignored(raw, code="ALAN002"):
            continue
        match = _EMOJI_RE.search(raw)
        if match is None:
            continue
        out.append(
            Violation(
                file=file,
                line=idx + 1,
                column=match.start() + 1,
                code="ALAN002",
                message=(
                    f"emoji decorativo en heading o cuerpo {match.group()!r} "
                    "(skill documentation-alan-style §10)"
                ),
            )
        )
    return out


def _check_allcaps(
    file: Path, lines: list[str], skip: set[int]
) -> list[Violation]:
    """ALAN003: palabras de 2+ letras ASCII en mayúsculas que no están
    en la whitelist de acrónimos.
    """
    out: list[Violation] = []
    spec_context = _is_spec_context(file)
    for idx, raw in enumerate(lines):
        if idx in skip:
            continue
        if _line_ignored(raw, code="ALAN003"):
            continue
        scenario = _OPEN_SPEC_SCENARIO_RE.match(raw)
        scenario_span: tuple[int, int] | None = None
        if scenario is not None:
            group = "bold" if scenario.group("bold") is not None else "plain"
            scenario_span = scenario.span(group)
        masked = _mask_inline_code(raw)
        for match in _ALLCAPS_WORD_RE.finditer(masked):
            if scenario_span is not None and match.span() == scenario_span:
                continue
            word = match.group()
            if word in ACRONYM_WHITELIST:
                continue
            if spec_context and word in _SPEC_CONTEXT_KEYWORDS:
                continue
            out.append(
                Violation(
                    file=file,
                    line=idx + 1,
                    column=match.start() + 1,
                    code="ALAN003",
                    message=(
                        f"secuencia en mayúsculas {word!r} fuera de la whitelist "
                        "de acrónimos técnicos y nombres propios (skill "
                        "documentation-alan-style §10)"
                    ),
                )
            )
    return out


def _check_ambiguous(
    file: Path, lines: list[str], skip: set[int]
) -> list[Violation]:
    """ALAN004: frase ambigua en una línea fuera de código.

    Reporta la primera coincidencia por línea para no inundar la salida;
    operadores pueden eliminar las frases y re-correr.
    """
    out: list[Violation] = []
    for idx, raw in enumerate(lines):
        if idx in skip:
            continue
        if _line_ignored(raw, code="ALAN004"):
            continue
        lowered = raw.lower()
        for phrase in _AMBIGUOUS_PHRASES:
            pos = lowered.find(phrase)
            if pos < 0:
                continue
            out.append(
                Violation(
                    file=file,
                    line=idx + 1,
                    column=pos + 1,
                    code="ALAN004",
                    message=(
                        f"lenguaje ambiguo {phrase!r}: use imperativo directo "
                        "(skill documentation-alan-style §10)"
                    ),
                )
            )
            break
    return out


def _check_marketing(
    file: Path, lines: list[str], skip: set[int]
) -> list[Violation]:
    """ALAN005: palabra de marketing fluff en una línea fuera de código."""
    out: list[Violation] = []
    for idx, raw in enumerate(lines):
        if idx in skip:
            continue
        if _line_ignored(raw, code="ALAN005"):
            continue
        match = _MARKETING_RE.search(raw)
        if match is None:
            continue
        out.append(
            Violation(
                file=file,
                line=idx + 1,
                column=match.start() + 1,
                code="ALAN005",
                message=(
                    f"marketing fluff {match.group()!r}: redacte en lenguaje neutro "
                    "(skill documentation-alan-style §10)"
                ),
            )
        )
    return out


def _check_external_links(
    file: Path, lines: list[str], skip: set[int]
) -> list[Violation]:
    """ALAN006: el archivo contiene más de seis enlaces externos.

    Emite una sola violación por archivo (en el primer enlace que
    supera el umbral) para mantener la señal accionable.
    """
    count = 0
    first_excess: tuple[int, int] | None = None
    for idx, raw in enumerate(lines):
        if idx in skip:
            continue
        for match in _EXTERNAL_LINK_RE.finditer(raw):
            count += 1
            if count > _MAX_EXTERNAL_LINKS and first_excess is None:
                first_excess = (idx + 1, match.start() + 1)
    if first_excess is None:
        return []
    line, column = first_excess
    return [
        Violation(
            file=file,
            line=line,
            column=column,
            code="ALAN006",
            message=(
                f"más de {_MAX_EXTERNAL_LINKS} enlaces externos en el archivo "
                f"(contados {count}; skill documentation-alan-style §10)"
            ),
        )
    ]


def _is_non_paragraph_markdown(raw: str) -> bool:
    """Indica si una línea pertenece a una estructura que no es prosa."""
    stripped = raw.strip()
    if raw.startswith(("    ", "\t")):
        return True
    if stripped.startswith(("|", ">", "<!--", "<", "---")):
        return True
    return _MARKDOWN_LIST_ITEM_RE.match(stripped) is not None


def _check_paragraphs(
    file: Path, lines: list[str], skip: set[int]
) -> list[Violation]:
    """ALAN007: párrafo de más de doscientos caracteres sin punto.

    Un párrafo se define como la secuencia de líneas no vacías, no
    indentadas como heading y fuera de bloques de código. La violación
    se emite sobre la primera línea del párrafo y se suprime cuando
    esa línea lleva ``alantyle-ignore``.
    """
    out: list[Violation] = []
    para_lines: list[tuple[int, str]] = []

    def flush() -> None:
        if not para_lines:
            return
        joined = " ".join(line.strip() for _, line in para_lines)
        if len(joined) > _PARAGRAPH_MAX_CHARS and "." not in joined:
            first_idx, first_raw = para_lines[0]
            if not _line_ignored(first_raw, code="ALAN007"):
                out.append(
                    Violation(
                        file=file,
                        line=first_idx + 1,
                        column=1,
                        code="ALAN007",
                        message=(
                            f"párrafo de {len(joined)} caracteres sin punto y aparte "
                            f"(límite {_PARAGRAPH_MAX_CHARS}; skill documentation-alan-style §10)"
                        ),
                    )
                )
        para_lines.clear()

    for idx, raw in enumerate(lines):
        if idx in skip:
            flush()
            continue
        stripped = raw.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            continue
        if _is_non_paragraph_markdown(raw):
            flush()
            continue
        para_lines.append((idx, raw))
    flush()
    return out


def _check_toc(file: Path, lines: list[str]) -> list[Violation]:
    """ALAN008: marcador de TOC auto-generada dentro de las primeras
    cincuenta líneas del documento.
    """
    limit = min(_TOC_SCAN_LIMIT, len(lines))
    for idx in range(limit):
        if _TOC_MARKER_RE.search(lines[idx]):
            return [
                Violation(
                    file=file,
                    line=idx + 1,
                    column=1,
                    code="ALAN008",
                    message=(
                        "marcador de tabla de contenidos auto-generada cerca del top; "
                        "use un índice explícito (skill documentation-alan-style §10)"
                    ),
                )
            ]
    return []


def _check_install_at_end(file: Path, lines: list[str]) -> list[Violation]:
    """ALAN009: heading ``## Installation`` o ``## Install`` aparece
    después de la mitad del documento.
    """
    total = len(lines)
    if total < _MIN_LINES_FOR_INSTALL_AT_END:
        return []
    midpoint = total // 2
    for idx in range(midpoint, total):
        if _INSTALL_HEADING_RE.match(lines[idx]):
            return [
                Violation(
                    file=file,
                    line=idx + 1,
                    column=1,
                    code="ALAN009",
                    message=(
                        "sección de instalación al final del documento; "
                        "muévala al inicio (skill documentation-alan-style §10)"
                    ),
                )
            ]
    return []


def scan_markdown_content(file: Path, content: str) -> list[Violation]:
    """Aplica los nueve detectores al contenido markdown dado.

    Punto de entrada para tests; los argumentos CLI llaman a
    :func:`find_violations` que itera sobre archivos y delega aquí.
    """
    lines = content.splitlines()
    skip = _code_block_lines(lines)
    out: list[Violation] = []
    out.extend(_check_frontmatter(file, lines))
    out.extend(_check_emoji(file, lines, skip))
    out.extend(_check_allcaps(file, lines, skip))
    out.extend(_check_ambiguous(file, lines, skip))
    out.extend(_check_marketing(file, lines, skip))
    out.extend(_check_external_links(file, lines, skip))
    out.extend(_check_paragraphs(file, lines, skip))
    out.extend(_check_toc(file, lines))
    out.extend(_check_install_at_end(file, lines))
    return out


def find_violations(paths: list[Path]) -> list[Violation]:
    """Escanea los paths dados y devuelve todas las violaciones."""
    out: list[Violation] = []
    for path in _iter_markdown_paths(paths):
        try:
            content = _read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        out.extend(scan_markdown_content(path, content))
    return out


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI. Véase docstring del módulo."""
    _pin_output_encoding()
    if argv is None:
        argv = sys.argv[1:]
    args = argv
    if not args:
        print(
            "uso: check_alantyle.py <ruta> [<ruta>...] "
            "(archivo .md o directorio recursivo)",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR
    paths = [Path(a) for a in args]
    files = _iter_markdown_paths(paths)
    violations = find_violations(paths)
    cwd = Path.cwd()
    for v in violations:
        try:
            rel = v.file.relative_to(cwd)
        except ValueError:
            rel = v.file
        print(
            f"{rel}:{v.line}:{v.column}: {v.code} {v.message}",
            file=sys.stderr,
        )
    if violations:
        print(
            f"check_alantyle: FAIL ({len(violations)} violaciones en {len(files)} archivos)",
            file=sys.stderr,
        )
        return EXIT_VIOLATIONS
    print(
        f"check_alantyle: OK ({len(files)} archivos)",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
