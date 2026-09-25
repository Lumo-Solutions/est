from __future__ import annotations

from app.procurement.email_auth import has_auth_failure, parse_authentication_results


def test_parses_pass_pass_pass():
    header = "mx.example.com; spf=pass smtp.mailfrom=vendor.com; dkim=pass header.d=vendor.com; dmarc=pass"
    result = parse_authentication_results(header)
    assert (result.spf, result.dkim, result.dmarc) == ("pass", "pass", "pass")
    assert not has_auth_failure(result)


def test_flags_a_failure():
    header = "mx.example.com; spf=fail smtp.mailfrom=vendor.com; dkim=pass; dmarc=fail"
    result = parse_authentication_results(header)
    assert result.spf == "fail"
    assert result.dmarc == "fail"
    assert has_auth_failure(result)


def test_missing_header_is_unknown_not_pass():
    result = parse_authentication_results(None)
    assert (result.spf, result.dkim, result.dmarc) == ("unknown", "unknown", "unknown")
    assert not has_auth_failure(result)  # unknown is flagged for review separately, not treated as a "failure"


def test_parses_result_regardless_of_comment_ordering():
    header = "mx.example.com;\n\tspf=pass smtp.mailfrom=vendor.com;\n\tdkim=fail header.d=vendor.com"
    result = parse_authentication_results(header)
    assert result.spf == "pass"
    assert result.dkim == "fail"
    assert has_auth_failure(result)


def test_unrecognized_result_token_is_unknown():
    header = "mx.example.com; spf=neutral"
    result = parse_authentication_results(header)
    assert result.spf == "unknown"
