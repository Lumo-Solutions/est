from __future__ import annotations

import pytest

from app.services.dedupe import (
    VendorSignature,
    classify,
    contact_fingerprint,
    email_domain,
    normalize_address,
    normalize_license,
    normalize_name,
    phone_last9,
    score_pair,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Al Futtaim Contracting LLC", "AL FUTTAIM"),
        ("AL-FUTTAIM CONT. L.L.C.", "AL FUTTAIM"),
        ("Al Futtaim Trading & General Contracting Co.", "AL FUTTAIM"),
        ("  ACME   Est.  ", "ACME"),
    ],
)
def test_normalize_name_strips_suffixes_and_punctuation(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_normalize_license_keeps_only_alnum() -> None:
    assert normalize_license("DXB-12345/A") == "DXB12345A"
    assert normalize_license(None) is None
    assert normalize_license("") is None


def test_email_domain_extraction() -> None:
    assert email_domain("Contact@Example.COM") == "example.com"
    assert email_domain(None) is None
    assert email_domain("not-an-email") is None


def test_phone_last9() -> None:
    # digits: 971 4 123 4567 -> "97141234567" (11 digits); last 9 drops the leading "97"
    assert phone_last9("+971 4 123 4567") == "141234567"
    assert phone_last9("123") is None


def test_contact_fingerprint_is_order_independent() -> None:
    fp1 = contact_fingerprint("example.com", "412345678", "DXB123")
    fp2 = contact_fingerprint("example.com", "412345678", "DXB123")
    assert fp1 == fp2
    assert len(fp1) == 64


def test_score_pair_exact_license_short_circuits_high() -> None:
    a = VendorSignature("AL FUTTAIM", "DXB12345", "SHEIKH ZAYED RD", "example.com", "412345678", "TRN1")
    b = VendorSignature("FUTTAIM GROUP", "DXB12345", "DIFFERENT ADDRESS", "other.com", "509999999", "TRN2")
    result = score_pair(a, b)
    assert result.score >= 0.95
    assert classify(result.score) == "auto_candidate"


def test_score_pair_identical_signals_scores_high() -> None:
    a = VendorSignature("AL FUTTAIM CONTRACTING", "DXB12345", "SHEIKH ZAYED RD DUBAI", "alfuttaim.com", "412345678", "TRN1")
    b = VendorSignature("AL FUTTAIM CONTRACTING", "DXB12345", "SHEIKH ZAYED RD DUBAI", "alfuttaim.com", "412345678", "TRN1")
    result = score_pair(a, b)
    assert result.score == 1.0
    assert classify(result.score) == "auto_candidate"


def test_score_pair_unrelated_vendors_scores_low() -> None:
    a = VendorSignature("ACME EARTHWORKS", "DXB11111", "JEBEL ALI", "acme.com", "412340000", "TRNA")
    b = VendorSignature("ZENITH MEP SOLUTIONS", "SHJ99999", "AL QUOZ", "zenith.com", "509990000", "TRNB")
    result = score_pair(a, b)
    assert result.score < 0.5
    assert classify(result.score) == "ignore"


def test_score_pair_similar_name_only_is_a_warning_not_auto() -> None:
    a = VendorSignature("GULF CONSTRUCTION SERVICES", None, None, None, None, None)
    b = VendorSignature("GULF CONSTRUCTION SERVICE", None, None, None, None, None)
    result = score_pair(a, b)
    assert classify(result.score) in ("warning", "ignore")
    assert classify(result.score) != "auto_candidate"


def test_normalize_address_transliterates_and_uppercases() -> None:
    assert normalize_address("Ütopia Road, Blvd. 4") == "UTOPIA ROAD BLVD 4"
    assert normalize_address(None) is None
