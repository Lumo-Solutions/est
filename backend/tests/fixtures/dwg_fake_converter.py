"""A stand-in for the converter container's spool loop (deploy/dwg-converter/
converter_loop.py), so the worker-side client and the conversion task can be
tested inside the plain pytest container, which has no ODA converter.

It speaks the same file protocol. What it answers is REPLAYED from what the
real converter produced when `make dwg-fixtures` built the fixtures (real
round-tripped DXF bytes, the real result.json for a corrupt file and for a
timeout), so these tests exercise the real outcomes, not invented ones.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from app.core.config import Settings
from tests.fixtures.dwg_sources import FIXTURE_DIR

_MANIFEST = FIXTURE_DIR / "manifest.json"


def fixtures_available() -> bool:
    return _MANIFEST.exists()


def require_fixtures() -> None:
    """Skip when the DWG fixtures could not be built (no ODA .deb on this
    machine) -- but fail when REQUIRE_DWG_FIXTURES=1 (make test-*), so a
    machine that has the converter can never silently skip these tests."""
    if fixtures_available():
        return
    msg = "DWG fixtures not built (run `make dwg-fixtures`; needs deploy/vendor/oda/*.deb)"
    if os.environ.get("REQUIRE_DWG_FIXTURES") == "1":
        pytest.fail(msg)
    pytest.skip(msg)


def manifest() -> dict:
    require_fixtures()
    return json.loads(_MANIFEST.read_text())


def fixture_bytes(name: str) -> bytes:
    require_fixtures()
    return (FIXTURE_DIR / name).read_bytes()


def make_settings(spool: Path, **overrides) -> Settings:
    return Settings(
        APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y",
        S3_ENDPOINT="http://s3.test", VLLM_API_BASE="http://vllm.internal:8000/v1",
        DWG_SPOOL_DIR=str(spool), DWG_CONVERT_TIMEOUT_S=overrides.pop("DWG_CONVERT_TIMEOUT_S", 5),
        **overrides,
    )


class FakeConverter:
    """mode: "ok" (answer with `dxf`), "fail" (the real corrupt-file verdict),
    "timeout" (the real per-file-timeout verdict), "hang" (claim the job, never
    answer), "ignore" (never even claim it), "not_installed" (heartbeat says the
    ODA binary is missing)."""

    def __init__(self, spool: Path, mode: str = "ok", dxf: bytes | None = None) -> None:
        self.spool, self.mode, self.dxf = spool, mode, dxf
        self.jobs = spool / "jobs"
        self.seen: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _heartbeat(self) -> None:
        ok = self.mode != "not_installed"
        # Atomic, like the real loop: a reader must never see a half-written file.
        tmp = self.spool / "heartbeat.json.tmp"
        tmp.write_text(json.dumps({"ts": time.time(), "version": "27.9.0.0" if ok else None, "ok": ok}))
        os.replace(tmp, self.spool / "heartbeat.json")

    def _loop(self) -> None:
        last_hb = 0.0
        while not self._stop.is_set():
            if time.monotonic() - last_hb > 1:
                self._heartbeat()
                last_hb = time.monotonic()
            for job in sorted(self.jobs.glob("*")) if self.jobs.exists() else []:
                req, claimed, result = job / "request.json", job / "claimed", job / "result.json"
                if not req.exists() or claimed.exists() or result.exists() or self.mode == "ignore":
                    continue
                claimed.write_text("")
                request = json.loads(req.read_text())
                self.seen.append({"request": request, "input_bytes": (job / request["input_name"]).stat().st_size})
                if self.mode == "hang":
                    continue
                self._answer(job, request)
            time.sleep(0.05)

    def _answer(self, job: Path, request: dict) -> None:
        recorded = manifest()["outcomes"]
        if self.mode == "fail":
            payload = recorded["corrupt"]["raw"]
        elif self.mode == "timeout":
            payload = recorded["timeout"]["raw"]
        else:
            assert self.dxf is not None
            (job / "output.dxf").write_bytes(self.dxf)
            payload = {
                "ok": True, "converter_version": "27.9.0.0", "target_version": request["target_version"],
                "output_name": "output.dxf", "output_bytes": len(self.dxf), "duration_ms": 1200,
            }
        (job / "result.json.tmp").write_text(json.dumps(payload))
        os.replace(job / "result.json.tmp", job / "result.json")

    def __enter__(self) -> FakeConverter:
        self.jobs.mkdir(parents=True, exist_ok=True)
        self._heartbeat()
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
