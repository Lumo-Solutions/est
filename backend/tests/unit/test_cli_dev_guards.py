"""The dev-only cleanup commands refuse outside dev/test, and the project delete refuses a real tender code."""

from __future__ import annotations

import asyncio

import pytest

from app import cli
from app.core.config import get_settings


ENV = {
    "APP_DATABASE_URL": "postgresql://x/y", "MIGRATOR_DATABASE_URL": "postgresql://x/y", "S3_ENDPOINT": "http://s3",
    "VLLM_API_BASE": "http://vllm.internal:8000/v1",
}


@pytest.fixture
def app_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    def _set(value: str):
        monkeypatch.setenv("APP_ENV", value)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


def test_withdraw_stale_approvals_refuses_in_production(app_env):
    app_env("production")
    with pytest.raises(SystemExit, match="Refusing"):
        asyncio.run(cli.withdraw_stale_approvals(apply=False))


def test_delete_demo_project_refuses_in_production(app_env):
    app_env("production")
    with pytest.raises(SystemExit, match="Refusing"):
        asyncio.run(cli.delete_demo_project("P6-IDX-A"))


@pytest.mark.parametrize("code", ["102", "103", "ACME-TOWER", "TENDER-2026"])
def test_delete_demo_project_refuses_a_code_that_is_not_e2e_or_demo(app_env, code):
    app_env("dev")
    with pytest.raises(SystemExit, match="not an e2e/demo project code"):
        asyncio.run(cli.delete_demo_project(code))
