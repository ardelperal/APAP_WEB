"""Clean fixture for Detector 10 (Rule 25): a watched helper name
defined in exactly one file must NOT be flagged."""


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
