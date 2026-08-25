"""SQL for the animals slice (AGENTS.md §22: SQL in exactly one place).

Selects the complete hexagonal :class:`Animal` read shape.
``FNacimiento`` comes back as an ISO 8601 string from InsForge's
PostgREST adapter. ``updated_at`` remains transport-internal.
"""
from __future__ import annotations

from app.modules.animals.domain.animal import DB_LABEL_TO_ESTADO

_ANIMAL_COLUMNS_SQL = (
    'id, "NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento", activo, '
    'fecha_alta, "TraeNChip", "FIMPLANTACIONCHIP", "Raza", "Color", "Pelo", '
    '"Tamano", "Caracter", "FDefuncion", "Terapia", "Observaciones", '
    '"NombreFoto", "Cartilla", "Eutanasia", "RazaPPP", "Mestizo", '
    '"EutanasiaOtrasCausas", "EutanasiaEnfermedad", '
    '"UltimoEstadoAntesDeFallecido", "ComunicacionARIAC"'
)

_ANIMAL_SEARCH_COLUMNS_SQL = (
    'a.id, a."NCHIP", a."NombreAnimal", a."Especie", a."Sexo", '
    'a."FNacimiento", a.activo, a.fecha_alta, a."TraeNChip", '
    'a."FIMPLANTACIONCHIP", a."Raza", a."Color", a."Pelo", a."Tamano", '
    'a."Caracter", a."FDefuncion", a."Terapia", a."Observaciones", '
    'a."NombreFoto", a."Cartilla", a."Eutanasia", a."RazaPPP", a."Mestizo", '
    'a."EutanasiaOtrasCausas", a."EutanasiaEnfermedad", '
    'a."UltimoEstadoAntesDeFallecido", a."ComunicacionARIAC", acs.current_state'
)

GET_ANIMAL_BY_ID_SQL: str = (
    f"SELECT {_ANIMAL_COLUMNS_SQL} FROM animales WHERE id = $1 LIMIT 1"  # noqa: S608 — projection is a module constant; values remain bind parameters
)

GET_ANIMAL_BY_NCHIP_SQL: str = (
    f"SELECT {_ANIMAL_COLUMNS_SQL} "  # noqa: S608 — projection is a module constant; values remain bind parameters
    "FROM animales "
    'WHERE "NCHIP" = $1 AND activo = TRUE '
    "LIMIT 1"
)


def get_animal_by_nchip_sql(nchip: str) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the NCHIP lookup.

    Public entry point so the application layer can assert on the
    SQL shape without spinning up the transport (rule §22). The
    adapter delegates here so the SQL is defined once.
    """
    return GET_ANIMAL_BY_NCHIP_SQL, [nchip]


SEARCH_ANIMALS_SQL: str = (
    f"SELECT {_ANIMAL_SEARCH_COLUMNS_SQL} "  # noqa: S608 — projection and query fragments are module-owned constants; filter values remain binds
    "FROM animales a "
    "{join_clause}"
    "WHERE {where_clause} "
    'ORDER BY a."NCHIP" ASC '
    "LIMIT ${limit_position} OFFSET ${offset_position}"
)

COUNT_ANIMALS_SQL: str = (
    "SELECT COUNT(*) AS total FROM animales a "
    "{join_clause}"
    "WHERE {where_clause}"
)

_ESTADO_TO_DB_LABEL: dict[str, str] = {
    api_estado: db_label for db_label, api_estado in DB_LABEL_TO_ESTADO.items()
}


def _animal_search_where(
    *,
    q: str | None,
    chip: str | None,
    especie: str | None,
    sexo: str | None,
    estado: str | None,
    fecha_alta_since: str | None,
    fecha_alta_until: str | None,
) -> tuple[str, str, list[object]]:
    """Build the shared search/count JOIN, WHERE clause, and bind values."""
    conditions = ["a.activo = TRUE"]
    params: list[object] = []

    def add(condition: str, value: object) -> None:
        params.append(value)
        conditions.append(f"{condition} ${len(params)}")

    if chip:
        add('a."NCHIP" =', chip)
    elif q:
        add('a."NombreAnimal" ILIKE', f"%{q}%")
    if especie:
        add('a."Especie" =', especie)
    if sexo:
        add('a."Sexo" =', sexo)

    db_estado = _ESTADO_TO_DB_LABEL.get(estado) if estado else None
    join_clause = "LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
    if db_estado is not None:
        add("acs.current_state =", db_estado)

    if fecha_alta_since:
        add("a.fecha_alta >=", fecha_alta_since)
    if fecha_alta_until:
        add("a.fecha_alta <=", fecha_alta_until)

    return join_clause, " AND ".join(conditions), params


def search_animals_sql(
    *,
    q: str | None,
    chip: str | None,
    especie: str | None,
    sexo: str | None,
    estado: str | None,
    fecha_alta_since: str | None,
    fecha_alta_until: str | None,
    limit: int,
    offset: int,
) -> tuple[str, list[object]]:
    """Return SQL and binds for one filtered page ordered by NCHIP."""
    join_clause, where_clause, params = _animal_search_where(
        q=q,
        chip=chip,
        especie=especie,
        sexo=sexo,
        estado=estado,
        fecha_alta_since=fecha_alta_since,
        fecha_alta_until=fecha_alta_until,
    )
    limit_position = len(params) + 1
    sql = SEARCH_ANIMALS_SQL.format(
        join_clause=join_clause,
        where_clause=where_clause,
        limit_position=limit_position,
        offset_position=limit_position + 1,
    )
    return sql, [*params, limit, offset]


def count_animals_sql(
    *,
    q: str | None,
    chip: str | None,
    especie: str | None,
    sexo: str | None,
    estado: str | None,
    fecha_alta_since: str | None,
    fecha_alta_until: str | None,
) -> tuple[str, list[object]]:
    """Return an unpaginated count over the search WHERE clause."""
    join_clause, where_clause, params = _animal_search_where(
        q=q,
        chip=chip,
        especie=especie,
        sexo=sexo,
        estado=estado,
        fecha_alta_since=fecha_alta_since,
        fecha_alta_until=fecha_alta_until,
    )
    return COUNT_ANIMALS_SQL.format(
        join_clause=join_clause,
        where_clause=where_clause,
    ), params


# ``list_animals`` — paginated read, newest-first by fecha_alta with
# NCHIP as the deterministic tiebreaker. ``activo = TRUE`` matches the default filter
# in the application-layer wrapper; the adapter accepts an explicit
# override so the historical-record path can opt out.
LIST_ANIMALS_SQL: str = (
    f"SELECT {_ANIMAL_COLUMNS_SQL} "  # noqa: S608 — projection is a module constant; values remain bind parameters
    "FROM animales "
    "{where_clause}"
    'ORDER BY fecha_alta DESC, "NCHIP" ASC '
    "LIMIT $1 OFFSET $2"
)


def list_animals_sql(
    *,
    limit: int,
    offset: int,
    activo_only: bool,
) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the paginated list.

    Public entry point so the application layer can assert on the
    SQL shape without spinning up the transport (rule §22). The
    adapter delegates here so the SQL is defined once.

    Parameters are passed through verbatim — the application layer
    is responsible for clamping ``limit`` and ``offset`` to safe
    ranges; this helper does no defensive bounds-checking because
    it is the only caller that should be exercised in tests, and
    we want the surface to fail loudly on bad inputs.

    ``limit`` and ``offset`` are coerced to ``str`` because the
    InsForge client serialises bind parameters as strings on the
    wire; the integer values land in postgres via the same implicit
    text→int8 cast the legacy ``service.py`` already relies on.
    """
    where_clause = "WHERE activo = TRUE " if activo_only else ""
    return (
        LIST_ANIMALS_SQL.format(where_clause=where_clause),
        [str(limit), str(offset)],
    )


# ``create_animal`` — INSERT ... RETURNING so the adapter gets the
# generated ``id`` in one round-trip. The column list is the
# hexagonal minimum (5 fields the ``Animal`` dataclass round-trips);
# legacy ``TbFichaAnimal`` columns (Raza, Color, Pelo, Tamano,
# Caracter) land in a follow-up slice once the dataclass widens or a
# parallel ``AnimalCreateRequest`` lands. ``activo`` defaults to TRUE at the
# column level (NOT NULL DEFAULT TRUE) so the INSERT omits it; the
# ``RETURNING`` clause projects it back so the returned ``Animal``
# carries the effective value.
INSERT_ANIMAL_SQL: str = (
    "INSERT INTO animales "
    '("NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento") '
    "VALUES ($1, $2, $3, $4, $5) "
    "RETURNING id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
    "\"FNacimiento\", activo"
)


def create_animal_sql(
    *,
    nchip: str,
    nombre: str,
    especie: str,
    sexo: str,
    fnacimiento: str,
) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the INSERT.

    ``especie`` and ``sexo`` are accepted as ``str`` because the
    hexagonal :class:`Especie` / :class:`Sexo` enums are ``StrEnum``,
    so the value IS the string the SQL wants — no extra coercion.
    """
    return (
        INSERT_ANIMAL_SQL,
        [nchip, nombre, especie, sexo, fnacimiento],
    )


# ``update_animal`` — partial UPDATE ... RETURNING. The ``SET`` clause
# is built dynamically from whichever kwargs the caller passed: any
# ``None`` field is skipped. The legacy ``service.update_animal``
# requires every field (validation rejects a partial dict); the
# hexagonal path is partial-update-friendly because the legacy
# route handler does its own field whitelist before delegating.
# ``id`` is the primary key so it cannot be changed and goes in
# the WHERE clause as ``$1``; subsequent fields are ``$2``..``$5``.
# Postgres binding is positional.
UPDATE_ANIMAL_COLUMN_ORDER: tuple[str, ...] = (
    "NombreAnimal",
    "Especie",
    "Sexo",
    "FNacimiento",
)


def update_animal_sql(
    *,
    animal_id: str,
    nombre: str | None,
    especie: str | None,
    sexo: str | None,
    fnacimiento: str | None,
) -> tuple[str, list[str]] | None:
    """Return the ``(sql, params)`` tuple for the partial UPDATE.

    Returns ``None`` when every field is ``None`` — the use case
    treats that as a no-op and short-circuits before reaching the
    adapter, but the helper returns ``None`` defensively in case a
    future caller passes through. The caller checks the return and
    bails on ``None``.
    """
    pairs: list[tuple[str, str]] = []
    if nombre is not None:
        pairs.append(("NombreAnimal", nombre))
    if especie is not None:
        pairs.append(("Especie", especie))
    if sexo is not None:
        pairs.append(("Sexo", sexo))
    if fnacimiento is not None:
        pairs.append(("FNacimiento", fnacimiento))
    if not pairs:
        return None

    set_clause = ", ".join(f"{col} = ${i + 2}" for i, (col, _) in enumerate(pairs))
    sql = (
        "UPDATE animales "  # noqa: S608 — column names from UPDATE_ANIMAL_COLUMN_ORDER constant; values are $N binds
        f"SET {set_clause} "
        "WHERE id = $1 "
        "RETURNING id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
        "\"FNacimiento\", activo"
    )
    params: list[str] = [animal_id] + [value for _, value in pairs]
    return sql, params


# ``delete_animal`` — soft-delete via UPDATE ... RETURNING. Mirrors
# the legacy ``service._DELETE_ANIMAL_SQL`` shape (sets
# ``activo = FALSE`` rather than removing the row, so the audit
# trail stays intact per issue #431 Finding 3). Returns the full
# row so the route handler can confirm the post-deactivation
# state — the legacy SQL only RETURNs ``id, activo`` and the legacy
# service returns ``bool``; the hexagonal path returns the full
# ``Animal`` so callers don't have to re-query.
DELETE_ANIMAL_SQL: str = (
    "UPDATE animales "
    "SET activo = FALSE "
    "WHERE id = $1 "
    "RETURNING id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
    "\"FNacimiento\", activo"
)


def delete_animal_sql(animal_id: str) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the soft-delete."""
    return DELETE_ANIMAL_SQL, [animal_id]


# ``record_lifecycle_event`` — INSERT ... ON CONFLICT DO NOTHING ...
# RETURNING. Idempotent via the natural-key UNIQUE constraint on
# ``(animal_id, event_type, event_timestamp)`` (declared in
# ``ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL``); the application
# keeps the unique constraint aligned with the 14 pinned
# ``LifecycleEventType`` members (see ``core_event_types_set_matches_strenum_members``
# test). When the row already exists the ``ON CONFLICT`` clause
# collapses to a no-op and the existing row comes back via
# RETURNING — the caller sees the same shape either way.
#
# ``metadata`` is JSON-typed on the wire; the InsForge client
# serialises dicts as JSONB. ``legacy_source_id`` is integer (the
# legacy Access table's auto-increment column) and the other
# lineage fields are nullable text.
RECORD_LIFECYCLE_EVENT_COLUMNS: tuple[str, ...] = (
    "id",
    "animal_id",
    "event_type",
    "event_timestamp",
    "created_by",
    "caused_by_event_id",
    "source_entity_type",
    "source_entity_id",
    "legacy_source_table",
    "legacy_source_id",
    "metadata",
)


def record_lifecycle_event_sql(
    *,
    animal_id: str,
    event_type: str,
    event_timestamp: str,
    created_by: str,
    caused_by_event_id: str | None,
    source_entity_type: str | None,
    source_entity_id: str | None,
    legacy_source_table: str | None,
    legacy_source_id: int | None,
    metadata: dict | None,
) -> tuple[str, list[object]]:
    """Return the ``(sql, params)`` tuple for the lifecycle INSERT.

    The bind list is positional; ``None`` lineage values land as
    NULL so the partial-update contract works the same way it does
    on the legacy ``record_event``. ``metadata`` lands as a JSONB
    parameter (``$10``); ``legacy_source_id`` as integer ($9). The
    return type is ``list[object]`` because postgres binds a mix
    of text, int and jsonb values — narrowing each entry to a
    homogeneous type would require ``Union[...]`` and add noise.
    """
    sql = (
        "INSERT INTO animal_lifecycle_events ("
        "animal_id, event_type, event_timestamp, created_by, "
        "caused_by_event_id, source_entity_type, source_entity_id, "
        "legacy_source_table, legacy_source_id, metadata"
        ") VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
        "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING "
        "RETURNING "
        "id, animal_id, event_type, event_timestamp, created_by, "
        "caused_by_event_id, source_entity_type, source_entity_id, "
        "legacy_source_table, legacy_source_id, metadata"
    )
    params: list[object] = [
        animal_id,
        event_type,
        event_timestamp,
        created_by,
        caused_by_event_id,
        source_entity_type,
        source_entity_id,
        legacy_source_table,
        legacy_source_id,
        metadata,
    ]
    return sql, params


# ``list_lifecycle_events`` — chronological timeline read.
# ``ORDER BY event_timestamp ASC, id ASC`` keeps the timeline stable
# when two events share a timestamp (the id is the secondary key).
# ``event_type = ANY($2)`` filters the timeline when the caller
# passes a non-empty ``event_types`` list; ``TRUE`` is the no-op
# placeholder when ``event_types`` is ``None`` or empty so the
# adapter does not have to branch on the filter shape.
LIST_LIFECYCLE_EVENTS_COLUMNS: tuple[str, ...] = (
    "id",
    "animal_id",
    "event_type",
    "event_timestamp",
    "created_by",
    "caused_by_event_id",
    "source_entity_type",
    "source_entity_id",
    "legacy_source_table",
    "legacy_source_id",
    "metadata",
)


def list_lifecycle_events_sql(
    *,
    animal_id: str,
    limit: int,
    offset: int,
    event_types: list[str] | None,
) -> tuple[str, list[object]]:
    """Return the ``(sql, params)`` tuple for the timeline read.

    Params are positional: ``$1`` animal_id, ``$2`` event_type
    filter (array when a filter is requested, single column for the
    no-filter case via a wrapping subquery — postgres folds the
    ``=ANY`` comparison to TRUE when the array is empty). Limit and
    offset follow. The return type is ``list[object]`` because
    postgres binds a mix of text and text[] values — narrowing
    would require ``Union[...]`` and add noise.
    """
    where_clause = "WHERE animal_id = $1"
    if event_types:
        # Use = ANY with a non-empty array; postgres treats the
        # comparison as TRUE for matching rows. Empty list bypasses
        # the ``= ANY`` clause via the early return in the adapter.
        where_clause = "WHERE animal_id = $1 AND event_type = ANY($2::text[])"
    sql = (
        "SELECT id, animal_id, event_type, event_timestamp, created_by, "  # noqa: S608 — column names are constant; the only user-derived input is the event_types list which lands as a $N bind parameter
        "caused_by_event_id, source_entity_type, source_entity_id, "
        "legacy_source_table, legacy_source_id, metadata "
        "FROM animal_lifecycle_events "
        f"{where_clause} "
        "ORDER BY event_timestamp ASC, id ASC "
        "LIMIT $3 OFFSET $4"
    )
    if event_types:
        params: list[object] = [animal_id, list(event_types), str(limit), str(offset)]
    else:
        params = [animal_id, str(limit), str(offset)]
    return sql, params


# ``resolve_animal_photo`` — read the photo metadata for the ETag
# computation. The streaming fetch happens in the adapter against
# the storage client (NOT the postgres connection); the SQL only
# returns the metadata (nombrefoto + updated_at) the adapter needs
# to compute the ETag and decide whether the storage fetch is
# worth it (sentinel keys skip the fetch and return the placeholder
# PNG immediately).
GET_ANIMAL_PHOTO_META_SQL: str = (
    "SELECT \"NombreFoto\", updated_at FROM animales WHERE id = $1"
)


def get_animal_photo_meta_sql(animal_id: str) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the photo-metadata read."""
    return GET_ANIMAL_PHOTO_META_SQL, [animal_id]


__all__ = [
    "COUNT_ANIMALS_SQL",
    "DELETE_ANIMAL_SQL",
    "GET_ANIMAL_BY_ID_SQL",
    "GET_ANIMAL_BY_NCHIP_SQL",
    "GET_ANIMAL_PHOTO_META_SQL",
    "INSERT_ANIMAL_SQL",
    "LIST_ANIMALS_SQL",
    "LIST_LIFECYCLE_EVENTS_COLUMNS",
    "RECORD_LIFECYCLE_EVENT_COLUMNS",
    "SEARCH_ANIMALS_SQL",
    "UPDATE_ANIMAL_COLUMN_ORDER",
    "create_animal_sql",
    "count_animals_sql",
    "delete_animal_sql",
    "get_animal_by_nchip_sql",
    "get_animal_photo_meta_sql",
    "list_animals_sql",
    "list_lifecycle_events_sql",
    "record_lifecycle_event_sql",
    "search_animals_sql",
    "update_animal_sql",
]
