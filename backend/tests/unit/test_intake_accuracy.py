"""Classification accuracy on the synthetic tender pack: the rules alone (the fallback) and AI-first with the
mock provider (docs/tender-intake-plan.md section 15, AI-first intake). The real-model accuracy run stays on the GPU
checklist. Run with `-s` to print the table."""

from __future__ import annotations

from app.ai.mock_fixtures import intake_classify
from app.ai.provider import AIRequest, ImageInput
from app.core.config import Settings
from app.intake.classifier import ai_document_text, combine, parse_model_output, rule_hints, text_is_sufficient
from app.intake.extract import extract_content
from app.intake.rules import classify_rules, normalise_folder
from app.intake.safety import check_file, extension_of
from app.takeoff.prompts import render_prompt
from tests.fixtures.tender_pack import build_pack, build_zip_member_files

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)


def _classifiable():
    files = [f for f in build_pack() if f.expected_status in ("classifiable", "duplicate")]
    return files + [f for f in build_zip_member_files() if f.expected_status == "classifiable"]


def mock_answer(filename: str, content, rules, folder: str = "") -> dict:
    """What the pipeline would send, answered by the mock provider."""
    system, user = render_prompt(
        "document_classification.j2",
        filename=filename,
        folder_path=folder,
        file_type=content.ext,
        page_count=content.pages,
        document_text=ai_document_text(content),
        title_block_text=content.title_block_text if content.ext != "dxf" else "",
        has_image=not text_is_sufficient(content),
        hints=rule_hints(rules),
    )
    images = [] if text_is_sufficient(content) else [ImageInput(b"png")]
    return intake_classify(AIRequest(task="intake_classify", kind="classify", model="mock", system=system, user=user, schema={}, images=images))


def evaluate(with_ai: bool) -> list[dict]:
    settings = Settings(**_REQUIRED)  # type: ignore[arg-type]
    rows = []
    for f in _classifiable():
        safety = check_file(filename=f.name, data=f.data, settings=settings)
        assert safety.accepted, f"{f.name}: {safety.reason}"
        content = extract_content(filename=f.name, ext=extension_of(f.name), sniffed=safety.sniffed, data=f.data)
        rules = classify_rules(content, f.name, folder=normalise_folder(f.name))
        model = parse_model_output(mock_answer(f.name, content, rules)) if with_ai else None
        proposal = combine(rules, model, settings=settings)
        rows.append(
            {
                "file": f.name,
                "expected": f.expected_class,
                "rules": rules.doc_class,
                "rules_conf": rules.confidence,
                "got": proposal.doc_class,
                "conf": proposal.confidence,
                "source": proposal.source,
                "metadata": proposal.metadata,
                "expected_metadata": f.expected_metadata,
            }
        )
    return rows


def _print(rows: list[dict], title: str) -> None:
    correct = sum(r["got"] == r["expected"] for r in rows)
    print(f"\n== {title}: {correct}/{len(rows)} = {correct / len(rows):.1%}")
    for r in rows:
        mark = "ok " if r["got"] == r["expected"] else "BAD"
        print(f"  {mark} {r['file']:<40} expected={r['expected']:<20} got={r['got']:<20} conf={r['conf']:.2f} by={r['source']}")


def test_rules_only_accuracy_is_the_fallback_baseline():
    rows = evaluate(with_ai=False)
    _print(rows, "rules only (fallback)")
    assert sum(r["got"] == r["expected"] for r in rows) / len(rows) >= 0.75
    assert {r["source"] for r in rows} == {"rules"}
    # Anything the rules are very sure about must be right.
    confident = [r for r in rows if r["rules_conf"] >= 0.85]
    assert confident and all(r["got"] == r["expected"] for r in confident), [r for r in confident if r["got"] != r["expected"]]


def test_ai_first_accuracy_with_the_mock_provider():
    rows = evaluate(with_ai=True)
    _print(rows, "AI first (mock provider)")
    correct = sum(r["got"] == r["expected"] for r in rows) / len(rows)
    rules_only = evaluate(with_ai=False)
    assert correct >= sum(r["got"] == r["expected"] for r in rules_only) / len(rules_only)
    assert correct >= 0.9
    assert {r["source"] for r in rows} == {"model"}
    # Every answer the AI is confident about (what auto-accept would act on) is right.
    confident = [r for r in rows if r["conf"] >= 0.85]
    assert confident and all(r["got"] == r["expected"] for r in confident), [r for r in confident if r["got"] != r["expected"]]


def test_extracted_metadata_matches_ground_truth_where_the_pack_defines_it():
    rows = evaluate(with_ai=True)
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
