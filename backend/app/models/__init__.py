"""Import every model module so Base.metadata is fully populated for Alembic
autogenerate and for app startup. Do not import individual models from
elsewhere via `app.models.<module>` in application code paths that run
before this module -- always `import app.models` first (main.py and
migrations/env.py both do)."""

from app.models import (  # noqa: F401
    approvals,
    audit,
    boq,
    costlib,
    prequal,
    procurement,
    quotation_ingestion,
    semantic_matching,
    settlement,
    takeoff,
    taxonomy,
    tenancy,
    typology,
    vendors,
)

__all__ = [
    "approvals",
    "audit",
    "boq",
    "costlib",
    "prequal",
    "procurement",
    "quotation_ingestion",
    "semantic_matching",
    "settlement",
    "takeoff",
    "taxonomy",
    "tenancy",
    "typology",
    "vendors",
]
