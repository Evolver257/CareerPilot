from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class EmbeddingType(TypeDecorator[list[float] | None]):
    """Use pgvector on PostgreSQL and JSON for SQLite test databases."""

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int = 384, **kwargs: Any) -> None:
        self.dimensions = dimensions
        super().__init__(**kwargs)

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())
