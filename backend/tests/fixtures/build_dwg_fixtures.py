"""Builds the DWG test fixtures with the REAL ODA converter sandbox.

Run by `make dwg-fixtures` (deploy/dwg-converter/build-fixtures.sh), which
starts the hardened converter container next to this process and shares its
/spool volume:

    for each source DXF   ->  <name>.dwg            (DXF -> DWG, ACAD2018)
                          ->  <name>.roundtrip.dxf  (that DWG -> DXF again)
    <name>.source.dxf     ->  the original DXF (the real-backend spec compares against it)
    pdf_named.dwg         ->  a PDF with a .dwg name
    corrupt.dwg           ->  valid "AC10xx" magic, garbage body; the
                              converter's real verdict is recorded
    timeout.result.json   ->  the converter's real verdict when a file cannot
                              finish inside its per-file timeout (0 s)
    manifest.json         ->  converter version + every recorded outcome

Nothing here is committed (backend/tests/fixtures/dwg/ is gitignored): the
DWGs are produced by a proprietary tool from our own synthetic DXFs.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from app.core.config import Settings
from app.integrations import dwg_converter
from app.integrations.dwg_converter import ConversionError
from tests.fixtures.dwg_sources import FIXTURE_DIR, SOURCES


def _settings() -> Settings:
    return Settings(
        APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y",
        S3_ENDPOINT="http://s3.test", VLLM_API_BASE="http://vllm.internal:8000/v1",
        DWG_SPOOL_DIR=os.environ.get("DWG_SPOOL_DIR", "/spool"), DWG_TARGET_VERSION="ACAD2018",
    )


def _wait_for_converter(settings: Settings, seconds: int = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if dwg_converter.converter_status(settings).present:
            return
        time.sleep(1)
    raise SystemExit("dwg fixtures: the converter container never published a heartbeat")


def corrupt_dwg() -> bytes:
    """Valid AutoCAD 2018 magic, then deterministic garbage: passes content
    sniffing, fails in the converter."""
    body = bytearray()
    x = 0x9E3779B9
    for _ in range(4096):
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        body.append((x >> 16) & 0xFF)
    return b"AC1032" + b"\x00" * 6 + bytes(body)


def main() -> int:
    settings = _settings()
    _wait_for_converter(settings)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"sources": {}, "outcomes": {}}

    for name, build in SOURCES.items():
        source = build()
        dwg, r1, ms1 = dwg_converter.run_job(source, input_name="input.dxf", output_format="DWG", settings=settings)
        assert dwg[:4] == b"AC10", f"{name}: converter output is not a DWG"
        dxf, r2, ms2 = dwg_converter.run_job(dwg, input_name="input.dwg", output_format="DXF", settings=settings)
        (FIXTURE_DIR / f"{name}.source.dxf").write_bytes(source)  # what the real-backend spec compares against
        (FIXTURE_DIR / f"{name}.dwg").write_bytes(dwg)
        (FIXTURE_DIR / f"{name}.roundtrip.dxf").write_bytes(dxf)
        manifest["sources"][name] = {
            "dwg_bytes": len(dwg), "roundtrip_dxf_bytes": len(dxf), "dxf_to_dwg_ms": ms1, "dwg_to_dxf_ms": ms2,
            "converter_version": r2.get("converter_version"),
        }
        manifest["converter_version"] = r2.get("converter_version")
        print(f"{name}: dxf->dwg {ms1}ms ({len(dwg)} B), dwg->dxf {ms2}ms ({len(dxf)} B)")

    # A PDF that someone named .dwg (content sniffing must call it a PDF).
    from app.intake.sample_pack import _vector_pdf

    (FIXTURE_DIR / "pdf_named.dwg").write_bytes(_vector_pdf("C-901", "A", "MISLABELLED", "A1"))

    # Real verdict on a corrupt file (run_job would raise; capture the raw result.json instead).
    bad = corrupt_dwg()
    (FIXTURE_DIR / "corrupt.dwg").write_bytes(bad)
    try:
        dwg_converter.run_job(bad, input_name="input.dwg", output_format="DXF", settings=settings)
        raise SystemExit("dwg fixtures: the converter unexpectedly converted the corrupt file")
    except ConversionError as exc:
        manifest["outcomes"]["corrupt"] = {"reason": exc.reason, "message": exc.message, "raw": exc.result}
        print(f"corrupt: {exc.reason}: {exc.message}")

    # Real verdict on a per-file timeout: timeout_s=0 can never be met, so this deterministically
    # exercises the converter's kill-the-process-group path.
    good = (FIXTURE_DIR / "civil_site.dwg").read_bytes()
    try:
        dwg_converter.run_job(good, input_name="input.dwg", output_format="DXF", settings=settings, timeout_s=0)
        raise SystemExit("dwg fixtures: a 0 s timeout unexpectedly succeeded")
    except ConversionError as exc:
        manifest["outcomes"]["timeout"] = {"reason": exc.reason, "message": exc.message, "raw": exc.result}
        print(f"timeout: {exc.reason}: {exc.message}")

    # The converter must still work after killing a job.
    dwg_converter.run_job(good, input_name="input.dwg", output_format="DXF", settings=settings)
    manifest["outcomes"]["works_after_timeout"] = True

    Path(FIXTURE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("dwg fixtures: done ->", FIXTURE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
