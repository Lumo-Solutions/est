"""Classification accuracy on the synthetic tender pack, rules only and rules
plus the mock model (docs/tender-intake-plan.md section 15). The real-model
accuracy run stays on the GPU checklist. Run with `-s` to print the table."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core.config import Settings
from app.intake.classifier import combine, parse_model_output
from app.intake.extract import extract_content
from app.intake.rules import classify_rules, needs_model
from app.intake.safety import check_file, extension_of
from app.takeoff.prompts import render_prompt
from tests.fixtures.tender_pack import build_pack, build_zip_member_files

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)
_MOCK = Path(__file__).resolve().parents[3] / "ai-service" / "mock-vllm" / "classification.py"


def _mock_classify():
    spec = importlib.util.spec_from_file_location("mock_classification", _MOCK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.classify_document


def _classifiable():
    files = [f for f in build_pack() if f.expected_status in ("classifiable", "duplicate")]
    return files + [f for f in build_zip_member_files() if f.expected_status == "classifiable"]


def evaluate(with_mock: bool) -> list[dict]:
    settings = Settings(**_REQUIRED)  # type: ignore[arg-type]
    mock = _mock_classify()
    rows = []
    for f in _classifiable():
        safety = check_file(filename=f.name, data=f.data, settings=settings)
        assert safety.accepted, f"{f.name}: {safety.reason}"
        content = extract_content(filename=f.name, ext=extension_of(f.name), sniffed=safety.sniffed, data=f.data)
        rules = classify_rules(content, f.name)
        wanted = needs_model(rules, settings.intake_rules_confident)
        model = None
        if with_mock and wanted:
            _, user = render_prompt(
                "document_classification.j2",
                filename=f.name,
                document_text=content.text,
                title_block_text=content.title_block_text,
                has_image=content.needs_image,
                candidates=sorted(rules.candidates),
            )
            model = parse_model_output(mock(user, content.needs_image))
        proposal = combine(rules, model, model_wanted=wanted and with_mock, settings=settings)
        rows.append(
            {
                "file": f.name,
                "expected": f.expected_class,
                "rules": rules.doc_class,
                "rules_conf": rules.confidence,
                "model_called": model is not None,
                "got": proposal.doc_class if with_mock else rules.doc_class,
                "conf": proposal.confidence if with_mock else rules.confidence,
                "metadata": proposal.metadata if with_mock else rules.metadata,
                "expected_metadata": f.expected_metadata,
            }
        )
    return rows


def _print(rows: list[dict], title: str) -> None:
    correct = sum(r["got"] == r["expected"] for r in rows)
    print(f"\n== {title}: {correct}/{len(rows)} = {correct / len(rows):.1%}")
    for r in rows:
        mark = "ok " if r["got"] == r["expected"] else "BAD"
        print(f"  {mark} {r['file']:<40} expected={r['expected']:<20} got={r['got']:<20} conf={r['conf']:.2f} model={r['model_called']}")


def test_rules_only_accuracy():
    rows = evaluate(with_mock=False)
    _print(rows, "rules only")
    accuracy = sum(r["got"] == r["expected"] for r in rows) / len(rows)
    assert accuracy >= 0.75
    # Anything stage 1 is confident enough to skip the model on must be right.
    confident = [r for r in rows if r["rules_conf"] >= 0.85]
    assert confident, "expected some confident rule answers"
    assert all(r["got"] == r["expected"] for r in confident), [r for r in confident if r["got"] != r["expected"]]


def test_rules_plus_mock_model_accuracy():
    rows = evaluate(with_mock=True)
    _print(rows, "rules + mock model")
    correct = sum(r["got"] == r["expected"] for r in rows) / len(rows)
    rules_only = evaluate(with_mock=False)
    assert correct >= sum(r["got"] == r["expected"] for r in rules_only) / len(rules_only)
    assert correct >= 0.9


def test_extracted_metadata_matches_ground_truth_where_the_pack_defines_it():
    rows = evaluate(with_mock=True)
    wrong = []
    for r in rows:
        for key, want in r["expected_metadata"].items():
            got = r["metadata"].get(key)
            if key == "supersedes":
                ok = all(w in (got or []) for w in want)
            else:
                ok = got == want
            if not ok:
                wrong.append((r["file"], key, want, got))
    assert not wrong, wrong


@pytest.mark.parametrize("name", ["C-101 Rev A.dxf", "S-201 Rev B.pdf", "A-201 Rev A.dxf"])
def test_drawing_sub_types(name):
    settings = Settings(**_REQUIRED)  # type: ignore[arg-type]
    f = next(x for x in build_pack() if x.name == name)
    content = extract_content(filename=f.name, ext=extension_of(f.name), sniffed=check_file(filename=f.name, data=f.data, settings=settings).sniffed, data=f.data)
    out = classify_rules(content, f.name)
    assert out.doc_class == "drawing"
    assert out.sub_type == f.expected_sub_type
