"""Second copy of ``_opt`` — mirrors app/modules/foo/routes.py (seeded
duplication for the Detector 10 positive fixture)."""


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
