from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_fingerprint_component(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized, flags=re.UNICODE)
    return normalized


def job_fingerprint(*, company_name: str | None, title: str, city: str | None) -> str | None:
    company = normalize_fingerprint_component(company_name)
    normalized_title = normalize_fingerprint_component(title)
    normalized_city = normalize_fingerprint_component(city)
    if normalized_city.endswith("市"):
        normalized_city = normalized_city[:-1]
    if not company or not normalized_title or not normalized_city:
        return None
    payload = "|".join((company, normalized_title, normalized_city))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
