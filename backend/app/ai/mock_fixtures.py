"""Default, deterministic answers for the MOCK provider: what a competent model would return for the synthetic

tender pack (app/demo/ai_demo.py) and for ordinary tender documents, derived from the request content by

plain rules. They exist so every AI feature runs end to end, in tests and on the keyless dev stack, with

schema-valid output and no network.



They are NOT a model and make no claim to be one: the eval harness (`make ai-eval`) reports their accuracy

against the golden sets honestly, and a real provider is swapped in by configuration only.

Tasks: intake_classify, boq_pdf_rows, drawing_annotations, boq_interpret, evidence_rank, cost_choose,

markup_advise. Anything else falls back to the smallest schema-valid instance.

"""



from __future__ import annotations



import re

from collections.abc import Callable

from typing import Any



from app.ai.provider import AIRequest



Handler = Callable[[AIRequest], dict[str, Any]]



# ------------------------------------------------------------------ shared text helpers



_WORD = re.compile(r"[a-z0-9]+")

# word -> the single concept it stands for (so synonyms never inflate an overlap count)

_CONCEPT: dict[str, str] = {

    "formation": "corridor", "compact": "corridor", "trim": "corridor", "carriageway": "corridor", "road": "corridor",

    "corridor": "corridor", "asphalt": "asphalt", "wearing": "asphalt",

    "centre": "alignment", "center": "alignment", "centreline": "alignment", "centerline": "alignment", "cl": "alignment",

    "alignment": "alignment", "marking": "marking",

    "sewer": "pipe", "drain": "pipe", "pipe": "pipe", "storm": "pipe", "network": "pipe", "run": "pipe",

    "manhole": "manhole", "mh": "manhole", "chamber": "manhole",

    "kerb": "kerb", "curb": "kerb", "trees": "tree", "tree": "tree", "turfing": "turf", "turf": "turf",

    "excavate": "excavation", "excavation": "excavation", "topsoil": "topsoil",

}

_STOP = {"and", "the", "for", "with", "all", "any", "of", "to", "in", "on", "at", "or", "a", "an", "incl", "including", "complete",

         "supply", "place", "type", "thick", "receive", "level", "existing", "approved", "each", "layer", "trade", "unclassified",

         "summed", "runs", "length", "area", "nos", "see", "schedule"}





def _words(text: str) -> list[str]:

    return _WORD.findall(text.lower())





def _keywords(text: str) -> set[str]:

    out: set[str] = set()

    for w in _words(text):

        if w in _STOP or len(w) < 3 or w.isdigit():

            continue

        out.add(_CONCEPT.get(w, w))

    return out





def _sizes(text: str) -> set[str]:

    """Numbers that look like sizes/diameters (150, 300, 1200): 3-4 digits, optionally followed by mm."""

    t = text.lower().replace(",", "")

    return set(re.findall(r"(?<![\d.])(\d{3,4})(?![\d.]*\s*(?:m2|m3|nos|nr)\b)", t)) - {"2026", "2025", "2024"}





def _score(desc: str, label: str) -> float:

    """0..1 plausibility that `label` (a drawing item or a cost item) describes `desc`."""

    dk, lk = _keywords(desc), _keywords(label)

    overlap = len(dk & lk)

    word_part = min(1.0, overlap / 1.5)

    ds, ls = _sizes(desc), _sizes(label)

    if ds and ls:

        size_part = 1.0 if ds & ls else -0.5

    else:

        size_part = 0.0

    penalty = 0.3 if ("existing" in desc.lower() and "existing" not in label.lower()) else 0.0   # works on something already there

    return max(0.0, min(1.0, 0.5 * word_part + 0.4 * size_part + (0.1 if overlap else 0.0) - penalty))





def _blocks(user: str) -> list[tuple[str, str]]:

    """Splits a prompt into (line id, body) for `<<<LINE id=...` blocks."""

    out = []

    for chunk in user.split("<<<LINE id=")[1:]:

        lid, _, body = chunk.partition("\n")

        out.append((lid.strip(), body))

    return out





# ------------------------------------------------------------------ intake_classify
# A stand-in for a model that reads the document, not the folder: it looks only at the filename and the text between
# the DOCUMENT markers, ignores the folder path and the rule hints in the prompt, and ignores text that tries to
# instruct it. Confidence follows how clearly the document states what it is (a title in the first lines is
# confident; a cue deep in the body or a filename alone is not).

_DOC_TEXT = re.compile(r"<<<DOCUMENT TEXT\n(.*?)\nDOCUMENT TEXT>>>", re.S)
_DOC_BLOCK = re.compile(r"<<<DOCUMENT TITLE BLOCK\n(.*?)\nDOCUMENT TITLE BLOCK>>>", re.S)
_FILE_TYPE = re.compile(r"^File type: (\w+)", re.M)

_CLASS_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("addendum", (r"addendum\s*(?:no\.?|number|#)?\s*\d+", r"\baddendum\b")),
    ("boq", (r"bills?\s+of\s+quantit", r"schedules?\s+of\s+quantit")),
    ("correspondence", (r"dear\s+(?:sirs?|madam|mr|ms)\b", r"yours\s+(?:faithfully|sincerely)", r"further\s+to\s+(?:our|your)\b")),
    ("contract", (r"conditions\s+of\s+contract", r"\bfidic\b", r"particular\s+conditions", r"general\s+conditions")),
    ("tender_instructions", (r"instructions\s+to\s+(?:tenderers|bidders)",)),
    ("tender_forms", (r"form\s+of\s+tender", r"bid\s+bond", r"performance\s+(?:bond|guarantee)", r"bid\s+security")),
    ("clarification", (r"request\s+for\s+information", r"\brfi\s*(?:no\.?|#)?\s*\d+", r"clarification\s*(?:no\.?|#)\s*\d+", r"response\s+to\s+(?:query|queries|rfi)")),
    ("site_investigation", (r"geotechnical", r"soil\s+investigation", r"site\s+investigation", r"\bborehole")),
    ("programme", (r"\bprogramme\b", r"\bgantt\b", r"baseline\s+(?:programme|schedule)")),
    ("specification", (r"\bspecifications?\b", r"part\s+1\s*[-:]?\s*general", r"\bsection\s+\d{2}\s?\d{2}\s?\d{2}\b")),
)
_FILENAME_CUES: tuple[tuple[str, str], ...] = (
    ("addendum", r"addend"), ("boq", r"\bboq\b|bill[-_ ]of[-_ ]quant"), ("specification", r"\bspec"),
    ("contract", r"contract|conditions"), ("tender_instructions", r"\bitt\b|instructions"),
    ("tender_forms", r"form[-_ ]of[-_ ]tender|\bbond\b"), ("clarification", r"\brfi\b|clarification"),
    ("programme", r"\bprog(?:ramme)?\b|gantt"), ("site_investigation", r"geotech|soil|borehole"),
    ("correspondence", r"letter|correspondence|email"), ("drawing", r"\bdwg\b|\b[a-z]{1,3}-\d{2,4}\b"),
)
_DISCIPLINE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stormwater", ("storm", "surface water", "culvert")),
    ("sewer", ("sewer", "sewage", "foul", "manhole schedule")),
    ("water_supply", ("water supply", "potable", "water main", "water network", "ductile iron")),
    ("irrigation", ("irrigation", "drip line", "sprinkler")),
    ("electrical_lighting", ("street light", "streetlight", "lighting", "electrical", "luminaire")),
    ("telecom", ("telecom", "duct bank", "fibre", "fiber", "communication")),
    ("landscape", ("landscape", "planting", "softscape", "hardscape")),
    ("structural", ("structural", "reinforc", "foundation", "footing", "column schedule")),
    ("architectural", ("architectural", "floor plan", "elevation", "ceiling plan", "door schedule")),
    ("mep", ("mechanical", "hvac", "plumbing", "fire fighting", "mep")),
    ("roads_civil", ("road", "highway", "pavement", "carriageway", "kerb", "earthwork", "civil", "grading")),
)
_DRAWING_TYPE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("location_plan", ("location plan", "key plan", "location map", "site location")),
    ("plan_profile", ("plan and profile", "plan & profile", "longitudinal", "long section", "long-section")),
    ("cross_sections", ("cross section", "cross-section", "cross sections")),
    ("typical_details", ("typical detail", "standard detail", "typical section", "typical details")),
    ("setting_out", ("setting out", "setting-out", "coordinate table", "setting out points")),
    ("schedules", ("schedule",)),
    ("general_arrangement", ("general arrangement", "layout", "site plan", "master plan", " plan")),
)
_UNIT_TYPE = re.compile(r"\b(?:villa|unit|house|plot)\s*type\s*[-:]?\s*([A-Z]?\d{1,2}[A-Z]?|[A-D])\b|\btype\s*([0-9]{1,2}[A-Z]?)\b", re.I)
_INSTRUCTION_LINE = re.compile(
    r"ignore\s+(?:all\s+|any\s+|the\s+)*(?:previous|prior|above|earlier)|disregard|(?:classify|mark|label|file|treat|set)\s+(?:this|it|the\s+document)\s+as"
    r"|auto[-\s]?accept|approve|set\s+(?:the\s+)?confidence|confidence\s*(?:=|:|of|to)|you\s+are\s+now|new\s+instructions|system\s+prompt",
    re.I,
)
COMPROMISED_MARKER = "[[MOCK-COMPROMISED]]"  # a test hook: makes the mock behave like a model that obeyed the document


def _first_hit(text: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m
    return None


def intake_classify(req: AIRequest) -> dict[str, Any]:
    from app.intake.extract import DocContent
    from app.intake.metadata import extract_metadata

    user = req.user
    fname = re.search(r"^Filename: (.*)$", user, re.M)
    name = (fname.group(1) if fname else "").strip()
    ft = _FILE_TYPE.search(user)
    ftype = (ft.group(1) if ft else "").lower()
    body_m, block_m = _DOC_TEXT.search(user), _DOC_BLOCK.search(user)
    raw_body = body_m.group(1) if body_m else ""
    raw_block = block_m.group(1) if block_m else ""
    compromised = COMPROMISED_MARKER in raw_body
    steered = bool(_INSTRUCTION_LINE.search(raw_body) or _INSTRUCTION_LINE.search(raw_block))
    # A model that resists drops instruction-like lines before it reads; what is left is the real document.
    body = "\n".join(line for line in raw_body.splitlines() if not _INSTRUCTION_LINE.search(line))
    block = "\n".join(line for line in raw_block.splitlines() if not _INSTRUCTION_LINE.search(line))
    text = f"{block}\n{body}"
    low = text.lower()
    head = "\n".join(body.strip().splitlines()[:6])[:500].lower() + "\n" + block.lower()

    cls, quote, conf = "other", "", 0.4
    has_sheet_headers = "[sheet:" in low and "description" in low and "unit" in low and ("qty" in low or "quantity" in low)
    has_activity = "[sheet:" in low and "activity" in low and ("start" in low or "finish" in low)
    title_block_drawing = bool(re.search(r"drawing\s*(?:no|number)|dwg\s*no", block, re.I)) or bool(
        re.search(r"drawing\s*(?:no|number)", head, re.I) and re.search(r"\b(?:scale|rev)", low)
    )
    if ftype == "dxf":
        cls, quote, conf = "drawing", "DXF drawing file", 0.96
    elif title_block_drawing:
        m = re.search(r"drawing\s*(?:no\.?|number)[^\n]*", text, re.I)
        cls, quote, conf = "drawing", (m.group(0) if m else "title block")[:120], 0.94
    elif has_sheet_headers:
        cls, quote, conf = "boq", "Item / Description / Unit / Qty column headings", 0.96
    elif has_activity:
        cls, quote, conf = "programme", "Activity / Start / Finish columns", 0.9
    else:
        best: tuple[float, str, str] | None = None
        for candidate, patterns in _CLASS_CUES:
            m = _first_hit(head, patterns)
            if m:
                score, at = 0.93, m.group(0)
            else:
                m = _first_hit(low, patterns)
                if not m:
                    continue
                score, at = 0.78, m.group(0)
            if best is None or score > best[0]:
                best = (score, candidate, at)
        if best:
            conf, cls, quote = best
        else:
            for candidate, pat in _FILENAME_CUES:
                if re.search(pat, name, re.I):
                    cls, quote, conf = candidate, name, 0.58
                    break
            else:
                if req.images:
                    cls, quote, conf = "drawing", "scanned page image", 0.55  # an image-only page nothing else matched
    if steered:
        conf = min(conf, 0.6)  # the prompt tells a model to be less sure of text that tries to steer it

    md = extract_metadata(DocContent(filename=name, ext=ftype, sniffed=None, text=body, title_block_text=block))
    out: dict[str, Any] = {"doc_class": cls, "confidence": round(conf, 3), "evidence_quote": quote[:190], "evidence_page": 1}
    meta: dict[str, Any] = {}
    if cls == "drawing":
        # What the sheet is called (its TITLE line and first lines) decides; the rest of the text only fills in when the title is silent.
        title_low = "\n".join(
            [ln for ln in text.splitlines() if re.match(r"\s*(?:sheet\s+)?title\s*[:\-]", ln, re.I)]
            + [ln for ln in body.splitlines() if ln.strip() and not ln.startswith("[Page")][:2]
        ).lower()
        disc = next((d for d, words in _DISCIPLINE_CUES if any(w in title_low for w in words)), None) or next(
            (d for d, words in _DISCIPLINE_CUES if any(w in low for w in words)), None
        )
        dtype = next((d for d, words in _DRAWING_TYPE_CUES if any(w in title_low for w in words)), None) or next(
            (d for d, words in _DRAWING_TYPE_CUES if any(w in low for w in words)), None
        )
        out["sub_type"], out["drawing_type"] = disc, dtype
        m = _UNIT_TYPE.search(text)
        if m:
            meta["unit_type"] = f"Type {(m.group(1) or m.group(2)).upper()}"
        for key in ("document_number", "title", "revision", "scale", "sheet_number"):
            if md.get(key):
                meta[key] = md[key]
    elif cls == "addendum":
        for key in ("addendum_number", "addendum_issue_date", "supersedes", "amends", "title"):
            if md.get(key):
                meta[key] = md[key]
    elif cls == "boq" and md.get("header_row"):
        meta["header_row"] = md["header_row"]
    if meta:
        out["metadata"] = meta
    if compromised:
        # What a model that obeyed the document would emit: a wrong class, full confidence and action-looking keys.
        # The gateway drops unknown keys and the pipeline treats the rest as a proposal, so none of it may take effect.
        out.update({"doc_class": "drawing", "confidence": 1.0, "action": "approve", "route": "boq_wizard", "auto_accept": True})
    return out


# ------------------------------------------------------------------ boq_pdf_rows



_ROW = re.compile(r"^\s*(\d+(?:\.\d+)*[A-Za-z]?)\s+(.+?)\s+(m3|m2|m|nr|no|nos|item|ls|kg|t|sum)\s+([\d,]+(?:\.\d+)?)\b", re.I)





_HEADING = re.compile(r"^\s*(\d+)\s+([A-Z][A-Z &/-]{3,})\s*$")





def boq_pdf_rows(req: AIRequest) -> dict[str, Any]:

    if req.images:

        from app.demo import bitgrid



        decoded = bitgrid.decode(req.images[0].data)

        if decoded and decoded.get("rows"):

            rows = [

                {"item_no": r.get("item_no"), "description": r["description"], "unit": r.get("unit"), "quantity": r.get("quantity")}

                for r in decoded["rows"]

            ]

            return {"is_boq_table": True, "rows": rows, "confidence": 0.9}

    rows = []

    for line in req.user.splitlines():

        if re.search(r"brought forward|carried forward|collection|total", line, re.I):

            continue

        h = _HEADING.match(line)

        if h and not _ROW.match(line):

            rows.append({"item_no": h.group(1), "description": h.group(2).strip(), "unit": None, "quantity": None})

            continue

        m = _ROW.match(line)

        if m:

            rows.append({"item_no": m.group(1), "description": m.group(2).strip(), "unit": m.group(3),

                         "quantity": float(m.group(4).replace(",", ""))})

    return {"is_boq_table": bool(rows), "rows": rows, "confidence": 0.75 if rows else 0.3}





# ------------------------------------------------------------------ drawing_annotations



_LEN = re.compile(r"\bL\s*=\s*([\d,]+(?:\.\d+)?)\s*m\b(.*)", re.I)

_AREA = re.compile(r"([\d,]+(?:\.\d+)?)\s*m2\b", re.I)

_VOL = re.compile(r"([\d,]+(?:\.\d+)?)\s*m3\b", re.I)

_COUNT = re.compile(r"(?<![\w.])([\d,]+)\s*(nos|no\.|nr)\b(.*)", re.I)

_BARE_LEN = re.compile(r"^([\d,]+(?:\.\d+)?)\s*m\b\s*(.*)$", re.I)

_LENGTH_WORD = re.compile(r"(?:^|\s)([A-Z][A-Z ]*?)\s+L\s*=\s*([\d,]+(?:\.\d+)?)\s*m\b", re.I)





def _num(s: str) -> float:

    return float(s.replace(",", ""))





def drawing_annotations(req: AIRequest) -> dict[str, Any]:

    m = re.search(r"<<<SHEET TEXT\n(.*?)\nSHEET TEXT>>>", req.user, re.S)

    text = m.group(1) if m else ""

    title: dict[str, Any] = {}

    for key, pat in (("drawing_number", r"DRAWING NO[:.]?\s*(\S+)"), ("revision", r"\bREV[:.]?\s*(\S+)"),

                     ("scale_text", r"SCALE[:.]?\s*(1\s*:\s*\d+)"), ("sheet_title", r"TITLE[:.]?\s*(.+)")):

        mm = re.search(pat, text, re.I)

        if mm:

            title[key] = mm.group(1).strip()

    annotations, legend, schedule = [], [], []

    for raw in (ln.strip() for ln in text.splitlines()):

        if not raw:

            continue

        if raw.upper().startswith(("LEGEND", "PROPOSED ", "EXISTING ")):

            legend.append({"label": raw.split(":", 1)[-1].strip()})

            continue

        if re.match(r"MH-\d+", raw, re.I):

            schedule.append([c.strip() for c in re.split(r"\s{2,}|\|", raw) if c.strip()])

            continue

        ml, mc, ma, mv = _LEN.search(raw), _COUNT.search(raw), _AREA.search(raw), _VOL.search(raw)

        bare = None if (ml or mc or ma or mv) else _BARE_LEN.match(raw)

        if bare:

            annotations.append({"text": raw[:200], "kind": "length", "value": _num(bare.group(1)), "unit": "m", "material": bare.group(2).strip() or None})

        elif ml:

            annotations.append({"text": raw[:200], "kind": "length", "value": _num(ml.group(1)), "unit": "m", "material": ml.group(2).strip() or None})

        elif mv:

            annotations.append({"text": raw[:200], "kind": "volume", "value": _num(mv.group(1)), "unit": "m3", "material": None})

        elif ma:

            annotations.append({"text": raw[:200], "kind": "area", "value": _num(ma.group(1)), "unit": "m2", "material": None})

        elif mc:

            annotations.append({"text": raw[:200], "kind": "count", "value": _num(mc.group(1)), "unit": "nos", "material": mc.group(3).strip() or None})

    return {"title_block": title, "scale_notes": [t for t in re.findall(r"SCALE[:.]?\s*1\s*:\s*\d+", text, re.I)][:3],

            "legend": legend, "schedule": schedule, "annotations": annotations, "confidence": 0.85}





# ------------------------------------------------------------------ boq_interpret



def boq_interpret(req: AIRequest) -> dict[str, Any]:

    from app.verification.engine import LineInput, interpret_by_rules



    lines = []

    for lid, body in _blocks(req.user):

        m = re.search(r"Item (\S+) \[(.*?)\]: (.*)", body)

        if not m:

            continue

        uom = None if m.group(2) == "no unit" else m.group(2)

        it = interpret_by_rules(LineInput(id=lid, item_no=m.group(1), description=m.group(3), uom=uom, quantity=None))

        lines.append({"id": lid, "work_type": it.work_type, "material": it.material, "size_mm": it.size_mm, "unit": uom,

                      "trade": None, "keywords": it.keywords[:6]})

    return {"lines": lines}





# ------------------------------------------------------------------ evidence_rank



_CAND = re.compile(r"- ref=(\S+) \| (\w+) \| (.*?) \| ([\-\d.,]+) (\S*)")





def evidence_rank(req: AIRequest) -> dict[str, Any]:

    out = []

    for lid, body in _blocks(req.user):

        m = re.search(r"Item (\S+) \[(.*?)\]: (.*)", body)

        desc = m.group(3) if m else ""

        scored = []

        for ref, kind, label, _val, _unit in _CAND.findall(body):

            scored.append((ref, kind, label, _score(desc, label)))

        if not scored:

            continue

        best = max(s for *_x, s in scored)

        ranked = []

        for ref, kind, label, s in sorted(scored, key=lambda t: -t[3]):

            selected = best >= 0.4 and s >= best - 0.02 and s >= 0.4
            if kind == "measurement" or ref.startswith(("m:", "g:")):
                selected = selected or s >= 0.6   # measured geometry that agrees is kept even when an annotation words it better

            reason = ("wording and size agree with the drawing item" if s >= 0.6 else "partly agrees" if s >= 0.4 else "different item")

            ranked.append({"ref": ref, "score": round(max(s, 0.7), 3) if selected else round(s, 3), "selected": selected, "reason": reason})

        # a measured item and an annotation restating it are the same thing: keep one (measured wins)

        measured = [r for r in ranked if r["selected"] and r["ref"].startswith(("m:", "g:"))]

        if measured:

            for r in ranked:

                if r["ref"].startswith("a:"):

                    r["selected"] = False

        out.append({"id": lid, "ranked": ranked})

    return {"lines": out}





# ------------------------------------------------------------------ cost_choose



_COST_CAND = re.compile(r"- ref=(\S+) \| (\w+) \| (.*?) \| ([\d,]+(?:\.\d+)?) (\w+) per (\S+)(.*)")





def cost_choose(req: AIRequest) -> dict[str, Any]:

    out = []

    for lid, body in _blocks(req.user):

        m = re.search(r"Item (\S+) \[(.*?)\] qty [\d,.]+: (.*)", body)

        desc = m.group(3) if m else ""

        rows = []

        for ref, ctype, label, _rate, _cur, _uom, rest in _COST_CAND.findall(body):

            base = _score(desc, label) if ctype != "historical" else 0.55

            bonus = 0.08 if ctype == "quote" else 0.0

            rows.append((ref, ctype, label, min(1.0, base + bonus), rest))

        if not rows:

            continue

        best = max(r[3] for r in rows)

        ranked = []

        taken = False

        for ref, ctype, label, s, rest in sorted(rows, key=lambda r: -r[3]):

            sel = (not taken) and s >= 0.45 and ctype != "historical" and s >= best - 0.001

            taken = taken or sel

            why = "Same size and material as the BOQ item" if s >= 0.75 else "Similar scope; check inclusions" if s >= 0.45 else "Different scope"

            if "flags:" in rest:

                why += f" (flags: {rest.split('flags:')[1].strip()})"

            ranked.append({"ref": ref, "score": round(s, 3), "selected": sel, "rationale": why})

        entry: dict[str, Any] = {"id": lid, "ranked": ranked}

        if not taken:

            entry["overall"] = "No candidate matches the scope closely enough to propose."

        out.append(entry)

    return {"lines": out}





# ------------------------------------------------------------------ markup_advise



def markup_advise(req: AIRequest) -> dict[str, Any]:

    u = req.user

    cur = re.search(r"plant ([\d.]+)%, overhead ([\d.]+)%, volatility ([\d.]+)%, markup ([\d.]+)%", u)

    plant, oh, vol, mk = (float(x) for x in cur.groups()) if cur else (0.0, 0.0, 0.0, 0.0)

    tot = re.search(r"(\d+) lines, (\d+) flagged, (\d+) without a cost yet", u)

    lines, flagged, unresolved = (int(x) for x in tot.groups()) if tot else (0, 0, 0)

    share = flagged / lines if lines else 0.0

    hist = re.findall(r"- ([^:]+): (\d+) bids, (\d+) won \(([\d.]+)%\)", u)

    best = max(hist, key=lambda h: (float(h[3]), int(h[1])), default=None)

    base_mk = mk if mk > 0 else 8.0

    base_oh = oh if oh > 0 else 5.0

    base_vol = vol if vol > 0 else 3.0

    cite = (f"Your history is strongest at margins of {best[0]} ({best[3]}% won of {best[1]} bids)." if best

            else "There is no recorded win/loss history yet, so changes are kept modest.")

    risk = (f"{flagged} of {lines} lines carry risk flags" if flagged else "No lines carry risk flags") + (

        f" and {unresolved} have no cost yet." if unresolved else ".")

    return {

        "options": [

            {"label": "competitive", "markup_pct": max(2.0, round(base_mk - 1.5, 2)), "overhead_pct": base_oh, "volatility_pct": base_vol,

             "rationale": f"Lower markup to win on price. {cite}"},

            {"label": "balanced", "markup_pct": round(base_mk, 2), "overhead_pct": base_oh, "volatility_pct": base_vol,

             "rationale": f"Keep the current settings. {risk}"},

            {"label": "protective", "markup_pct": round(base_mk + 1.5 + (2.0 if share > 0.2 else 0.0), 2), "overhead_pct": base_oh,

             "volatility_pct": round(base_vol + (1.0 if share > 0.1 else 0.5), 2),

             "rationale": f"Protects margin against cost risk. {risk}"},

        ],

        "per_trade": [],

        "overall": f"{cite} {risk} These are suggestions only.",

    }





DEFAULT_HANDLERS: dict[str, Handler] = {

    "intake_classify": intake_classify,

    "boq_pdf_rows": boq_pdf_rows,

    "drawing_annotations": drawing_annotations,

    "boq_interpret": boq_interpret,

    "evidence_rank": evidence_rank,

    "cost_choose": cost_choose,

    "markup_advise": markup_advise,

}

