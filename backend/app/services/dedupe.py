"""Pure, DB-free vendor duplicate-detection scoring (unit-testable; see
backend/tests/unit/test_dedupe_scoring.py). SQL-side blocking (trigram /
exact-key candidate selection) lives in services/vendors.py -- this module
only normalizes strings and scores a candidate pair once fetched."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from rapidfuzz import fuzz
from unidecode import unidecode

_LEGAL_SUFFIXES = [
    "FZ LLC", "LLC", "FZE", "FZCO", "EST", "ESTABLISHMENT",
    "CO", "COMPANY", "CONTRACTING", "CONT", "TRADING", "GENERAL", "AND", "THE",
]
_SUFFIX_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\b", re.IGNORECASE
)
# Collapses dotted-abbreviation suffixes ("L.L.C.", "F.Z.E.") to their
# undotted form BEFORE generic punctuation stripping runs -- otherwise
# "L.L.C." becomes three isolated single-letter tokens ("L L C") that
# _SUFFIX_PATTERN's whole-word "LLC" entry can never match.
_DOTTED_ABBREV = re.compile(r"\b(?:[A-Z]\.){2,}")
_NON_ALNUM_SPACE = re.compile(r"[^A-Z0-9 ]")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_WHITESPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Upper-cases, transliterates, strips legal-entity suffixes and
    punctuation, collapses whitespace. "Al Futtaim Cont. LLC" and
    "AL-FUTTAIM CONTRACTING L.L.C." both normalize to "AL FUTTAIM"."""
    text = unidecode(name or "").upper()
    text = _DOTTED_ABBREV.sub(lambda m: m.group(0).replace(".", ""), text)
    text = _NON_ALNUM_SPACE.sub(" ", text)
    text = _SUFFIX_PATTERN.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def normalize_license(license_no: str | None) -> str | None:
    if not license_no:
        return None
    cleaned = _NON_ALNUM.sub("", license_no.upper())
    return cleaned or None


def normalize_address(address: str | None) -> str | None:
    if not address:
        return None
    text = unidecode(address).upper()
    text = _NON_ALNUM_SPACE.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].lower().strip() or None


def phone_last9(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits[-9:] if len(digits) >= 9 else None


def contact_fingerprint(email_dom: str | None, phone9: str | None, license_norm: str | None) -> str:
    parts = sorted(p for p in (email_dom, phone9, license_norm) if p)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VendorSignature:
    """Normalized fields for one vendor, used as input to score_pair()."""

    normalized_name: str
    normalized_license: str | None
    normalized_address: str | None
    email_domain: str | None
    phone_last9: str | None
    trn_vat_no: str | None


WEIGHTS = {
    "license": 0.45,
    "name": 0.25,
    "address": 0.08,
    "email_domain": 0.10,
    "phone": 0.10,
    "trn": 0.02,
}

AUTO_CANDIDATE_THRESHOLD = 0.92
WARNING_THRESHOLD = 0.75


@dataclass(frozen=True, slots=True)
class DedupeScore:
    score: float
    signals: dict[str, float]


def score_pair(a: VendorSignature, b: VendorSignature) -> DedupeScore:
    signals: dict[str, float] = {}

    if a.normalized_license and b.normalized_license:
        if a.normalized_license == b.normalized_license:
            signals["license"] = 1.0
        else:
            ratio = fuzz.ratio(a.normalized_license, b.normalized_license) / 100.0
            signals["license"] = ratio if ratio >= 0.85 else 0.0
    else:
        signals["license"] = 0.0

    signals["name"] = fuzz.token_set_ratio(a.normalized_name, b.normalized_name) / 100.0

    if a.normalized_address and b.normalized_address:
        signals["address"] = fuzz.partial_ratio(a.normalized_address, b.normalized_address) / 100.0
    else:
        signals["address"] = 0.0

    signals["email_domain"] = 1.0 if (a.email_domain and a.email_domain == b.email_domain) else 0.0
    signals["phone"] = 1.0 if (a.phone_last9 and a.phone_last9 == b.phone_last9) else 0.0
    signals["trn"] = 1.0 if (a.trn_vat_no and a.trn_vat_no == b.trn_vat_no) else 0.0

    weighted = sum(WEIGHTS[k] * v for k, v in signals.items())

    # Exact license or exact TRN match is decisive regardless of the rest.
    if signals["license"] >= 0.999 or signals["trn"] >= 0.999:
        weighted = max(weighted, 0.95)

    return DedupeScore(score=round(min(weighted, 1.0), 4), signals=signals)


def classify(score: float) -> str:
    if score >= AUTO_CANDIDATE_THRESHOLD:
        return "auto_candidate"
    if score >= WARNING_THRESHOLD:
        return "warning"
    return "ignore"
