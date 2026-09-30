"""Client for the DWG -> DXF converter sandbox (deploy/dwg-converter).

The converter (ODA File Converter, internal use only -- see
docs/deploy-deltas.md) runs in its own container with NO network, a
read-only root filesystem and resource limits, because DWG is untrusted
input. It cannot be reached over a socket, so this module talks to it
through a shared spool directory (settings.dwg_spool_dir):

    jobs/<id>/input.dwg   we write it, then atomically jobs/<id>/request.json
    jobs/<id>/output.dxf  the converter writes it, then atomically result.json
    heartbeat.json        the converter refreshes it every few seconds

Everything here is blocking (file polling); callers in async code go through
asyncio.to_thread. Failures are ConversionError carrying a machine-readable
`reason`, which the worker stores on the drawing (needs_conversion) together
with `message` and MANUAL_WORKAROUND -- a failed conversion never raises out
of the pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass

from app.core.config import Settings, get_settings

MANUAL_WORKAROUND = (
    "Workaround: open the drawing in AutoCAD, BricsCAD or LibreCAD, save/export it as DXF (or PDF), "
    "upload that file, and re-run ingestion."
)
_POLL_S = 0.25
_GRACE_S = 15.0

# Reasons stored in drawings.conversion_reason.
R_DISABLED = "disabled"
R_UNAVAILABLE = "unavailable"
R_NOT_INSTALLED = "not_installed"
R_TIMEOUT = "timeout"
R_FAILED = "convert_failed"


class ConversionError(Exception):
    def __init__(self, reason: str, message: str, result: dict | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        # The converter's raw result.json when it produced one (recorded by the fixture builder).
        self.result = result

    @property
    def user_message(self) -> str:
        return f"{self.message} {MANUAL_WORKAROUND}"


@dataclass(frozen=True)
class ConversionResult:
    dxf: bytes
    converter_version: str
    target_version: str
    duration_ms: int


@dataclass(frozen=True)
class ConverterStatus:
    present: bool
    version: str | None = None
    detail: str | None = None


def _heartbeat(settings: Settings) -> dict | None:
    try:
        with open(os.path.join(settings.dwg_spool_dir, "heartbeat.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def converter_status(settings: Settings | None = None) -> ConverterStatus:
    """Is the converter container up (fresh heartbeat) with ODA installed?"""
    settings = settings or get_settings()
    hb = _heartbeat(settings)
    if hb is None:
        return ConverterStatus(False, None, "no converter heartbeat on the spool volume")
    age = time.time() - float(hb.get("ts", 0))
    if age > settings.dwg_heartbeat_max_age_s:
        return ConverterStatus(False, hb.get("version"), f"converter heartbeat is stale ({int(age)}s old)")
    if not hb.get("ok"):
        return ConverterStatus(False, None, "converter is running but the ODA File Converter is not installed in it")
    return ConverterStatus(True, hb.get("version"))


def check_available(settings: Settings | None = None) -> None:
    """Raises ConversionError unless a conversion can be attempted now."""
    settings = settings or get_settings()
    if settings.dwg_conversion_enabled is False:
        raise ConversionError(R_DISABLED, "DWG conversion is turned off on this server (DWG_CONVERSION_ENABLED=false).")
    status = converter_status(settings)
    if not status.present:
        reason = R_NOT_INSTALLED if status.detail and "not installed" in status.detail else R_UNAVAILABLE
        raise ConversionError(reason, f"The DWG converter is not installed or not running on this server ({status.detail}).")


def conversion_available(settings: Settings | None = None) -> bool:
    try:
        check_available(settings)
    except ConversionError:
        return False
    return True


def looks_like_dxf(data: bytes) -> bool:
    head = data[:8192]
    return b"SECTION" in head and b"\x00" not in head[:512]


def _write_json_atomic(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def interpret_result(result: dict, timeout_s: int) -> None:
    """Raises the ConversionError a converter result.json describes (no-op
    when it reports success). Pure, so the outcomes the real converter
    produced for a corrupt file / a timeout can be replayed in tests."""
    if result.get("ok"):
        return
    reason = result.get("reason") or R_FAILED
    if reason == "timeout":
        reason = R_TIMEOUT
    elif reason not in (R_NOT_INSTALLED, R_TIMEOUT):
        reason = R_FAILED
    msg = {
        R_TIMEOUT: f"Conversion timed out after {timeout_s}s.",
        R_NOT_INSTALLED: "The DWG converter is not installed in its container.",
    }.get(reason, "The DWG could not be converted (the file may be corrupt, truncated or use an unsupported version).")
    raise ConversionError(reason, msg, result)


def run_job(
    data: bytes, *, input_name: str, output_format: str, settings: Settings | None = None, timeout_s: int | None = None
) -> tuple[bytes, dict, int]:
    """One round trip through the converter. Returns (output bytes, the
    converter's result.json, elapsed ms); raises ConversionError on every
    failure mode. Blocking."""
    settings = settings or get_settings()
    check_available(settings)

    timeout_s = settings.dwg_convert_timeout_s if timeout_s is None else timeout_s
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(settings.dwg_spool_dir, "jobs", job_id)
    t0 = time.monotonic()
    try:
        os.makedirs(job_dir)
        with open(os.path.join(job_dir, input_name), "wb") as f:
            f.write(data)
        _write_json_atomic(
            os.path.join(job_dir, "request.json"),
            {
                "target_version": settings.dwg_target_version, "output_format": output_format,
                "timeout_s": timeout_s, "input_name": input_name,
            },
        )

        result_path = os.path.join(job_dir, "result.json")
        claimed_path = os.path.join(job_dir, "claimed")
        # Two phases: waiting for the (serial) converter to pick the job up,
        # then the converter's own per-file timeout plus a grace period for
        # the result file to appear.
        deadline = time.monotonic() + timeout_s + _GRACE_S
        claimed = False
        while not os.path.exists(result_path):
            if not claimed and os.path.exists(claimed_path):
                claimed = True
                deadline = time.monotonic() + timeout_s + _GRACE_S
            if time.monotonic() > deadline:
                raise ConversionError(
                    R_TIMEOUT if claimed else R_UNAVAILABLE,
                    f"The DWG converter did not finish within {timeout_s}s." if claimed
                    else "The DWG converter did not pick the file up (it may have stopped).",
                )
            time.sleep(_POLL_S)

        with open(result_path) as f:
            result = json.load(f)
        interpret_result(result, timeout_s)
        with open(os.path.join(job_dir, result.get("output_name", f"output.{output_format.lower()}")), "rb") as f:
            out = f.read()
        return out, result, int((time.monotonic() - t0) * 1000)
    except ConversionError:
        raise
    except (OSError, ValueError) as exc:
        raise ConversionError(R_FAILED, f"Could not exchange files with the DWG converter: {type(exc).__name__}.") from exc
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def convert_dwg_to_dxf(data: bytes, settings: Settings | None = None) -> ConversionResult:
    """Converts one DWG (bytes) to DXF at settings.dwg_target_version.
    Blocking. Raises ConversionError on every failure mode."""
    settings = settings or get_settings()
    dxf, result, elapsed_ms = run_job(data, input_name="input.dwg", output_format="DXF", settings=settings)
    if not looks_like_dxf(dxf):
        raise ConversionError(R_FAILED, "The converter produced a file that is not a valid DXF.")
    return ConversionResult(
        dxf=dxf,
        converter_version=str(result.get("converter_version") or "unknown"),
        target_version=str(result.get("target_version") or settings.dwg_target_version),
        duration_ms=elapsed_ms,
    )
