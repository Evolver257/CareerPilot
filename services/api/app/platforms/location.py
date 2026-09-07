from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LocationParts:
    city: str | None
    district: str | None
    location: str | None


def split_location(value: str | None) -> LocationParts:
    text = " ".join((value or "").split()).strip()
    if not text:
        return LocationParts(None, None, None)
    parts = [part.strip() for part in re.split(r"[·|｜,/、]+", text) if part.strip()]
    city = parts[0] if parts else None
    if city and city.endswith("市"):
        city = city[:-1]
    district = parts[1] if len(parts) > 1 else None
    return LocationParts(city, district, text)
