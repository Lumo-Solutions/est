"""Production-scale intake: resumable uploads, per-file dispatch, pack controls.

* tender_packages.expected_count / paused_at / cancelled_at: the uploader registers every file up front, so a pack
  knows how many files it is waiting for; pause and cancel are recorded on the pack (statuses `uploading`, `paused`
  and `cancelled` join the existing ones; the column is a plain varchar, so no type change).
* project_documents.uploaded_at / queued_at / attempts: a document is `pending_upload` until its bytes arrive, is
  enqueued from the database (queued_at) one file at a time, and counts how often a worker started it.
* Partial indexes for the dispatcher / sweeper and the paged document lists.

Existing rows are untouched: queued_at stays NULL, so a file left in `received` by a lost broker message is picked up
by the dispatcher the first time it runs (that is how a crashed pack resumes). Row-level security already covers
these columns (same tables, same policies).

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-01 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tender_packages", sa.Column("expected_count", sa.Integer, nullable=True))
    op.add_column("tender_packages", sa.Column("paused_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("tender_packages", sa.Column("cancelled_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("project_documents", sa.Column("uploaded_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("project_documents", sa.Column("queued_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("project_documents", sa.Column("attempts", sa.Integer, nullable=False, server_default="0"))
    op.execute("UPDATE project_documents SET uploaded_at = created_at WHERE uploaded_at IS NULL")
    # Dispatcher / sweeper: only files that still have work to do.
    op.create_index(
        "ix_project_documents_open_work",
        "project_documents",
        ["status", "queued_at", "created_at"],
        postgresql_where=sa.text("status IN ('received', 'processing')"),
    )
    op.create_index("ix_project_documents_package_status", "project_documents", ["package_id", "status"])
    op.create_index("ix_project_documents_duplicate_of_id", "project_documents", ["duplicate_of_id"])


def downgrade() -> None:
    op.drop_index("ix_project_documents_duplicate_of_id", table_name="project_documents")
    op.drop_index("ix_project_documents_package_status", table_name="project_documents")
    op.drop_index("ix_project_documents_open_work", table_name="project_documents")
    op.drop_column("project_documents", "attempts")
    op.drop_column("project_documents", "queued_at")
    op.drop_column("project_documents", "uploaded_at")
    op.drop_column("tender_packages", "cancelled_at")
    op.drop_column("tender_packages", "paused_at")
    op.drop_column("tender_packages", "expected_count")
