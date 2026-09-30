"""DWG conversion: the derived-DXF link on drawings.

A DWG upload is kept as the original (kind='dwg'); the DXF the converter
sandbox produces from it lives in S3 next to it and is described by these
columns, so one drawing row still owns the sheets/entities/measurements and
the UI can offer both files. Plain columns on an existing RLS-protected
table: no new table, no policy change. drawings.kind/status are free
varchar(16) columns (no CHECK), so the new 'dwg' kind and the
'converting'/'needs_conversion' statuses need no DDL.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def _columns() -> list[sa.Column]:
    return [
        sa.Column("derived_object_key", sa.String(512), nullable=True),
        sa.Column("derived_sha256", sa.String(64), nullable=True),
        sa.Column("derived_size_bytes", sa.Integer, nullable=True),
        sa.Column("converter_version", sa.String(32), nullable=True),
        sa.Column("conversion_target", sa.String(16), nullable=True),
        sa.Column("converted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("conversion_ms", sa.Integer, nullable=True),
        # Machine-readable failure reason when status='needs_conversion':
        # timeout | convert_failed | not_installed | disabled | unavailable.
        sa.Column("conversion_reason", sa.String(24), nullable=True),
    ]


def upgrade() -> None:
    for col in _columns():
        op.add_column("drawings", col)


def downgrade() -> None:
    for col in reversed(_columns()):
        op.drop_column("drawings", col.name)
