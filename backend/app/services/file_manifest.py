"""The file manifest in the database: write one entry, search the project's entries (docs/boq-agent/plan.md §2).

Search = Postgres full-text rank fused with pgvector cosine rank (reciprocal rank fusion). Both are scoped to one project
and, through RLS, to its tenant; a missing embedding just means the file is found by text only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.intake.manifest import ManifestEntry
from app.models.tender_intake import ProjectFileIndex

RRF_K = 60
_TOKEN = re.compile(r"[A-Za-z0-9]{2,}")
MAX_QUERY_TERMS = 14


def text_query(query: str) -> str:
    """A tsquery that matches a file holding ANY of the words (prefix match), ranked by how many it holds. A tender question
    is a handful of words, rarely all of them in one file, so AND-ing them (the websearch default) finds nothing."""
    terms = list(dict.fromkeys(t.lower() for t in _TOKEN.findall(query or "")))[:MAX_QUERY_TERMS]
    return " | ".join(f"{t}:*" for t in terms)


async def upsert_entry(
    session: AsyncSession, ctx: RequestContext, *, project_id: UUID, document_id: UUID, entry: ManifestEntry,
    embedding: list[float] | None = None,
) -> None:
    values = dict(
        tenant_id=ctx.tenant_id, project_id=project_id, document_id=document_id, path=entry.path, folder=entry.folder,
        filename=entry.filename[:512], ext=entry.ext, size_bytes=entry.size_bytes, sha256=entry.sha256,
        page_count=entry.page_count, page_sizes=entry.page_sizes, page1_text=entry.page1_text,
        title_block_text=entry.title_block_text, sheets=entry.sheets, hints=entry.hints, hints_text=entry.hints_text,
        partial_index=entry.partial_index, partial_reason=entry.partial_reason, indexed_at=datetime.now(timezone.utc),
        embedding=embedding, created_by=ctx.user_id, updated_by=ctx.user_id,
    )
    stmt = pg_insert(ProjectFileIndex).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k not in ("tenant_id", "project_id", "document_id", "created_by")}
    await session.execute(stmt.on_conflict_do_update(constraint="uq_project_file_index_document", set_=update_cols))


@dataclass(slots=True)
class SearchHit:
    document_id: UUID
    path: str
    score: float
    text_rank: int | None
    vector_rank: int | None


async def search(
    session: AsyncSession, project_id: UUID, query: str, *, query_embedding: list[float] | None = None,
    folder_prefix: str | None = None, ext: str | None = None, doc_class: str | None = None, limit: int = 20,
) -> list[SearchHit]:
    """Top files for a query. Filters are optional and exact: a folder prefix, an extension, a rules doc_class hint."""
    where = ["project_id = :pid"]
    params: dict = {"pid": project_id, "lim": max(1, min(limit, 50)) * 4}
    if folder_prefix:
        where.append("(folder = :fp OR folder LIKE :fpl)")
        params["fp"], params["fpl"] = folder_prefix.rstrip("/"), folder_prefix.rstrip("/") + "/%"
    if ext:
        where.append("ext = :ext")
        params["ext"] = ext.lower().lstrip(".")
    if doc_class:
        where.append("hints->>'doc_class' = :dc")
        params["dc"] = doc_class
    clause = " AND ".join(where)
    ranks: dict[UUID, dict] = {}
    paths: dict[UUID, str] = {}
    tsq = text_query(query)
    if tsq:
        rows = (
            await session.execute(
                text(
                    f"SELECT document_id, path FROM project_file_index WHERE {clause} "
                    "AND search_tsv @@ to_tsquery('simple', :q) "
                    "ORDER BY ts_rank_cd(search_tsv, to_tsquery('simple', :q)) DESC LIMIT :lim"
                ),
                {**params, "q": tsq},
            )
        ).all()
        for i, (doc_id, path) in enumerate(rows, start=1):
            ranks.setdefault(doc_id, {})["text"] = i
            paths[doc_id] = path
    if query_embedding is not None:
        vec = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"
        rows = (
            await session.execute(
                text(
                    f"SELECT document_id, path FROM project_file_index WHERE {clause} AND embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:v AS vector) LIMIT :lim"
                ),
                {**params, "v": vec},
            )
        ).all()
        for i, (doc_id, path) in enumerate(rows, start=1):
            ranks.setdefault(doc_id, {})["vec"] = i
            paths[doc_id] = path
    hits = [
        SearchHit(
            d, paths[d], sum(1.0 / (RRF_K + r) for r in rk.values()), rk.get("text"), rk.get("vec"),
        )
        for d, rk in ranks.items()
    ]
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[: max(1, min(limit, 50))]


async def get_entry(session: AsyncSession, project_id: UUID, document_id: UUID) -> ProjectFileIndex | None:
    return (
        await session.execute(
            select(ProjectFileIndex).where(ProjectFileIndex.project_id == project_id, ProjectFileIndex.document_id == document_id)
        )
    ).scalar_one_or_none()


async def copy_entry(session: AsyncSession, ctx: RequestContext, doc) -> bool:
    """A byte-identical file (same sha256) is not read again: it gets the original's entry under its own path."""
    if doc.duplicate_of_id is None:
        return False
    original = await get_entry(session, doc.project_id, doc.duplicate_of_id)
    if original is None:
        return False
    entry = ManifestEntry(
        path=doc.archive_path or doc.original_filename, folder=original.folder if doc.archive_path is None else (doc.archive_path.rsplit("/", 1)[0] if "/" in doc.archive_path else ""),
        filename=doc.original_filename, ext=original.ext, size_bytes=original.size_bytes, sha256=original.sha256,
        page_count=original.page_count, page_sizes=original.page_sizes, page1_text=original.page1_text,
        title_block_text=original.title_block_text, sheets=original.sheets, hints=original.hints, hints_text=original.hints_text,
        partial_index=original.partial_index, partial_reason=original.partial_reason,
    )
    await upsert_entry(session, ctx, project_id=doc.project_id, document_id=doc.id, entry=entry, embedding=original.embedding)
    return True
