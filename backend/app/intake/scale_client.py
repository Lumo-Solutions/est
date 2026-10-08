"""A command-line stand-in for the browser's resumable upload (docs/intake-scale/report.md), for proving the pipeline
without a browser: hash every file (streamed), register in batches, upload only what the server asks for, 4 at a time,
each retried. The same protocol as `frontend/src/features/tenderIntake/upload/uploader.ts`.

    python -m app.intake.scale_client --dir /data/pack --project <uuid> --base http://backend:8000 \
        --token-url http://keycloak:8080/realms/installtec/protocol/openid-connect/token \
        --client-id installtec-backend --client-secret ... --user estimator1 --password '...'

`--stop-after N` kills this process (no cleanup, like closing the tab) after N files were uploaded: run it again with the
same arguments and it resumes, sending only what the server does not have yet. Dev/test tool: it talks to whatever
`--base` points at with a password-grant token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

MB = 1024 * 1024


class Token:
    def __init__(self, url: str, client_id: str, secret: str, user: str, password: str) -> None:
        self._args = (url, client_id, secret, user, password)
        self._lock = threading.Lock()
        self._value = ""
        self._expires = 0.0

    def get(self, force: bool = False) -> str:
        with self._lock:
            if force or time.time() > self._expires - 30:
                url, client_id, secret, user, password = self._args
                r = httpx.post(
                    url, data={"grant_type": "password", "client_id": client_id, "client_secret": secret, "username": user, "password": password}, timeout=30
                )
                r.raise_for_status()
                body = r.json()
                self._value, self._expires = body["access_token"], time.time() + int(body.get("expires_in", 300))
            return self._value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(MB), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--base", default="http://backend:8000")
    ap.add_argument("--token-url", required=True)
    ap.add_argument("--client-id", default="installtec-backend")
    ap.add_argument("--client-secret", default=os.environ.get("KEYCLOAK_CLIENT_SECRET", ""))
    ap.add_argument("--user", default="estimator1")
    ap.add_argument("--password", default=os.environ.get("UPLOAD_PASSWORD", ""))
    ap.add_argument("--label", default="Scale proof")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--stop-after", type=int, default=0, help="exit abruptly after this many files were uploaded (simulates closing the tab)")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    token = Token(args.token_url, args.client_id, args.client_secret, args.user, args.password)
    client = httpx.Client(base_url=args.base + "/api/v1", timeout=httpx.Timeout(600, connect=30), limits=httpx.Limits(max_connections=16))

    def call(method: str, url: str, **kw) -> httpx.Response:
        extra = kw.pop("headers", {})
        r = client.request(method, url, headers={"Authorization": f"Bearer {token.get()}", **extra}, **kw)
        if r.status_code == 401 and "content" not in kw:  # the token expired: get a new one and ask again
            r = client.request(method, url, headers={"Authorization": f"Bearer {token.get(force=True)}", **extra}, **kw)
        return r

    files = sorted(p for p in args.dir.rglob("*") if p.is_file() and p.name != "manifest.json")
    total = len(files)
    t0 = time.time()
    print(f"hashing {total} files ...", flush=True)
    with ThreadPoolExecutor(2) as pool:
        shas = list(pool.map(sha256_file, files))
    t_hash = time.time() - t0
    rel = [p.relative_to(args.dir).as_posix() for p in files]
    print(f"hashed in {t_hash:.1f}s", flush=True)

    to_send: list[tuple[int, str]] = []
    rejected: list[tuple[str, str]] = []
    package_id = None
    resumed = False
    already = 0
    for start in range(0, total, 500):
        batch = [{"path": rel[i], "size": files[i].stat().st_size, "sha256": shas[i]} for i in range(start, min(start + 500, total))]
        r = call("POST", f"/projects/{args.project}/tender-packages/register", json={"package_id": package_id, "total_files": total, "label": args.label, "files": batch})
        if r.status_code != 200:
            print("register failed", r.status_code, r.text[:300], flush=True)
            return 2
        body = r.json()
        if package_id is None:
            resumed = body["resumed"]  # only the first batch says whether an unfinished upload was found
        package_id = body["package_id"]
        by_path: dict[str, list[int]] = {}
        for i in range(start, min(start + 500, total)):
            by_path.setdefault(rel[i], []).append(i)
        for f in body["files"]:
            idx = by_path[f["path"]].pop(0)
            if f["state"] == "rejected":
                rejected.append((f["path"], f["reason"]))
            elif f["state"] == "uploaded":
                already += 1
            elif f["upload"]:
                to_send.append((idx, f["document_id"]))
    print(f"registered: pack={package_id} resumed={resumed} already_on_server={already} rejected={len(rejected)} to_send={len(to_send)}", flush=True)

    done = 0
    failed: list[tuple[str, str]] = []
    lock = threading.Lock()

    def send(item: tuple[int, str]) -> None:
        nonlocal done
        idx, doc_id = item
        path = files[idx]
        for attempt in range(4):
            try:
                with open(path, "rb") as fh:
                    r = call(
                        "PUT", f"/tender-packages/{package_id}/documents/{doc_id}/content", content=fh,
                        headers={"content-type": "application/octet-stream", "content-length": str(path.stat().st_size)},
                    )
                if r.status_code == 200:
                    with lock:
                        done += 1
                        if done % 50 == 0:
                            print(f"uploaded {done}/{len(to_send)}  ({already + done}/{total})", flush=True)
                        if args.stop_after and done >= args.stop_after:
                            print(f"--stop-after {args.stop_after}: exiting abruptly", flush=True)
                            os._exit(3)
                    return
                if r.status_code == 401:
                    token.get(force=True)  # expired mid-upload: retry with a fresh token
                elif r.status_code == 409 or 400 <= r.status_code < 500:
                    with lock:
                        failed.append((rel[idx], f"{r.status_code} {r.text[:160]}"))
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5 * 4**attempt)
        with lock:
            failed.append((rel[idx], "gave up after retries"))

    t1 = time.time()
    with ThreadPoolExecutor(args.concurrency) as pool:
        for fut in as_completed([pool.submit(send, it) for it in to_send]):
            fut.result()
    t_up = time.time() - t1
    report = {
        "files": total, "package_id": package_id, "resumed": resumed, "already_on_server": already, "sent": done, "rejected": rejected, "failed": failed,
        "hash_seconds": round(t_hash, 1), "upload_seconds": round(t_up, 1),
        "upload_mb": round(sum(files[i].stat().st_size for i, _ in to_send) / MB, 1),
    }
    print(json.dumps({k: (v if k not in ("rejected", "failed") else len(v)) for k, v in report.items()}), flush=True)
    if args.report:
        args.report.write_text(json.dumps(report, indent=1))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
