from __future__ import annotations

_BOSS_PRIVATE_DIGITS = str.maketrans(
    {chr(0xE031 + digit): str(digit) for digit in range(10)}
)


def decode_boss_salary(value: str | None) -> str | None:
    """Decode digits rendered through BOSS's kanzhun-mix private-use font."""
    return value.translate(_BOSS_PRIVATE_DIGITS) if value is not None else None
