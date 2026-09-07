"""Pure domain types for the Cesiones slice.

No I/O, no LocalBackend, no FastAPI, no SQL.
Extracted from ``app.modules.cesiones.service`` per HR-2.
"""

from __future__ import annotations


class CesionConflictError(ValueError):
    """Raised when an attempt to create a cesión collides with the
    1-a-1 UNIQUE FK on ``cesiones_propietario.entrada_id``. Mirrors
    ``EntradaConflictError`` in the entradas module — both translate
    LocalBackend's 409 envelope into a domain-meaningful exception that
    routes can render as a 409 form error without depending on the
    LocalBackend envelope shape.
    """


# ---------------------------------------------------------------------------
# Public row types
# ---------------------------------------------------------------------------


class Cesion:
    """A public service-row representation for ``cesiones_propietario``.

    Field names follow the Access legacy CamelCase Spanish spelling
    (see ``docs/discovery/feature-02-intake-foster-adoption.md`` §"Owner
    surrender"). ``entrada_id`` is the FK to ``entradas.id``.
    """

    __slots__ = (
        "id",
        "entrada_id",
        "numero_contrato",
        "nombre_representante",
        "cartilla_sanitaria",
        "certificado_veterinario",
        "autorizacion_recogida",
        "fecha_vacuna_rabia",
        "numero_colegiado",
        "numero_colaborador",
        "dni_representante",
        "calle_representante",
        "numero_calle_representante",
        "piso_representante",
        "letra_representante",
        "localidad_representante",
        "provincia_representante",
        "cp_representante",
        "telefono_representante",
        "email_representante",
        "hora_cesion",
        "fecha_alta",
        "updated_at",
    )

    def __init__(  # noqa: PLR0913
        self,
        id: str,
        entrada_id: str,
        numero_contrato: str,
        nombre_representante: str,
        /,
        *,
        cartilla_sanitaria: str | None = None,
        certificado_veterinario: str | None = None,
        autorizacion_recogida: str | None = None,
        fecha_vacuna_rabia: str | None = None,
        numero_colegiado: str | None = None,
        numero_colaborador: str | None = None,
        dni_representante: str | None = None,
        calle_representante: str | None = None,
        numero_calle_representante: str | None = None,
        piso_representante: str | None = None,
        letra_representante: str | None = None,
        localidad_representante: str | None = None,
        provincia_representante: str | None = None,
        cp_representante: str | None = None,
        telefono_representante: str | None = None,
        email_representante: str | None = None,
        hora_cesion: str | None = None,
        fecha_alta: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        self.id = id
        self.entrada_id = entrada_id
        self.numero_contrato = numero_contrato
        self.nombre_representante = nombre_representante
        self.cartilla_sanitaria = cartilla_sanitaria
        self.certificado_veterinario = certificado_veterinario
        self.autorizacion_recogida = autorizacion_recogida
        self.fecha_vacuna_rabia = fecha_vacuna_rabia
        self.numero_colegiado = numero_colegiado
        self.numero_colaborador = numero_colaborador
        self.dni_representante = dni_representante
        self.calle_representante = calle_representante
        self.numero_calle_representante = numero_calle_representante
        self.piso_representante = piso_representante
        self.letra_representante = letra_representante
        self.localidad_representante = localidad_representante
        self.provincia_representante = provincia_representante
        self.cp_representante = cp_representante
        self.telefono_representante = telefono_representante
        self.email_representante = email_representante
        self.hora_cesion = hora_cesion
        self.fecha_alta = fecha_alta
        self.updated_at = updated_at

    def __repr__(self) -> str:
        return (
            f"Cesion(id={self.id!r}, entrada_id={self.entrada_id!r}, "
            f"numero_contrato={self.numero_contrato!r}, "
            f"nombre_representante={self.nombre_representante!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Cesion):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class Contrato:
    """A public service-row representation for ``contratos``.

    Just enough to keep the (Cesion, Contrato) return type explicit.
    Only the columns populated by the cesion workflow carry values; the
    other entity FKs (entrada, acogida, adopcion) are ``None`` per the
    ``contratos_exactly_one_entity`` CHECK constraint.
    """

    __slots__ = (
        "id",
        "tipo_contrato_id",
        "numero_contrato",
        "fecha",
        "cesion_id",
        "fecha_alta",
    )

    def __init__(  # noqa: PLR0913
        self,
        id: str,
        tipo_contrato_id: str,
        numero_contrato: str,
        fecha: str,
        /,
        *,
        cesion_id: str | None = None,
        fecha_alta: str | None = None,
    ) -> None:
        self.id = id
        self.tipo_contrato_id = tipo_contrato_id
        self.numero_contrato = numero_contrato
        self.fecha = fecha
        self.cesion_id = cesion_id
        self.fecha_alta = fecha_alta

    def __repr__(self) -> str:
        return (
            f"Contrato(id={self.id!r}, tipo_contrato_id={self.tipo_contrato_id!r}, "
            f"numero_contrato={self.numero_contrato!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Contrato):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
