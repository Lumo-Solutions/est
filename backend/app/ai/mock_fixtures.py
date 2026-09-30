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



def intake_classify(req: AIRequest) -> dict[str, Any]:

    text = req.user.lower()

    fname = re.search(r"filename: (.*)", req.user)

    name = (fname.group(1) if fname else "").lower()

    rules = [

        ("addendum", ("addendum",)),

        ("boq", ("bill of quantities", "schedule of quantities", "boq")),

        ("correspondence", ("dear sirs", "dear madam", "yours faithfully", "yours sincerely", "further to our")),

        ("specification", ("specification", "part 1 - general", "section 0")),

        ("contract", ("conditions of contract", "fidic")),

        ("tender_instructions", ("instructions to tenderers", "instructions to bidders")),

        ("tender_forms", ("form of tender", "bid bond")),

        ("clarification", ("request for information", "clarification")),

        ("programme", ("programme", "gantt")),

        ("site_investigation", ("geotechnical", "borehole")),

        ("drawing", ("drawing no", "scale", "sheet")),

    ]

    cls, quote, conf = "other", "", 0.5

    for candidate, needles in rules:

        hit = next((n for n in needles if n in text or n in name), None)

        if hit:

            cls, quote, conf = candidate, hit, 0.8

            break

    sub = None

    if cls == "drawing":

        sub = "landscape" if "landscape" in text else "civil_infra" if any(w in text for w in ("road", "sewer", "drain", "civil")) else None

    out: dict[str, Any] = {"doc_class": cls, "confidence": conf, "evidence_quote": quote}

    if sub:

        out["sub_type"] = sub

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

