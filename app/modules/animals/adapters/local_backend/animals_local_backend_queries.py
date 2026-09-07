"""SQL for the animals slice (AGENTS.md §22: SQL in exactly one place).

Selects the complete hexagonal :class:`Animal` read shape.
``FNacimiento`` comes back as an ISO 8601 string from LocalBackend's
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


def _exact_search_filter(
    condition: str,
    value: object | None,
) -> tuple[str, object] | None:
    """Return one exact-match filter only when its value is present."""
    return (condition, value) if value else None


def _name_search_filter(q: str | None) -> tuple[str, object] | None:
    """Return the wrapped substring-name filter when requested."""
    return ('a."NombreAnimal" ILIKE', f"%{q}%") if q else None


def _append_search_filter(
    conditions: list[str],
    params: list[object],
    search_filter: tuple[str, object] | None,
) -> None:
    """Append one optional condition and its correctly numbered bind."""
    if search_filter is None:
        return
    condition, value = search_filter
    params.append(value)
    conditions.append(f"{condition} ${len(params)}")


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

    identity_filter = _exact_search_filter('a."NCHIP" =', chip) or _name_search_filter(q)
    _append_search_filter(conditions, params, identity_filter)
    _append_search_filter(
        conditions, params, _exact_search_filter('a."Especie" =', especie)
    )
    _append_search_filter(
        conditions, params, _exact_search_filter('a."Sexo" =', sexo)
    )

    db_estado = _ESTADO_TO_DB_LABEL.get(estado or "")
    join_clause = "LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
    _append_search_filter(
        conditions, params, _exact_search_filter("acs.current_state =", db_estado)
    )
    _append_search_filter(
        conditions,
        params,
        _exact_search_filter("a.fecha_alta >=", fecha_alta_since),
    )
    _append_search_filter(
        conditions,
        params,
        _exact_search_filter("a.fecha_alta <=", fecha_alta_until),
    )

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
    LocalBackend client serialises bind parameters as strings on the
    wire; the integer values land in postgres via an implicit text→int8 cast.
    """
    where_clause = "WHERE activo = TRUE " if activo_only else ""
    return (
        LIST_ANIMALS_SQL.format(where_clause=where_clause),
        [str(limit), str(offset)],
    )


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
# ``metadata`` is JSON-typed on the wire; the LocalBackend client
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


# ``resolve_animal_photo`` — read the storage key. The streaming fetch happens
# in the adapter against
# the storage client (NOT the postgres connection); the SQL only
# returns the key the adapter needs to decide whether the storage fetch is
# worth it (sentinel keys skip the fetch and return the placeholder
# PNG immediately).
GET_ANIMAL_PHOTO_META_SQL: str = (
    "SELECT \"NombreFoto\" FROM animales WHERE id = $1"
)


def get_animal_photo_meta_sql(animal_id: str) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the photo-metadata read."""
    return GET_ANIMAL_PHOTO_META_SQL, [animal_id]


__all__ = [
    "COUNT_ANIMALS_SQL",
    "GET_ANIMAL_BY_ID_SQL",
    "GET_ANIMAL_BY_NCHIP_SQL",
    "GET_ANIMAL_PHOTO_META_SQL",
    "LIST_ANIMALS_SQL",
    "LIST_LIFECYCLE_EVENTS_COLUMNS",
    "RECORD_LIFECYCLE_EVENT_COLUMNS",
    "SEARCH_ANIMALS_SQL",
    "count_animals_sql",
    "get_animal_by_nchip_sql",
    "get_animal_photo_meta_sql",
    "list_animals_sql",
    "list_lifecycle_events_sql",
    "record_lifecycle_event_sql",
    "search_animals_sql",
]
