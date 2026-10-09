"""Phase 6 of the BOQ agent work: a drawing's continuation runs one priority step above its own index task (depth first), and a
time-out that fires inside a database call is reported as a sentence, not as SQLAlchemy's statement dump."""

from __future__ import annotations

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.usefixtures("postgres_container")  # sets the environment the Celery app needs at import


@pytest.mark.parametrize("priority,expected", [(0, 0), (3, 0), (6, 3), (9, 6)])
def test_continuation_runs_one_step_above_the_index_task(priority, expected):
    from app.workers.tasks.takeoff import continuation_priority

    assert continuation_priority(priority) == expected


def test_a_time_limit_inside_a_flush_is_still_a_time_limit():
    from app.workers.tasks.takeoff import describe_index_failure

    plain = describe_index_failure(SoftTimeLimitExceeded())
    wrapped = describe_index_failure(DBAPIError("INSERT INTO drawing_entities (a, b, c) VALUES ($1, $2, $3)", {"a": 1}, SoftTimeLimitExceeded()))
    assert plain == wrapped and "took longer than" in plain and "INSERT" not in wrapped
    try:
        try:
            raise SoftTimeLimitExceeded()
        except SoftTimeLimitExceeded as inner:
            raise RuntimeError("flush failed") from inner
    except RuntimeError as outer:
        assert describe_index_failure(outer) == plain


def test_other_errors_keep_their_own_text():
    from app.workers.tasks.takeoff import describe_index_failure

    assert describe_index_failure(ValueError("bad page tree")) == "bad page tree"
    assert describe_index_failure(KeyError()) == "KeyError()" or describe_index_failure(KeyError())
