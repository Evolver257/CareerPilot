"""decode BOSS private-font salary digits

Revision ID: 0008_decode_boss_salary
Revises: 0007_browser_tasks
Create Date: 2026-08-26
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0008_decode_boss_salary"
down_revision: str | None = "0007_browser_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRIVATE_DIGITS = str.maketrans(
    {chr(0xE031 + digit): str(digit) for digit in range(10)}
)
_SALARY_RANGE = re.compile(r"(\d{1,3})\s*[kK]?\s*[-–~至]\s*(\d{1,3})")


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        return value.translate(_PRIVATE_DIGITS)
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode(item) for key, item in value.items()}
    return value


def upgrade() -> None:
    jobs = sa.table(
        "jobs",
        sa.column("id", sa.Uuid()),
        sa.column("platform", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("raw_data", sa.JSON()),
        sa.column("normalized_data", sa.JSON()),
        sa.column("salary_min", sa.Integer()),
        sa.column("salary_max", sa.Integer()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            jobs.c.id,
            jobs.c.description,
            jobs.c.raw_data,
            jobs.c.normalized_data,
            jobs.c.salary_min,
            jobs.c.salary_max,
        ).where(jobs.c.platform == "boss")
    ).mappings()

    for row in rows:
        description = _decode(row.description)
        raw_data = _decode(row.raw_data or {})
        normalized_data = _decode(row.normalized_data or {})
        salary_text = raw_data.get("salary_text")
        was_decoded = raw_data != (row.raw_data or {})
        if was_decoded:
            raw_data["salary_encoding_decoded"] = True

        salary_min = row.salary_min
        salary_max = row.salary_max
        match = _SALARY_RANGE.search(salary_text) if isinstance(salary_text, str) else None
        if match:
            salary_min, salary_max = (int(value) for value in match.groups())
            structured_job = normalized_data.get("structured_job")
            if isinstance(structured_job, dict):
                salary = structured_job.get("salary")
                if isinstance(salary, dict):
                    salary["minimum"] = salary_min
                    salary["maximum"] = salary_max
                    salary["currency"] = "CNY"

        if (
            description != row.description
            or raw_data != (row.raw_data or {})
            or normalized_data != (row.normalized_data or {})
            or salary_min != row.salary_min
            or salary_max != row.salary_max
        ):
            connection.execute(
                jobs.update()
                .where(jobs.c.id == row.id)
                .values(
                    description=description,
                    raw_data=raw_data,
                    normalized_data=normalized_data,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    updated_at=sa.func.now(),
                )
            )


def downgrade() -> None:
    # Decoding restores the user-visible salary and is intentionally irreversible.
    pass
