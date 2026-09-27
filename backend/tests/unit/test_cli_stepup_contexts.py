"""Regression test for a real bug found running `make dev-simulate-e2e` and
`make dev-simulate-settlement` against the real dev stack right after
fix/keycloak-step-up merged: app/cli.py builds synthetic RequestContexts
with acr="silver" (to simulate an already-stepped-up bd_director/
procurement_head), bypassing Keycloak entirely -- but has_recent_step_up
(app/security/deps.py) also requires a recent auth_time, which
RequestContext defaults to None. Every acr="silver" simulation context
that reaches a step-up-guarded call (decide_settlement, dispatch_rfq) was
silently broken (StepUpRequiredError) until auth_time=int(time.time()) was
added alongside each one.

This is a static check on app/cli.py's own source rather than a call into
its simulate_* functions, which need a real Postgres/Celery/SMTP stack and
are already exercised that way by hand (`make dev-simulate-e2e`) -- this
test instead guards the *pattern* cheaply, in every pytest run, so a future
simulate_* addition can't reintroduce the same mistake.
"""

from __future__ import annotations

import ast
import inspect

import app.cli as cli_module


def _acr_silver_calls_missing_auth_time() -> list[int]:
    """Line numbers of every RequestContext(...) call in app/cli.py that
    passes acr="silver" as a keyword but has no auth_time keyword at all."""
    source = inspect.getsource(cli_module)
    tree = ast.parse(source)
    offending: list[int] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "RequestContext"):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        acr_value = kwargs.get("acr")
        is_silver = (
            isinstance(acr_value, ast.Constant) and isinstance(acr_value.value, str) and acr_value.value == "silver"
        )
        if is_silver and "auth_time" not in kwargs:
            offending.append(node.lineno)

    return offending


def test_every_simulated_silver_context_carries_auth_time():
    offending = _acr_silver_calls_missing_auth_time()
    assert offending == [], (
        f"app/cli.py line(s) {offending} construct RequestContext(acr='silver', ...) with no auth_time -- "
        "has_recent_step_up (app/security/deps.py) fails closed on auth_time=None, so any decide_settlement/"
        "dispatch_rfq call using one of these contexts always raises StepUpRequiredError. "
        "Add auth_time=int(time.time()) alongside acr='silver'."
    )
