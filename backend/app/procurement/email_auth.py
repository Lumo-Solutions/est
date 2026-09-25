"""Parses SPF/DKIM/DMARC verdicts out of an `Authentication-Results` header
(RFC 8601), as added by the receiving mail server before the poller ever
sees the message -- this platform never performs its own SPF/DKIM/DMARC
verification.

A message can carry more than one Authentication-Results header (one per
relay hop). The caller is responsible for picking the one closest to final
delivery -- `email.message.Message.get("Authentication-Results")` already
does this (it returns the first occurrence, which for a header every
upstream relay prepends is the most recent one, i.e. the receiving mailbox
provider's own verdict) -- this module only parses whatever single header
value it's given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.enums import AuthCheckResult

_RESULT_RE = re.compile(r"\b(spf|dkim|dmarc)=(\w+)", re.IGNORECASE)
_VALID_RESULTS = {r.value for r in AuthCheckResult}


@dataclass(frozen=True, slots=True)
class AuthResults:
    spf: str
    dkim: str
    dmarc: str


def parse_authentication_results(header_value: str | None) -> AuthResults:
    if not header_value:
        return AuthResults(spf=AuthCheckResult.UNKNOWN.value, dkim=AuthCheckResult.UNKNOWN.value, dmarc=AuthCheckResult.UNKNOWN.value)

    found: dict[str, str] = {}
    for mech, result in _RESULT_RE.findall(header_value):
        mech = mech.lower()
        result = result.lower()
        if mech not in found:
            found[mech] = result if result in _VALID_RESULTS else AuthCheckResult.UNKNOWN.value

    return AuthResults(
        spf=found.get("spf", AuthCheckResult.UNKNOWN.value),
        dkim=found.get("dkim", AuthCheckResult.UNKNOWN.value),
        dmarc=found.get("dmarc", AuthCheckResult.UNKNOWN.value),
    )


def has_auth_failure(results: AuthResults) -> bool:
    return AuthCheckResult.FAIL.value in (results.spf, results.dkim, results.dmarc)
