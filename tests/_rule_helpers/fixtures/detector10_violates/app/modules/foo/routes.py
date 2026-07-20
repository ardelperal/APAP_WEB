"""Positive fixture for Detector 10 (Rule 25): ``_opt`` defined here AND
in ``app/modules/bar/routes.py`` (neither file is in the real repo's
BASELINE_DUPLICATE_HELPERS, so both must be flagged as NEW drift)."""


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
