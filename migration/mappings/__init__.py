"""YAML mappings para migración web ↔ legacy (LIFECYCLE-03 / migration-01).

Cada archivo ``*.yaml`` en este paquete describe cómo mapear una tabla
web a su tabla legacy correspondiente. El loader ``load_mapping()`` lo
parsea y lo valida con el modelo pydantic ``TableMapping``, de modo que
un YAML malformado se rechaza ANTES de tocar datos (regla del design:
abortar con código 4 al cargar el mapeo).

**Estructura de un YAML** (ver Anexo A del design):

```yaml
version: "1.0"
web_table: animales
legacy_table: TbFichaAnimal
key_field: NCHIP
legacy_key: NCHIP
date_fields: [FIMPLANTACIONCHIP, FDefuncion]
columns:
  - { web_column: NCHIP, legacy_column: NCHIP, transform: identity, nullable: false }
  - { web_column: id, transform: default_uuid, nullable: false }
fk_lookups:
  - name: animal
    web_column: animal_id
    legacy_column: NChip
    lookup_table: animales
    lookup_legacy_key: NCHIP
```

**Reglas operativas que este módulo encarna**:

- **#13454 v2** (schema web libre, no CamelCase legacy forzado): las
  columnas web pueden tener nombres distintos a las legacy; el rename
  se hace explícito columna por columna en el YAML.
- **#13474 v2** (función de migración con mapeo configurable): los
  YAMLs son el contrato. Cambiar el rename legacy↔web no requiere
  tocar código Python; solo editar el YAML.
- **#13487** (TDD estricto): los YAMLs están cubiertos por
  ``tests/test_migration.py::TestMappings``. Si cambia un nombre de
  columna, el test correspondiente se rompe.

**Strict ``web_only_strategy`` validator (PR 3 of web-only-feature-preservation)**:

A ``ColumnMapping`` with ``legacy_column=null`` MUST declare a
``web_only_strategy`` (``preserve`` / ``fixed`` / ``derived``) UNLESS
its transform is in the exempt list:

  - ``default_uuid`` (column ``id`` PK): el web genera un UUID v4
    mecánico, sin valor de negocio a preservar.
  - ``default_now`` (columns ``fecha_alta`` / ``updated_at``): el web
    estampa ``utcnow()``, sin dato legacy del que derivar.
  - ``fk_lookup`` (cross-table FKs): el valor se resuelve vía
    ``sync_state.json`` (legacy_id ↔ web_uuid), no vía shadow-state.
    Declarar ``web_only_strategy`` aquí sería un mecanismo duplicado.

Cualquier columna con ``legacy_column=null`` y ``transform`` en
``{identity, currency_to_numeric, double_to_numeric, default_true}``
que omita ``web_only_strategy`` falla con ``ValidationError`` al cargar
el YAML — el caller mapea esa excepción a ``EXIT_CODE_YAML_VALIDATION_ERROR``
(4) ANTES de cualquier I/O (regla del design §1.5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from migration import MappingNotFoundError

# Directorio donde viven los YAMLs. Se resuelve a partir de __file__ para
# que funcione tanto en editable install (``pip install -e .``) como en
# wheel instalado en producción.
MAPPINGS_DIR = Path(__file__).parent

#: Transforms whose ``legacy_column=null`` columns are EXEMPT from the
#: strict ``web_only_strategy`` requirement. See module docstring for
#: the rationale per transform.
#:
#: - ``default_uuid``: PK generada por la web (UUID v4) — sin valor legacy.
#: - ``default_now``: timestamp web (``fecha_alta``/``updated_at``).
#: - ``fk_lookup``: cross-table FK resuelto vía ``sync_state.json``.
#:
#: Adding a new transform here means "this column never carries a
#: business value that needs preservation". Do NOT add ``default_true``
#: (the ``activo`` soft-delete flag IS a business decision — the web
#: owns it, so the shadow-state repository needs ``fixed``).
_STRATEGY_EXEMPT_TRANSFORMS: frozenset[str] = frozenset(
    {"default_uuid", "default_now", "fk_lookup"}
)

#: Exit code convention for YAML / config validation errors.
#:
#: The CLI / applier maps a ``ValidationError`` raised from
#: :func:`load_mapping` to this exit code BEFORE any I/O (design §1.5
#: table of error handling: "YAML/config error → código 4").
#:
#: Exposed as a module constant so callers do not redeclare the magic
#: number. The ``apap-migrate reconcile`` subcommand and the applier
#: both import this constant; PR 5 wires ``run_reconcile`` to use it
#: when a YAML fails to load.
EXIT_CODE_YAML_VALIDATION_ERROR: int = 4

# --- Modelos pydantic ----------------------------------------------------


class ColumnMapping(BaseModel):
    """Una columna en el mapeo.

    ``web_column`` es el nombre de la columna en la tabla web; puede ser
    snake_case (``fecha_alta``) o CamelCase (``NCHIP``) si el nombre
    legacy ya es la mejor opción.

    ``legacy_column`` es el nombre en la tabla legacy del Access. Es
    ``None`` cuando la columna es **web-only / greenfield** (ej: el
    ``id`` UUID generado por la web, o los timestamps ``fecha_alta`` /
    ``updated_at``). El applier detecta ``legacy_column is None`` y
    deja la columna fuera de la query INSERT/UPDATE al legacy (regla
    #13454 v2: schema web libre, no se fuerza CamelCase legacy).

    ``transform`` es la operación que el applier aplica al valor antes
    de escribirlo. Los transforms disponibles son los siete
    documentados en el design §1.5 (tabla de error handling) + Anexo A:

    - ``identity``: copia 1:1 (default).
    - ``currency_to_numeric``: Access Currency → float Python (ej:
      ``DonativoAdopcion`` que en Access es Currency con formato €.
    - ``double_to_numeric``: Access Double → float Python (similar al
      anterior pero para campos numéricos puros como
      ``DonativoPreadopcion``).
    - ``fk_lookup``: el valor legacy es un identificador free-text o
      INTEGER que referencia a otra tabla; se resuelve via
      ``fk_lookups[name=...]`` al UUID web correspondiente (estrategia
      de 4 niveles: sync_state → snapshot → fuzzy → None/raise).
    - ``default_now``: la web pone su ``datetime.utcnow()`` actual
      (campos ``fecha_alta`` / ``updated_at``).
    - ``default_uuid``: la web genera un UUID v4 (columna ``id`` PK).
    - ``default_true``: la web pone ``True`` (columna ``activo``).
    """

    web_column: str
    legacy_column: str | None = None
    transform: Literal[
        "identity",
        "currency_to_numeric",
        "double_to_numeric",
        "fk_lookup",
        "default_now",
        "default_uuid",
        "default_true",
        "nullify_empty_string",
        "normalize_sexo",
        "normalize_especie",
        "normalize_si_no",
    ] = "identity"
    nullable: bool = True
    lookup: str | None = None  # nombre del fk_lookup (transform=fk_lookup)
    # Web-only / greenfield columns (legacy_column is None) declare a
    # ``web_only_strategy`` so the applier and shadow-state repository
    # know how to round-trip the value across the legacy↔web sync.
    # PR 1 of web-only-feature-preservation adds the field; PR 3 will
    # activate the strict ``legacy_column=null → strategy required``
    # validator once the 5 existing YAMLs are updated to declare
    # strategies on every web-only column (see design.md §9 and
    # tasks.md 3.2).
    web_only_strategy: Literal["preserve", "fixed", "derived"] | None = None

    @model_validator(mode="after")
    def _reject_invalid_strategy(self) -> ColumnMapping:
        """Reject ``web_only_strategy`` values outside the documented enum.

        Catches typos (``"preserved"``, ``"auto"``, ``"magic"``) at
        YAML-load time so the operator never reaches the applier with a
        strategy the derivation engine cannot interpret. The ``None``
        value passes this check unconditionally; the strict
        ``legacy_column=null → strategy required`` rule lives in
        :meth:`_require_strategy_for_web_only` (declared right after
        this method so both ``mode="after"`` validators run in order).
        """
        valid = {"preserve", "fixed", "derived"}
        if self.web_only_strategy is not None and self.web_only_strategy not in valid:
            raise ValueError(
                f"{self.web_column}: web_only_strategy={self.web_only_strategy!r} "
                f"is not one of {sorted(valid)}"
            )
        return self

    @model_validator(mode="after")
    def _require_strategy_for_web_only(self) -> ColumnMapping:
        """Strict validator activated in PR 3: a web-only column
        (``legacy_column is None``) MUST declare a
        ``web_only_strategy`` UNLESS its transform is in the exempt
        list ``_STRATEGY_EXEMPT_TRANSFORMS``.

        Exempt transforms (rationale per transform in the module
        docstring + the constant definition):

          - ``default_uuid``: UUID mecánico de la PK ``id``.
          - ``default_now``: timestamps web (``fecha_alta``/``updated_at``).
          - ``fk_lookup``: FKs cross-table resueltos vía ``sync_state.json``.

        Non-exempt transforms (``identity``, ``currency_to_numeric``,
        ``double_to_numeric``, ``default_true``) carry business value
        and MUST declare a strategy so the shadow-state repository and
        the derivation engine know how to round-trip them. ``activo``
        (``default_true``) is the canonical example: the web owns the
        soft-delete decision, so the repository needs
        ``web_only_strategy="fixed"`` to know it must NOT try to
        reconcile the value with legacy.

        Failure mode: the validator raises ``ValueError``, which
        pydantic wraps in ``ValidationError``. :func:`load_mapping`
        propagates it; the CLI / applier maps it to exit code
        ``EXIT_CODE_YAML_VALIDATION_ERROR`` (4) BEFORE any I/O.

        See tasks.md 3.2, spec.md "Columna sin web_only_strategy con
        legacy_column=null aborta" and design.md §9.
        """
        if self.legacy_column is not None:
            # Column has a legacy source — web-only preservation does
            # not apply, so the strategy is irrelevant (and ``None``).
            return self
        if self.transform in _STRATEGY_EXEMPT_TRANSFORMS:
            # Exempt: auto-generated web value or cross-table FK.
            return self
        if self.web_only_strategy is None:
            raise ValueError(
                f"{self.web_column}: web_only_strategy is required when "
                f"legacy_column=null (transform={self.transform!r}). "
                f"Declare one of preserve, fixed, derived. "
                f"See design.md §9 (YAML: web_only_strategy)."
            )
        return self


class FkLookup(BaseModel):
    """Especificación de un FK lookup (legacy → UUID web).

    Cuando una columna web tiene FK a otra tabla web (ej:
    ``entradas.animal_id`` → ``animales.id``) y la fila legacy tiene un
    valor free-text (``NCHIP``) o INTEGER (``IDEntrada``) que apunta a
    otra fila legacy, el applier usa esta spec para resolver el FK en 4
    niveles (design §4):

      1. ``sync_state.json`` (mapeo persistente legacy_id ↔ UUID).
      2. snapshot en memoria de filas migradas en este run.
      3. fuzzy match con ``thefuzz`` (si ``fuzzy_match=True``) con el
         ``fuzzy_threshold`` (default 85%).
      4. ``None`` si ``optional=True``; ``FkLookupError`` si NOT NULL.

    ``lookup_table`` es la tabla web de destino (``animales``,
    ``voluntarios``, ``entradas``). ``lookup_legacy_key`` es la columna
    legacy que el applier usa para matchear contra el valor heredado
    (ej: ``NCHIP`` en ``animales``).
    """

    name: str  # identificador único dentro del mapping (referenciado por ColumnMapping.lookup)
    web_column: str
    legacy_column: str
    lookup_table: str
    lookup_legacy_key: str
    fuzzy_match: bool = False
    fuzzy_threshold: int = Field(default=85, ge=0, le=100)
    optional: bool = False


class TableMapping(BaseModel):
    """Mapeo completo de una tabla.

    ``key_field`` es la columna web usada como clave lógica para
    matchear filas (puede ser el natural key legacy como ``NCHIP`` o el
    UUID ``id`` web). ``legacy_key`` es la columna legacy equivalente.

    ``date_fields`` lista las columnas legacy que el diff engine mira
    para detectar conflictos ``modified_both_sides`` (regla #13475 v2:
    active-passive estricto). Si una fila tiene varias fechas candidatas
    (``FIMPLANTACIONCHIP``, ``FDefuncion``, etc.), se incluye cada una.

    ``columns`` y ``fk_lookups`` son las listas que el applier itera
    para construir las queries INSERT/UPDATE/DELETE.
    """

    version: str = "1.0"
    web_table: str
    legacy_table: str
    key_field: str
    legacy_key: str
    date_fields: list[str] = []
    columns: list[ColumnMapping]
    fk_lookups: list[FkLookup] = []


# --- API pública ---------------------------------------------------------


def load_mapping(table: str) -> TableMapping:
    """Carga el YAML de mapeo para ``table`` y lo valida con pydantic.

    Args:
        table: nombre del archivo sin extensión (ej: ``"animal"``,
            ``"voluntario"``, ``"entrada"``, ``"acogida"``,
            ``"adopcion"``).

    Returns:
        ``TableMapping`` validado, listo para que el applier lo itere.

    Raises:
        MappingNotFoundError: si no existe el YAML para esa tabla. La
            excepción incluye la lista de tablas disponibles en el
            mensaje para que el operador sepa qué typo cometió.
        ValidationError: si el YAML existe pero su estructura no
            satisface ``TableMapping`` (falta ``web_table``, columna
            requerida, transform inválido, etc.).
    """
    yaml_path = MAPPINGS_DIR / f"{table}.yaml"
    if not yaml_path.exists():
        available = sorted(p.stem for p in MAPPINGS_DIR.glob("*.yaml"))
        raise MappingNotFoundError(f"No mapping for table '{table}'. Available: {available}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return TableMapping.model_validate(raw)


def list_available_tables() -> list[str]:
    """Lista los nombres de tablas disponibles (sin extensión, ordenados).

    Usado por el CLI para validar el flag ``--tables`` y por el diff
    engine para iterar todas las tablas en el orden topológico
    resuelto.
    """
    return sorted(p.stem for p in MAPPINGS_DIR.glob("*.yaml"))


__all__ = [
    "ColumnMapping",
    "EXIT_CODE_YAML_VALIDATION_ERROR",
    "FkLookup",
    "MAPPINGS_DIR",
    "TableMapping",
    "list_available_tables",
    "load_mapping",
]
