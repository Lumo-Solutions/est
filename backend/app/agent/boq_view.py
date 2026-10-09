"""How the agent sees the BOQ: sections (top-level groups, or chunks of ungrouped lines) and their leaf lines.

Pure over a list of `BoqLineItem`-like rows so it is unit-testable without a database.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

CHUNK_SIZE = 40


@dataclass(slots=True)
class SectionSpec:
    section_item_id: UUID  # the group's own row; for a chunk of ungrouped lines, the chunk's first line
    item_no: str
    label: str
    line_ids: list[UUID]
    synthetic: bool = False
    uoms: dict[str, int] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)


def _label(item_no: str, description: str) -> str:
    return f"{item_no} {description}".strip()[:240]


def build_sections(items: list[Any]) -> list[SectionSpec]:
    """`items`: rows with id, parent_id, item_no, description, uom, boq_quantity, sort_order, path.

    A leaf line is one with a quantity. A top-level row that has descendants is a section of its leaf lines; top-level rows
    with no children are chunked together (a flat BOQ becomes sections of CHUNK_SIZE lines)."""
    by_id = {i.id: i for i in items}
    children: dict[UUID | None, list[Any]] = {}
    for i in sorted(items, key=lambda x: (str(x.path), x.sort_order)):
        children.setdefault(i.parent_id, []).append(i)

    def leaves(node: Any) -> list[Any]:
        out: list[Any] = []
        stack = [node]
        while stack:
            n = stack.pop(0)
            kids = children.get(n.id, [])
            if kids:
                stack = kids + stack
            elif n.boq_quantity is not None:
                out.append(n)
        return out

    sections: list[SectionSpec] = []
    loose: list[Any] = []
    for root in children.get(None, []):
        if not children.get(root.id):
            if root.boq_quantity is not None:
                loose.append(root)
            continue
        ls = leaves(root)
        if not ls:
            continue
        sections.append(_spec(root.id, root.item_no, _label(root.item_no, root.description), ls))
    for start in range(0, len(loose), CHUNK_SIZE):
        chunk = loose[start : start + CHUNK_SIZE]
        label = f"Lines {chunk[0].item_no} to {chunk[-1].item_no}"
        sections.append(_spec(chunk[0].id, f"{chunk[0].item_no}-{chunk[-1].item_no}", label, chunk, synthetic=True))
    del by_id
    return sections


def _spec(item_id: UUID, item_no: str, label: str, ls: list[Any], synthetic: bool = False) -> SectionSpec:
    uoms = Counter((l.uom or "").strip().lower() or "?" for l in ls)
    return SectionSpec(
        section_item_id=item_id, item_no=item_no, label=label, line_ids=[l.id for l in ls], synthetic=synthetic,
        uoms=dict(uoms.most_common(6)), samples=[l.description[:80] for l in ls[:3]],
    )


def find_section(sections: list[SectionSpec], key: str) -> SectionSpec | None:
    """By section id, item_no, or a piece of its label (3+ characters) (the model sees all three in boq_outline)."""
    key = key.strip()
    for s in sections:
        if str(s.section_item_id) == key or s.item_no == key:
            return s
    low = key.lower()
    if len(low) < 3:
        return None
    return next((s for s in sections if low in s.label.lower()), None)
