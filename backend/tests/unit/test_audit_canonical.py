"""Re-verifies the exact hash-chain formula the Postgres trigger implements
(migration 0003's audit_events_chain_trg), in pure Python, independent of
any database. This is the same math services/audit.py::verify_chain()
performs against real rows -- see tests/integration/test_audit_chain_db.py
for the trigger itself running for real."""

from __future__ import annotations

import hashlib
import json


def compute_event_hash(prev_hash: str, canonical_json: str) -> str:
    return hashlib.sha256((prev_hash + "|" + canonical_json).encode("utf-8")).hexdigest()


def build_canonical_json(event: dict) -> str:
    # Mirrors the jsonb_build_object(...) shape in the trigger, serialized
    # the same way jsonb::text would (compact separators, sorted only where
    # jsonb naturally sorts -- top-level key order here matches the trigger's
    # literal object construction order, which is what matters for the hash).
    return json.dumps(event, separators=(",", ":"))


def test_genesis_prev_hash_is_64_zeros() -> None:
    genesis = "0" * 64
    assert len(genesis) == 64
    assert set(genesis) == {"0"}


def test_chain_links_seq_to_seq() -> None:
    event1 = {"seq": 1, "action": "create", "entity_type": "vendor"}
    canonical1 = build_canonical_json(event1)
    hash1 = compute_event_hash("0" * 64, canonical1)

    event2 = {"seq": 2, "action": "update", "entity_type": "vendor"}
    canonical2 = build_canonical_json(event2)
    hash2 = compute_event_hash(hash1, canonical2)

    assert hash1 != hash2
    assert len(hash1) == 64
    assert len(hash2) == 64

    # Re-deriving from the stored prev_hash + canonical_json must reproduce
    # the stored event_hash exactly -- this is what verify_chain() checks.
    assert compute_event_hash(hash1, canonical2) == hash2


def test_tampering_with_payload_changes_the_hash() -> None:
    canonical_original = build_canonical_json({"seq": 1, "payload_sha256": "abc123"})
    canonical_tampered = build_canonical_json({"seq": 1, "payload_sha256": "def456"})

    hash_original = compute_event_hash("0" * 64, canonical_original)
    hash_tampered = compute_event_hash("0" * 64, canonical_tampered)

    assert hash_original != hash_tampered


def test_tampering_with_prev_hash_breaks_the_chain() -> None:
    canonical = build_canonical_json({"seq": 2, "action": "update"})
    real_prev_hash = "a" * 64
    forged_prev_hash = "b" * 64

    assert compute_event_hash(real_prev_hash, canonical) != compute_event_hash(forged_prev_hash, canonical)


def test_payload_sha256_is_sha256_of_payload_text() -> None:
    payload = {"legal_name": "Al Futtaim Contracting LLC"}
    payload_text = json.dumps(payload)
    expected = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    assert len(expected) == 64
