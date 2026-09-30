"""DWG support, unit level: content sniffing, the round-trip guarantee, and the
worker-side converter client against a fake converter loop.

The DWG fixtures come from `make dwg-fixtures`, i.e. from the REAL ODA converter
(our existing synthetic DXFs converted DXF -> DWG, then DWG -> DXF again).
"""

from __future__ import annotations

import time

import pytest

from app.core.errors import ValidationAppError
from app.integrations import dwg_converter as client
from app.integrations.dwg_converter import ConversionError
from app.intake.sample_pack import _vector_pdf
from app.services.takeoff import classify_upload
from tests.fixtures.dwg_fake_converter import (
    FakeConverter, fixture_bytes, make_settings, manifest, require_fixtures,
)
from tests.fixtures.dwg_sources import SOURCES, summarize


@pytest.fixture(autouse=True)
def _need_fixtures():
    require_fixtures()


def _pdf() -> bytes:
    return _vector_pdf("C-101", "A", "SITE PLAN", "A1")


# ------------------------------------------------------------------ sniffing
@pytest.mark.parametrize("name", list(SOURCES))
def test_real_dwg_is_detected_by_its_ac10_magic_whatever_the_name_or_declared_type(name):
    data = fixture_bytes(f"{name}.dwg")
    assert data[:4] == b"AC10"
    for filename, declared in ((f"{name}.dwg", None), (f"{name}.dwg", "application/octet-stream"), ("plan.pdf", "application/pdf"), ("noext", None)):
        assert classify_upload(filename, declared, data)[0] == "dwg"


def test_a_dot_dwg_that_is_really_a_pdf_is_detected_as_a_pdf():
    kind, content_type = classify_upload("Site Plan.dwg", "application/acad", _pdf())
    assert (kind, content_type) == ("vector_pdf", "application/pdf")


def test_a_dot_dwg_that_is_really_a_dxf_is_detected_as_a_dxf():
    kind, _ = classify_upload("Site Plan.dwg", None, SOURCES["takeoff_basic"]())
    assert kind == "dxf"


def test_a_dot_pdf_that_is_really_a_dwg_goes_down_the_dwg_path():
    assert classify_upload("Site Plan.pdf", "application/pdf", fixture_bytes("civil_site.dwg"))[0] == "dwg"


@pytest.mark.parametrize("payload", [b"", b"hello world, not a drawing", b"\x00" * 64, b"AC9999" + b"\x00" * 32])
def test_a_dot_dwg_with_no_dwg_header_is_rejected_with_a_clear_422_not_a_500(payload):
    with pytest.raises(ValidationAppError, match="not a valid DWG"):
        classify_upload("broken.dwg", "application/acad", payload)


def test_a_corrupt_dwg_with_a_valid_header_passes_sniffing_and_fails_later_in_the_converter():
    assert classify_upload("bad.dwg", None, fixture_bytes("corrupt.dwg"))[0] == "dwg"


@pytest.mark.parametrize("version", ["AC1009", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"])
def test_every_autocad_release_magic_is_recognised(version):
    assert classify_upload("x.dwg", None, version.encode() + b"\x00" * 32)[0] == "dwg"


def test_plain_pdf_and_dxf_uploads_are_unchanged():
    assert classify_upload("a.pdf", "application/pdf", _pdf())[0] == "vector_pdf"
    assert classify_upload("a.dxf", "application/dxf", SOURCES["intake_sheet"]())[0] == "dxf"


# ------------------------------------------------------------------ round trip
@pytest.mark.parametrize("name", list(SOURCES))
def test_dxf_to_dwg_to_dxf_round_trip_preserves_what_the_pipeline_extracts(name):
    original = summarize(SOURCES[name]())
    roundtrip = summarize(fixture_bytes(f"{name}.roundtrip.dxf"))

    assert roundtrip.keys() == original.keys(), "layouts changed in the round trip"
    for layout, before in original.items():
        after = roundtrip[layout]
        assert after["units"] == before["units"]
        assert after["entity_counts"] == before["entity_counts"]
        assert after["text"] == before["text"]
        assert after["vertex_total"] == before["vertex_total"]
        assert len(after["measurements"]) == len(before["measurements"])
        for (cap_a, kind_a, val_a, layer_a), (cap_b, kind_b, val_b, layer_b) in zip(
            after["measurements"], before["measurements"], strict=True
        ):
            assert (cap_a, kind_a, layer_a) == (cap_b, kind_b, layer_b)
            assert val_a == pytest.approx(val_b, rel=1e-6, abs=1e-6), f"{cap_a}/{kind_a} on {layer_a}"


def test_the_round_trip_check_is_not_vacuous_civil_site_yields_every_capability():
    measured = summarize(fixture_bytes("civil_site.roundtrip.dxf"))["Model"]["measurements"]
    assert {cap for cap, *_ in measured} >= {
        "alignment", "corridor_area", "pipe_network_topology", "trench_prismoidal_volume",
    }
    by_kind = {(cap, kind): value for cap, kind, value, _ in measured}
    assert by_kind[("pipe_network_topology", "pipe_network_total_length_m")] == pytest.approx(40.0)
    assert by_kind[("corridor_area", "corridor_area_m2")] == pytest.approx(800.0)


def test_converter_output_is_the_fixed_target_version():
    assert b"AC1032" in fixture_bytes("civil_site.roundtrip.dxf")[:400]  # ACAD2018
    assert manifest()["converter_version"]


# ------------------------------------------------------------------ client
def test_converts_and_reports_version_target_and_timing(tmp_path):
    dxf = fixture_bytes("civil_site.roundtrip.dxf")
    settings = make_settings(tmp_path)
    with FakeConverter(tmp_path, "ok", dxf) as conv:
        result = client.convert_dwg_to_dxf(fixture_bytes("civil_site.dwg"), settings)
    assert result.dxf == dxf
    assert (result.converter_version, result.target_version) == ("27.9.0.0", "ACAD2018")
    assert result.duration_ms >= 0
    assert conv.seen[0]["request"]["target_version"] == "ACAD2018"
    assert conv.seen[0]["request"]["output_format"] == "DXF"
    assert conv.seen[0]["request"]["timeout_s"] == 5
    assert not list((tmp_path / "jobs").iterdir()), "the job directory must be cleaned up"


def test_a_corrupt_dwg_is_reported_as_convert_failed_using_the_real_converters_verdict(tmp_path):
    settings = make_settings(tmp_path)
    with FakeConverter(tmp_path, "fail"):
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(fixture_bytes("corrupt.dwg"), settings)
    assert exc.value.reason == client.R_FAILED
    assert client.MANUAL_WORKAROUND in exc.value.user_message
    assert manifest()["outcomes"]["corrupt"]["reason"] == client.R_FAILED  # what the real converter did


def test_the_converters_own_timeout_verdict_maps_to_timeout(tmp_path):
    settings = make_settings(tmp_path)
    with FakeConverter(tmp_path, "timeout"):
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(fixture_bytes("civil_site.dwg"), settings)
    assert exc.value.reason == client.R_TIMEOUT
    assert manifest()["outcomes"]["timeout"]["reason"] == client.R_TIMEOUT
    assert manifest()["outcomes"]["works_after_timeout"] is True  # real converter survived the kill


def test_a_converter_that_claims_a_job_and_never_answers_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "_GRACE_S", 0.3)
    settings = make_settings(tmp_path, DWG_CONVERT_TIMEOUT_S=1)
    started = time.monotonic()
    with FakeConverter(tmp_path, "hang"):
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(fixture_bytes("civil_site.dwg"), settings)
    assert exc.value.reason == client.R_TIMEOUT
    assert time.monotonic() - started < 5
    assert not list((tmp_path / "jobs").iterdir())


def test_a_converter_that_never_picks_the_job_up_is_reported_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "_GRACE_S", 0.3)
    settings = make_settings(tmp_path, DWG_CONVERT_TIMEOUT_S=1)
    with FakeConverter(tmp_path, "ignore"):
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(fixture_bytes("civil_site.dwg"), settings)
    assert exc.value.reason == client.R_UNAVAILABLE


def test_no_converter_at_all_is_unavailable_immediately(tmp_path):
    settings = make_settings(tmp_path)
    started = time.monotonic()
    with pytest.raises(ConversionError) as exc:
        client.convert_dwg_to_dxf(b"AC1032", settings)
    assert exc.value.reason == client.R_UNAVAILABLE and time.monotonic() - started < 1
    assert not client.conversion_available(settings)


def test_converter_running_without_oda_installed_is_reported_not_installed(tmp_path):
    settings = make_settings(tmp_path)
    with FakeConverter(tmp_path, "not_installed"):
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(b"AC1032", settings)
    assert exc.value.reason == client.R_NOT_INSTALLED


def test_a_stale_heartbeat_means_the_converter_is_down(tmp_path):
    (tmp_path / "heartbeat.json").write_text('{"ts": %f, "version": "27.9.0.0", "ok": true}' % (time.time() - 600))
    status = client.converter_status(make_settings(tmp_path))
    assert not status.present and "stale" in (status.detail or "")


def test_the_feature_flag_switches_conversion_off_even_with_a_healthy_converter(tmp_path):
    with FakeConverter(tmp_path, "ok", b"  0\nSECTION\n"):
        assert client.conversion_available(make_settings(tmp_path))  # auto (unset) + converter present => on
        assert client.conversion_available(make_settings(tmp_path, DWG_CONVERSION_ENABLED="true"))
        off = make_settings(tmp_path, DWG_CONVERSION_ENABLED="false")
        assert not client.conversion_available(off)
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(b"AC1032", off)
    assert exc.value.reason == client.R_DISABLED


def test_a_blank_flag_from_compose_means_auto(tmp_path):
    assert make_settings(tmp_path, DWG_CONVERSION_ENABLED="").dwg_conversion_enabled is None


def test_output_that_is_not_a_dxf_is_rejected(tmp_path):
    settings = make_settings(tmp_path)
    with FakeConverter(tmp_path, "ok", b"this is not a dxf at all"):
        with pytest.raises(ConversionError) as exc:
            client.convert_dwg_to_dxf(fixture_bytes("civil_site.dwg"), settings)
    assert exc.value.reason == client.R_FAILED


def test_interpret_result_is_a_no_op_on_success_and_maps_every_reason():
    client.interpret_result({"ok": True}, 5)
    for raw_reason, expected in (("timeout", "timeout"), ("not_installed", "not_installed"), ("convert_failed", "convert_failed"), ("bad_request", "convert_failed"), (None, "convert_failed")):
        with pytest.raises(ConversionError) as exc:
            client.interpret_result({"ok": False, "reason": raw_reason}, 5)
        assert exc.value.reason == expected

