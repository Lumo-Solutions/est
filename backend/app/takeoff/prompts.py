from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jinja2 import Template

# ai-service/ is a sibling of backend/ at the repo root (see
# ai-service/README.md and MASTER_SRS.MD's monorepo layout).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROMPTS_DIR = _REPO_ROOT / "ai-service" / "prompts"
_SCHEMAS_DIR = _REPO_ROOT / "ai-service" / "schemas"

_SYSTEM_MARKER = "{# system #}"
_USER_MARKER = "{# user #}"


@lru_cache
def _load_split_template(name: str) -> tuple[Template, Template]:
    """ai-service/prompts/*.j2 files mark their system/user sections with
    Jinja *comments* (`{# system #}` / `{# user #}`) rather than a template
    tag, so they render standalone in any Jinja-based tool (including the
    prompt-contract tests in ai-service/tests/). Comments are stripped by
    Jinja's own renderer, so we split the RAW file text on the marker
    strings first and compile each half as its own template."""
    raw = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    if _SYSTEM_MARKER not in raw or _USER_MARKER not in raw:
        raise ValueError(f"{name} is missing the {{# system #}}/{{# user #}} section markers")
    _, rest = raw.split(_SYSTEM_MARKER, 1)
    system_part, user_part = rest.split(_USER_MARKER, 1)
    return Template(system_part.strip()), Template(user_part.strip())


@lru_cache
def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def render_prompt(template_name: str, **context: object) -> tuple[str, str]:
    system_tpl, user_tpl = _load_split_template(template_name)
    return system_tpl.render(**context), user_tpl.render(**context)


def load_schema(schema_name: str) -> dict:
    return _load_schema(schema_name)
