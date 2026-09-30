"""Tiny JSON-schema helpers (no jsonschema dependency): a minimal valid
instance for the mock provider, and a structural check used on every model
answer before a caller sees it. Covers the subset our schemas use: type,
enum, required, properties, additionalProperties, items."""

from __future__ import annotations

from typing import Any


def _types(schema: dict[str, Any]) -> list[str]:
    t = schema.get("type", "object" if "properties" in schema else "string")
    return list(t) if isinstance(t, list) else [t]


def minimal_instance(schema: dict[str, Any]) -> Any:
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    types = _types(schema)
    if "null" in types and len(types) > 1:
        types = [t for t in types if t != "null"]
    t = types[0]
    if t == "object":
        props = schema.get("properties", {})
        return {k: minimal_instance(props[k]) for k in schema.get("required", []) if k in props}
    if t == "array":
        return []
    if t == "string":
        return ""
    if t in ("number", "integer"):
        return schema.get("minimum", 0)
    if t == "boolean":
        return False
    return None


def _type_ok(value: Any, types: list[str]) -> bool:
    for t in types:
        if t == "null" and value is None:
            return True
        if t == "string" and isinstance(value, str):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "array" and isinstance(value, list):
            return True
        if t == "object" and isinstance(value, dict):
            return True
    return False


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Returns human-readable problems (empty list = valid)."""
    problems: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} not in enum")
        return problems
    types = _types(schema)
    if not _type_ok(value, types):
        problems.append(f"{path}: expected {'/'.join(types)}, got {type(value).__name__}")
        return problems
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                problems.append(f"{path}.{req}: required")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    problems.append(f"{path}.{k}: unexpected key")
        for k, sub in props.items():
            if k in value:
                problems.extend(validate(value[k], sub, f"{path}.{k}"))
    elif isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            problems.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return problems


def strip_unknown(value: Any, schema: dict[str, Any]) -> Any:
    """Drops keys the schema does not declare (AI output has no back door)."""
    if isinstance(value, dict) and "properties" in schema:
        props = schema["properties"]
        return {k: strip_unknown(v, props[k]) for k, v in value.items() if k in props}
    if isinstance(value, list) and "items" in schema:
        return [strip_unknown(v, schema["items"]) for v in value]
    return value
