"""Verification engine: classes, quantities, methods, confidence, missing-in-BOQ. Pure, no DB, no model."""

from __future__ import annotations

from app.verification.engine import (
    Candidate,
    Evidence,
    LineInput,
    Method,
    VClass,
    compute_line,
    find_missing_in_boq,
    generate_candidates,
    interpret_by_rules,
    not_verifiable_reason,
    summarize,
)


def line(desc="Supply and lay 300mm uPVC SN8 sewer pipe", uom="m", qty=245.0, **kw):
    return LineInput(id=kw.pop("id", "L1"), item_no=kw.pop("item_no", "2.1"), description=desc, uom=uom, quantity=qty, **kw)


def meas(ref, value, unit="m", label="pipe_network_topology pipe_length_m layer=SEWER-300 trade=drainage", **kw):
    return Evidence(ref=f"m:{ref}", kind="measurement", value=value, unit=unit, label=label, **kw)


def ann(ref, value, unit="m", ann_kind="length", text="L=245.0m", **kw):
    return Evidence(ref=f"a:{ref}", kind="annotation", value=value, unit=unit, label=text, ann_kind=ann_kind, **kw)


def run(l, evs, cands=None, **kw):
    ev = {e.ref: e for e in evs}
    interp = interpret_by_rules(l)
    cands = cands if cands is not None else generate_candidates(l, interp, evs)
    return compute_line(l, interp, cands, ev, **kw)


# --------------------------------------------------------------- verifiability

def test_not_verifiable_reasons():
    assert not_verifiable_reason(line("Provisional sum for utilities diversion", "item", 1)) is not None
    assert not_verifiable_reason(line("Preliminaries and general requirements", "ls", 1)) is not None
    assert not_verifiable_reason(line("Mobilisation and demobilisation", "ls", 1)) is not None
    assert not_verifiable_reason(line("Supply pipe", None, 10)) == "No unit of measure on the BOQ line"
    assert "no quantity" in not_verifiable_reason(line("Pipe", "m", None)).lower()
    assert not_verifiable_reason(line("Section heading", None, None, is_heading=True)).startswith("Section heading")
    assert not_verifiable_reason(line("Excavate trench", "m3", 100)) is None
    assert not_verifiable_reason(line("Something in furlongs", "furlong", 3)) is not None


def test_not_verifiable_line_without_evidence_is_classed_not_verifiable():
    r = run(line("Provisional sum for testing", "item", 1), [])
    assert r.vclass == VClass.NOT_VERIFIABLE.value and r.method == Method.NONE.value


# --------------------------------------------------------------- classes

def test_measured_match_within_tolerance():
    r = run(line(), [meas("1", 246.0)])
    assert r.vclass == VClass.MATCH.value and r.method == "measured" and r.drawing_quantity == 246.0
    assert abs(r.delta_pct - 0.408) < 0.01 and r.mapped_by == "rules"


def test_measured_variance_outside_tolerance_with_delta():
    r = run(line(), [meas("1", 200.0)])
    assert r.vclass == VClass.VARIANCE.value and r.delta == -45.0 and round(r.delta_pct, 2) == -18.37


def test_missing_in_drawings_when_nothing_compatible():
    r = run(line("Supply and lay 300mm uPVC sewer pipe", "m", 100), [meas("1", 50, unit="m3")])
    assert r.vclass == VClass.MISSING_IN_DRAWINGS.value and r.drawing_quantity is None


def test_units_are_converted_into_the_boq_unit():
    r = run(line(uom="m", qty=245.0), [meas("1", 245000.0, unit="mm")])
    assert r.vclass == VClass.MATCH.value and r.drawing_quantity == 245.0


def test_tolerance_is_respected_per_line():
    assert run(line(qty=100.0, tolerance_pct=10.0), [meas("1", 108.0)]).vclass == VClass.MATCH.value
    assert run(line(qty=100.0, tolerance_pct=2.0), [meas("1", 108.0)]).vclass == VClass.VARIANCE.value


def test_multiple_measurements_are_summed():
    r = run(line(qty=300.0), [meas("1", 100.0), meas("2", 200.0)])
    assert r.drawing_quantity == 300.0 and r.vclass == VClass.MATCH.value and len(r.evidence) == 2


# --------------------------------------------------------------- annotated vs measured, never a guess

def test_annotated_used_only_when_no_measurement():
    a = ann("1", 245.0, text="L=245.0m D300 uPVC")
    r = run(line(), [a])
    assert r.method == "annotated" and r.vclass == VClass.MATCH.value
    r2 = run(line(), [a, meas("1", 250.0)])
    assert r2.method == "measured" and r2.drawing_quantity == 250.0  # measurement wins over annotation


def test_measurement_survives_the_attach_cap_when_many_annotations_rank_first():
    anns = [ann(str(i), 60.0, text="60.0m D300 uPVC") for i in range(6)]
    m = meas("g", 246.0)
    cands = [Candidate(ref=a.ref, score=1.0, source="ai", selected=True) for a in anns] + [Candidate(ref=m.ref, score=0.8, source="ai", selected=True)]
    r = run(line(), [*anns, m], cands=cands)
    assert r.method == "measured" and r.drawing_quantity == 246.0


def test_annotated_confidence_is_lower_and_multiple_annotations_flagged():
    single = run(line(), [ann("1", 245.0, text="L=245.0m D300 uPVC")])
    assert single.confidence <= 0.85
    many = run(line(qty=490.0), [ann("1", 245.0, text="L=245.0m D300 uPVC"), ann("2", 245.0, text="L=245.0m D300 uPVC")])
    assert "multiple_annotations" in many.flags and many.confidence < single.confidence
    assert many.drawing_quantity == 490.0


def test_no_evidence_means_no_quantity_never_an_estimate():
    r = run(line(), [])
    assert r.vclass == VClass.MISSING_IN_DRAWINGS.value and r.drawing_quantity is None and r.method == "none"


# --------------------------------------------------------------- user decisions win

def test_exclude_removes_a_candidate_and_include_adds_one():
    good, bad = meas("g", 245.0), meas("b", 40.0, label="alignment_length_m layer=ROAD-CL")
    cands = [Candidate("m:g", 0.9, "ok", "ai", True), Candidate("m:b", 0.8, "wrong", "ai", True)]
    both = run(line(qty=245.0), [good, bad], cands)
    assert both.drawing_quantity == 285.0 and both.vclass == VClass.VARIANCE.value
    excl = run(line(qty=245.0), [good, bad], cands, exclude={"m:b"})
    assert excl.drawing_quantity == 245.0 and excl.vclass == VClass.MATCH.value
    only_inc = run(line(qty=245.0), [good, bad], [], include={"m:g"})
    assert only_inc.mapped_by == "user" and only_inc.confidence >= 0.99 and only_inc.vclass == VClass.MATCH.value


def test_ai_unselected_or_low_score_candidates_are_not_attached():
    e = meas("1", 245.0)
    assert run(line(), [e], [Candidate("m:1", 0.9, "", "ai", False)]).vclass == VClass.MISSING_IN_DRAWINGS.value
    assert run(line(), [e], [Candidate("m:1", 0.3, "", "ai", True)]).vclass == VClass.MISSING_IN_DRAWINGS.value


def test_recompute_is_deterministic():
    e = meas("1", 300.0)
    a, b = run(line(), [e]), run(line(), [e])
    assert (a.vclass, a.delta, a.confidence) == (b.vclass, b.delta, b.confidence)


# --------------------------------------------------------------- candidates & interpretation

def test_interpret_by_rules_reads_size_material_and_work():
    i = interpret_by_rules(line("Supply, lay and joint 300mm diameter uPVC SN8 sewer pipe", "m", 10))
    assert i.size_mm == 300 and i.material == "upvc" and i.work_type in ("pipe", "drainage")


def test_candidates_are_unit_compatible_and_rank_by_relevance():
    l = line("Supply and lay 300mm uPVC sewer pipe", "m", 100)
    evs = [
        meas("area", 900.0, unit="m2", label="corridor_area layer=ROAD"),
        meas("road", 500.0, label="alignment_length_m layer=ROAD-CL trade=roads"),
        meas("pipe", 245.0, label="pipe_network pipe_length_m layer=SEWER-300 trade=drainage", trade_name="drainage"),
    ]
    cands = generate_candidates(l, interpret_by_rules(l), evs)
    assert cands[0].ref == "m:pipe" and "m:area" not in [c.ref for c in cands]


def test_size_in_label_boosts_score():
    l = line("Supply 300mm uPVC pipe", "m", 100)
    interp = interpret_by_rules(l)
    c300 = generate_candidates(l, interp, [meas("a", 1, label="pipe layer=SEWER-300")])[0].score
    c150 = generate_candidates(l, interp, [meas("b", 1, label="pipe layer=SEWER-150")])[0].score
    assert c300 > c150


# --------------------------------------------------------------- missing in BOQ

def test_unattached_measurements_are_missing_in_boq_and_sorted_by_size():
    evs = [meas("used", 245.0), meas("big", 900.0, label="alignment layer=ROAD-CL"), meas("small", 12.0, label="x")]
    out = find_missing_in_boq(evs, {"m:used"})
    assert [r.evidence[0].ref for r in out] == ["m:big", "m:small"] and all(r.vclass == "missing_in_boq" for r in out)


def test_annotation_restating_an_attached_measurement_is_not_extra_scope():
    evs = [meas("used", 245.0), ann("dup", 246.0), ann("other", 80.0), ann("lvl", 12.3, unit="m", ann_kind="level")]
    out = find_missing_in_boq(evs, {"m:used"})
    assert [r.evidence[0].ref for r in out] == ["a:other"]  # duplicate within 5% dropped; a level is not a quantity


def test_low_confidence_evidence_is_not_reported_as_missing_scope():
    assert find_missing_in_boq([meas("x", 100.0, confidence=0.2)], set()) == []


# --------------------------------------------------------------- summary

def test_summary_counts_and_top_risks():
    r1 = run(line(id="A", qty=245.0), [meas("1", 245.0)])
    r2 = run(line(id="B", qty=100.0), [meas("2", 150.0)])
    r3 = run(line(id="C", qty=100.0), [])
    r4 = run(line("Provisional sum", "item", 1, id="D"), [])
    s = summarize([r1, r2, r3, r4], {"A": "drainage", "B": "drainage", "C": "roads", "D": None})
    assert s["counts"]["match"] == 1 and s["counts"]["variance"] == 1 and s["counts"]["missing_in_drawings"] == 1
    assert s["counts"]["not_verifiable"] == 1 and s["verifiable"] == 3
    assert s["top_risks"][0]["class"] == "missing_in_drawings"
    assert {t["trade"] for t in s["by_trade"]} >= {"drainage", "roads"}


def test_annotation_restating_one_run_of_an_attached_group_is_not_extra_scope():
    group = Evidence(ref="g:x", kind="measurement", value=246.0, unit="m", label="pipe runs", members=("a", "b", "c"),
                     member_values=(100.0, 90.0, 56.0))
    evs = [group, ann("run1", 100.0), ann("run3", 56.0), ann("other", 33.0)]
    out = find_missing_in_boq(evs, {"g:x"})
    assert [r.evidence[0].ref for r in out] == ["a:other"]
