from __future__ import annotations

from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator, UserDefinedType

try:
    from pgvector.sqlalchemy import Vector as _PgVector
except ImportError:  # pragma: no cover - pgvector always installed in this project
    _PgVector = None

# Must match EMBEDDING_DIM's default in app/core/config.py and the vector
# width baked into migration 0009 (which independently reads
# get_settings().embedding_dim at MIGRATE TIME, when a real environment is
# guaranteed). This module-level constant intentionally does NOT read
# get_settings() -- doing so previously forced every import of app.models
# (including from pure unit tests with no .env at all) to require a fully
# configured Settings object just to build a column type. Changing the
# embedding model's dimension is a migration change either way, so a literal
# default here costs nothing and decouples model definitions from runtime
# config.
DEFAULT_EMBEDDING_DIM = 384


def EmbeddingVector(dim: int = DEFAULT_EMBEDDING_DIM) -> "_PgVector":
    return _PgVector(dim)


class Money(TypeDecorator):
    """NUMERIC(18,6) for unit rates / component amounts (A9)."""

    impl = Numeric(18, 6)
    cache_ok = True


class MoneyTotal(TypeDecorator):
    """NUMERIC(18,2) for totals and approval amounts (A9)."""

    impl = Numeric(18, 2)
    cache_ok = True


class Ltree(UserDefinedType):
    """Postgres `ltree` column (trade taxonomy hierarchy paths). Values are
    plain dotted strings ("earthworks.excavation") at the Python boundary;
    Postgres does the hierarchy operators (<@, @>, etc.)."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "LTREE"

    def bind_processor(self, dialect):  # noqa: ANN001
        def process(value):
            return value

        return process

    def result_processor(self, dialect, coltype):  # noqa: ANN001
        def process(value):
            return value

        return process
