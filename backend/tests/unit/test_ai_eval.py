"""The eval harness and smoke command against the MOCK provider (no network, no DB): the harness runs every task
through production code, reports honest scores, writes its reports, and refuses to spend on an unconfigured
external provider."""

from __future__ import annotations

import json

import pytest

from app.ai import eval as ai_eval
from app.ai import smoke
from app.ai.factory import set_gateway_override
from app.core.config import get_settings

ENV = {
    "APP_DATABASE_URL": "postgresql://x/y", "MIGRATOR_DATABASE_URL": "postgresql://x/y", "S3_ENDPOINT": "http://s3",
    "VLLM_API_BASE": "http://vllm.internal:8000/v1",
}


@pytest.fixture
def env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    set_gateway_override(None)
    get_settings.cache_clear()


async def test_mock_baseline_runs_every_task_and_scores_are_recorded(env):
    env.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    report = await ai_eval.run_eval()
    assert report["provider"] == "mock" and report["models"] == ["mock"]
    tasks = {r["task"]: r for r in report["results"]}
    assert set(tasks) == set(ai_eval.EVAL_TASKS)
    assert all(r["cases"] > 0 and r["calls"] > 0 and 0.0 <= r["score"] <= 1.0 for r in tasks.values())
    assert all(r["cost_usd"] == 0.0 for r in tasks.values())   # the mock costs nothing
    # the deterministic fixtures should read the synthetic pack correctly: a regression here means a fixture drifted
    assert tasks["intake_classify"]["score"] >= 0.9
    assert tasks["boq_pdf_rows"]["score"] >= 0.9
    assert tasks["drawing_annotations"]["score"] >= 0.9
    assert tasks["boq_interpret"]["score"] == 1.0
    assert tasks["evidence_rank"]["score"] >= 0.85
    assert tasks["cost_choose"]["score"] >= 0.75
    assert tasks["markup_advise"]["score"] == 1.0


async def test_reports_are_written_as_json_and_markdown(env, tmp_path):
    env.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    report = await ai_eval.run_eval(["boq_interpret", "markup_advise"])
    paths = ai_eval.write_report(report, str(tmp_path))
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert data["provider"] == "mock" and len(data["results"]) == 2
    md = paths[1].read_text(encoding="utf-8")
    assert "| boq_interpret |" in md and "Mean score" in md and "deterministic fixtures" in md


async def test_unconfigured_external_provider_is_skipped_not_spent(env, capsys):
    env.setenv("AI_PROVIDER", "anthropic")
    get_settings.cache_clear()
    report = await ai_eval.run_eval()
    assert report["skipped"] is True and "AI_API_KEY" in report["reason"]


def test_cli_prints_skipped_and_exits_zero_for_an_unconfigured_provider(env, capsys):
    env.setenv("AI_PROVIDER", "anthropic")
    get_settings.cache_clear()
    assert ai_eval.main(["--out", "/tmp/unused"]) == 0
    assert "SKIPPED" in capsys.readouterr().out


async def test_smoke_skips_with_a_clear_message(env, capsys):
    env.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    assert await smoke.run_smoke() == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out and "not an external provider" in out
    env.setenv("AI_PROVIDER", "anthropic")
    get_settings.cache_clear()
    assert await smoke.run_smoke() == 0
    assert "AI_API_KEY" in capsys.readouterr().out


async def test_smoke_prompts_and_schemas_all_render_and_match(env):
    """Every smoke input renders against its real template and the mock answers it schema-validly."""
    env.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    import uuid

    from app.ai.gateway import AIGateway
    from app.ai.store import MemoryStore
    from app.core.context import system_context
    from app.takeoff.prompts import load_schema, render_prompt

    gw = AIGateway(settings=get_settings(), store=MemoryStore(), ctx=system_context(uuid.uuid4()))
    for task, kind, template, schema_file, variables in smoke._CASES:
        system, user = render_prompt(template, **variables)
        res = await gw.run(task=task, kind=kind, system=system, user=user, schema=load_schema(schema_file))
        assert isinstance(res.data, dict), task
