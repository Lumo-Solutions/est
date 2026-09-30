"""Spool-directory worker: turns /spool/jobs/<id>/input.dwg into a DXF.

The container has NO network, so it cannot be a Celery worker or an HTTP
service. The backend's `convert`-queue worker shares the /spool volume with
it and speaks this tiny file protocol instead:

    worker  writes  jobs/<id>/input.dwg, then (atomically) jobs/<id>/request.json
    us      write   jobs/<id>/output.dxf (on success), then (atomically) result.json
    worker  reads result.json, fetches output.dxf, deletes jobs/<id>/

We also publish heartbeat.json every few seconds so the backend can tell
"converter not installed / not running" apart from "conversion failed".
The per-file timeout is enforced here by killing the whole process group
(ODAFileConverter + xvfb-run + Xvfb).

stdlib only: the image ships nothing but python3 and the ODA package.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

SPOOL = os.environ.get("SPOOL_DIR", "/spool")
JOBS = os.path.join(SPOOL, "jobs")
WORK = os.environ.get("WORK_DIR", "/tmp/work")
POLL_S = 0.5
HEARTBEAT_S = 5
JOB_TTL_S = 3600
DEFAULT_TIMEOUT_S = 120
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_TARGETS = {"ACAD2018", "ACAD2013", "ACAD2010", "ACAD2007", "ACAD2004", "ACAD2000"}
_FORMATS = {"DXF", "DWG"}


def converter_version() -> str | None:
    m = glob.glob("/usr/bin/ODAFileConverter_*")
    if not m:
        return None
    return os.path.basename(sorted(m)[-1]).split("_", 1)[1]


def write_json_atomic(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def heartbeat(version: str | None) -> None:
    try:
        write_json_atomic(
            os.path.join(SPOOL, "heartbeat.json"), {"ts": time.time(), "version": version, "ok": version is not None}
        )
    except OSError:
        pass


def run_conversion(job_dir: str, request: dict, version: str | None) -> dict:
    """request: {target_version, output_format (DXF|DWG), timeout_s, input_name}.
    output_format DWG exists only so the test setup can build DWG fixtures
    from our DXF fixtures with this same sandbox; the app itself only asks
    for DXF."""
    t0 = time.monotonic()
    target = request.get("target_version", "ACAD2018")
    out_fmt = request.get("output_format", "DXF")
    timeout_s = int(request.get("timeout_s", DEFAULT_TIMEOUT_S))
    in_name = request.get("input_name", "input.dwg")
    result: dict = {"ok": False, "converter_version": version, "target_version": target, "error": None, "reason": None}
    if target not in _TARGETS or out_fmt not in _FORMATS or "/" in in_name or in_name.startswith("."):
        result.update(reason="bad_request", error="unsupported request parameters")
        return result
    if version is None:
        result.update(reason="not_installed", error="ODA File Converter is not installed in the converter image")
        return result

    work = os.path.join(WORK, os.path.basename(job_dir))
    src, out = os.path.join(work, "in"), os.path.join(work, "out")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(src)
    os.makedirs(out)
    try:
        shutil.copyfile(os.path.join(job_dir, in_name), os.path.join(src, in_name))
        # args: in-dir out-dir out-version out-type recurse audit filter
        cmd = ["xvfb-run", "-a", "/usr/bin/ODAFileConverter", src, out, target, out_fmt, "0", "1", in_name]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            log, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            result.update(reason="timeout", error=f"conversion exceeded the {timeout_s}s per-file timeout")
            return result
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # reap stray Xvfb / children
            except (ProcessLookupError, PermissionError):
                pass
        ext = out_fmt.lower()
        produced = sorted(glob.glob(os.path.join(out, f"*.{ext}")) + glob.glob(os.path.join(out, f"*.{ext.upper()}")))
        tail = (log or b"").decode("utf-8", "replace").strip()[-400:]
        if proc.returncode != 0 or not produced or os.path.getsize(produced[0]) == 0:
            result.update(
                reason="convert_failed", error=f"converter exited {proc.returncode} without producing a {out_fmt}", detail=tail
            )
            return result
        shutil.copyfile(produced[0], os.path.join(job_dir, f"output.{ext}"))
        result.update(ok=True, output_bytes=os.path.getsize(produced[0]), output_name=f"output.{ext}", detail=tail)
        return result
    except Exception as exc:  # noqa: BLE001 -- any failure is reported back, never crashes the loop
        result.update(reason="convert_failed", error=f"{type(exc).__name__}: {exc}")
        return result
    finally:
        result["duration_ms"] = int((time.monotonic() - t0) * 1000)
        shutil.rmtree(work, ignore_errors=True)


def pending_jobs() -> list[str]:
    try:
        names = os.listdir(JOBS)
    except FileNotFoundError:
        return []
    out = []
    for n in names:
        d = os.path.join(JOBS, n)
        if (
            _JOB_ID.match(n)
            and os.path.isfile(os.path.join(d, "request.json"))
            and not os.path.exists(os.path.join(d, "result.json"))
            and not os.path.exists(os.path.join(d, "claimed"))
        ):
            out.append(d)
    return sorted(out, key=os.path.getmtime)


def gc_old_jobs() -> None:
    now = time.time()
    try:
        for n in os.listdir(JOBS):
            d = os.path.join(JOBS, n)
            if _JOB_ID.match(n) and now - os.path.getmtime(d) > JOB_TTL_S:
                shutil.rmtree(d, ignore_errors=True)
    except FileNotFoundError:
        pass


def main() -> int:
    os.makedirs(JOBS, exist_ok=True)
    version = converter_version()
    print(f"converter loop up; ODA version={version}", flush=True)
    last_hb = 0.0
    last_gc = 0.0
    unusable: set[str] = set()
    while True:
        now = time.monotonic()
        if now - last_hb >= HEARTBEAT_S:
            heartbeat(version)
            last_hb = now
        if now - last_gc >= 300:
            gc_old_jobs()
            last_gc = now
        jobs = pending_jobs()
        if not jobs:
            time.sleep(POLL_S)
            continue
        job_dir = jobs[0]
        if job_dir in unusable:
            time.sleep(POLL_S)
            continue
        try:
            open(os.path.join(job_dir, "claimed"), "w").close()
            with open(os.path.join(job_dir, "request.json")) as f:
                request = json.load(f)
            result = run_conversion(job_dir, request, version)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "reason": "convert_failed", "error": f"{type(exc).__name__}: {exc}", "converter_version": version}
        try:
            write_json_atomic(os.path.join(job_dir, "result.json"), result)
        except OSError as exc:
            # A job directory we cannot write to (wrong owner/perms): the loop
            # must survive it -- one bad job must never take the converter down.
            unusable.add(job_dir)
            print(f"job {os.path.basename(job_dir)} unusable: {exc}", flush=True)
            continue
        print(f"job {os.path.basename(job_dir)} ok={result.get('ok')} reason={result.get('reason')} ms={result.get('duration_ms')}", flush=True)
        heartbeat(version)
        last_hb = time.monotonic()


if __name__ == "__main__":
    sys.exit(main())
