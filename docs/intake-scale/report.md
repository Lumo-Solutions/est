# Production-scale intake: report

Branch `fix/intake-scale`. A real 1,600-file tender folder crashed the browser upload at ~520 files and took Docker
down. This report starts with the diagnosis (written before any code changed) and ends with the proof runs.

## 0. Diagnosis (evidence first)

### What the crashed pack looked like (DB, taken with the workers stopped)

Package `661d42e3-c5a7-4d41-a532-d5810fd07937`, project `542c2504-4d0d-4243-8550-50019b6013b7`:

| fact | value |
|---|---|
| upload requests that reached the backend | 28 (1 create + 27 `/files`), 20 files each = **560 files registered** of 1,600 |
| `project_documents` in the pack | 560 rows: **496 `received`, 64 `processing`**, 0 classified, 0 routed |
| bytes registered | 1.3 GB (max file 36 MB, mean 2.4 MB) |
| distinct sha256 | 364 of 560 (196 byte-identical duplicates inside the pack) |
| first / last row created | 07:04:57 / 07:07:17 UTC (2 min 20 s of upload) |
| Redis queues (ingest, embed, vlm, convert...) | **all empty**, `unacked` empty: the work items were lost, the DB rows were orphaned |
| `tender_packages.status` | `processing` forever (nothing would ever move it) |

So roughly 35 % of the folder arrived, none of it was finished, and there was nothing left in the broker to finish it.

### What the containers recorded

* `OOMKilled=false` on every container. Docker's own OOM killer did **not** fire: the pressure was on the *WSL2 VM*, which
  Docker Desktop caps at ~7.7 GB (`docker info`: 8,255,057,920 bytes, 12 CPUs), and **no container had a memory limit**
  (only `celery-worker-convert` 512 MB, `celery-worker-quotation` 512 MB and `dwg-converter` 2 GB had one). When the VM
  is out of memory the whole VM thrashes and Windows is starved with it, which is the "Docker went down" symptom.
* Backend log: `watchfiles ... Cannot allocate memory (os error 12)` (the dev auto-reloader could not even allocate an
  inotify watch), then the process was restarted by the reload supervisor.
* Worker log: at 07:07:41 the ingest worker logs `missed heartbeat` for **four sibling workers** (the 4 prefork children
  were frozen), and the log then ends. The next line is the restart at 07:26 after the stack was brought back by hand.
  `caddy_dev` exited 255, `dwg_converter` exit 137 (SIGKILL on shutdown).
* Between 07:05:01 and 07:05:14 the worker received **4 `process_tender_package` tasks** (one per upload batch), each
  of which immediately fanned out 16 documents at a time. From 07:06:07 the log is a wall of
  `tender_intake: could not prepare <id> ... TimeoutError` (the 60 s `INTAKE_DOC_TIMEOUT_S` expiring because the
  extraction threads were starved), i.e. the box was already saturated about a minute and a half in.
* The AI provider in use was the real one (`openai_compatible`, dashscope). 1,310 rows exist in `ai_calls` for the
  tenant; answers are cached in `ai_cache` (keyed by tenant/task/input sha/model/prompt version), so a re-run of the
  same bytes is not billed again, provided the resume goes through the same gateway.

What was **not** recorded: per-container peak memory (nothing sampled it) and the browser's own crash reason. The browser
side below is therefore inference from the code, not from a crash dump.

### Root causes (each traced to code)

**Upload (browser and backend)**

1. **The backend buffers every file of a request in memory, twice.** `routes/tender_intake.py::_read_uploads` does
   `await f.read(max+1)` for each `UploadFile` and keeps the bytes; `services/tender_intake.py::_add_files` hashes the
   bytes and `integrations/s3.py::put_object_streaming` (which, despite the name, takes a whole `bytes` and puts it in one
   request) uploads them. A request may hold up to `INTAKE_MAX_REQUEST_BYTES` = 300 MB, plus Starlette's spooled copy, plus
   the hash/put copies. Several such requests overlap because the browser does not wait for the workers.
2. **The browser has no resume and no backpressure.** `UploadPanel.tsx` keeps every `File` in React state, renders every
   one of them in a `<ul>` (1,600 rows), and posts batches of up to 20 files / 200 MB as one `FormData` each; after every
   batch it invalidates the tree/list queries, which poll every 2 s. Nothing is registered up front, nothing is hashed,
   a dropped tab loses the list, and re-dropping the folder uploads everything again (the backend can only dedupe *after*
   it has received and hashed the bytes).
3. **Upload dispatch is fire-and-forget.** Every `/files` request enqueues its own `process_tender_package` with a 3 s
   countdown. Nothing in the DB records that a task was enqueued, so when the broker/worker went down the 560 rows were
   orphaned (see the empty queues above).

**Processing (the worker)**

4. **One Celery task per upload batch, with the whole batch inside it.** `workers/tasks/tender_intake.py` loops over the
   documents in one task (`soft_time_limit=1800`): no per-file task, no per-file retry, no pause, and a 1,600-file pack
   would hit the 30-minute limit even without a crash.
5. **Unbounded fan-out inside the task.** `prepare_batch` does `asyncio.gather` over 16 documents
   (`INTAKE_AI_BATCH_SIZE`). Only the AI call is behind the semaphore (`INTAKE_AI_CONCURRENCY` = 4); download, safety
   check, text extraction and page rendering for all 16 run at once, each in its own thread, each holding the whole file
   (up to 60 MB). With the worker's `-c 4` and four batch tasks in parallel that is up to **64 files in memory at once**,
   each parsed twice (pypdf for the safety check, pdfplumber for extraction) and rendered.
6. **PDF rendering is not capped.** `build_images` renders page 1 at 100 dpi and again at **170 dpi** through
   `render_page_png`, which allocates the full page bitmap. An A0/A1 drawing at 170 dpi is ~8,000 x 5,600 px = ~180 MB of
   bitmap, plus the `to_pil()` copy, plus the PNG encode. `check_file` and `_extract_pdf` also parse the whole document
   (pdfplumber builds `lines/rects/curves` objects for page 1 of a CAD export: hundreds of MB).
7. **No worker hygiene.** `celery-worker` runs `-c 4` with no `--max-tasks-per-child`, no `--max-memory-per-child` and no
   container `mem_limit`/`cpus`; the backend has none either. There is no per-file time or size limit apart from the 60 s
   extraction timeout, and files above 60 MB are *rejected at upload* rather than parked for a person.
8. **No sweeper for intake files.** `reap_stale_jobs` / `reap_stuck_drawings` do not look at `project_documents`, so a file
   left in `received`/`processing` stays there forever.
9. **The AI rate limit is not applied here.** `AI_RATE_LIMIT_PER_MIN` exists but nothing paces the intake's calls beyond
   the 4-way semaphore; a 429 is retried 3 times at 5 s and the file then falls back to rules.

**UI at scale**

10. The upload queue renders every row, and "Confirm all" sends the ids of the rows currently loaded, so it cannot
    confirm what is not on screen.

### What this means for the fix

The failure is a chain, not a single leak: unbounded request buffering -> unbounded per-batch fan-out and huge page
renders in the worker -> no container limits, so the 7.7 GB WSL VM starves -> the broker work is lost -> nothing in the DB
can restart it. The fix therefore has four parts: a bounded, resumable upload; per-file tasks driven by the database (not
by in-flight broker messages) under hard limits; container containment; and recovery + control (pause / resume / cancel,
sweeper).

## 1. Upload, now resumable

Register (path, size, sha256) in batches of 500, then one raw streaming PUT per file, 4 at a time, retried; the server streams to S3
(multipart above 8 MiB, never more than one part in memory, digest checked before the object becomes visible) and drops a stalled
upload after 60 s. Re-dropping the folder resumes from the server's state. Browser side: SHA-256 streamed in 4 MB slices, no file list
rendered beyond 10 rows, progress `X / N`. Proven at scale with a CLI client speaking the same protocol (`app/intake/scale_client.py`):
upload killed abruptly after 700 files, re-run: `resumed=True already_on_server=721 to_send=1181 rejected=18`, no duplicate rows.

## 2. Processing under hard limits

One Celery task per file, enqueued from the database (`dispatch_intake`, at most `INTAKE_DISPATCH_LIMIT`=40 in flight, paused packs skipped),
swept every 30 s. prefetch 1, concurrency from config (2 on dev), `--max-tasks-per-child`, `--max-memory-per-child`; drawing page index on its
own queue/worker (`index`, concurrency 1). Files over 40 MiB, with too many pages or slower than 240 s land in "Needs your check: too large".
CAD-export PDF pages (>20,000 objects) are read with PDFium (real 8 MB A0 sheet: pdfplumber 163 s / 3 GB, now 2.4 s / 0.4 GB); page renders are
capped (A1-and-below render byte-identical to before, so cached AI answers still hit). AI: gateway rate limit honoured by waiting for the next window
(6 tries) instead of dropping to rules; 429/5xx back off inside the gateway; the failure breaker is shared through Redis.
**Deviation:** "batch text-only files into one AI call" was not done. It changes the prompt/input hash (re-bills every cached answer) and puts several
documents in one prompt, which lets one document's text influence another's class (the injection defence this project built). Calls are instead
bounded, rate-limited, cached, and duplicates copy their original's class.

## 3. Containment

`mem_limit`/`cpus` on backend and every worker, concurrency and recycling from env: see `docs/deploy-deltas.md`. Not limited (and measured large):
Postgres (peak 2.4 GB) and SeaweedFS (peak 1.9 GB): size the Docker VM at 10 GB or add limits for them.

## 4. Recovery

`pause` / `resume` / `cancel` (lead_estimator+, audited, UI buttons); `reap_stuck_documents` (processing > 360 s goes back to received, 3 attempts then
failed with a reason) runs in `intake_tick` and in the hourly stale-job reaper. Pack and document state live in the DB, so a lost broker message only
delays a file. Redis visibility timeout 30 min.

## 5. UI at scale

`/tree` returns counts only; `/items` pages with server-side filters; the tree, Needs-your-check and flat search are virtualised; "Confirm all" confirms every
match server-side in chunks of 100 with a cursor. Unit-tested with a 2,000-row group rendering < 40 DOM rows.

## 6. Proof runs (what was actually run)

Synthetic pack: 2,001 files / 3.38 GB (`scale_pack`: 560 vector PDFs A4-A0, 40 long drawing sets of 30-60 pages, 40 scans, 12 PDFs of 52-98 MB, 300 DXF,
BOQ xlsx/csv/pdf, specs, docx, addenda, 100 duplicates, junk, 8 zips), mock provider, project `SCALE-SIM-2`.

* Upload: tab-close simulation at 700 files then resume (above); 2.46 GB sent in 331 s on resume.
* Kill mid-run: both pool children SIGKILLed while reading (848 routed, 1,111 waiting): the worker survived, reading continued, **2 files were re-read
  (attempts=2), none lost or duplicated**. A whole-container kill / restart was also exercised in an earlier run of the same pack (424 routed, container
  killed and started: 424 -> 461 and onward, no loss).
* End state of intake: 2,051 documents terminal (1,986 routed, 54 needs-your-check, 3 rejected, 8 zip parents), 2,043 distinct paths for 2,043 rows.
  Classes: drawing 1,015, specification 246, boq 186, clarification 88, contract 87, tender forms 87, correspondence 86, tender instructions 86,
  site investigation 85, addendum 60.
* Peak memory per container (docker stats, 3 s samples): ingest worker 1,417 MiB of 1.5 GiB, index worker 1,677 MiB of 2 GiB, backend 474 MiB of 1 GiB,
  vlm 357 MiB, email 230, quotation 220, convert 212, beat 143; unlimited: Postgres 2,442, SeaweedFS 1,933, Keycloak 498. Nothing was OOM-killed.
* Time: intake reading ran at about 40-60 files/min with 2 children (about 40 min for 2,051 files once uploaded). **The drawing pipeline did not finish**:
  with one index child, 114 of 898 drawings were `ready` (183 extracting, 601 queued) when the run was stopped, because the host ran out of memory
  (Claude Code reaped two background pollers). Total wall clock is therefore not a meaningful number (the sampler recorded 3.5 h including idle time).

Bugs the runs found and fixed (all with tests): CAD PDFs in pdfplumber (above); a stalled upload held a DB transaction and blocked backend reload (idle timeout);
copies registered in a later batch attached to another copy instead of the root and stayed pending (recursive release); rejected junk kept a pack
"uploading" for ever; the dispatcher's uuid parameter; an addendum routed before its drawing; index tasks starving intake (own queue).

## Not done / open (stated plainly)

* **Your crashed packs were NOT resumed with the real provider, and nothing was merged.** There are two: project `103` pack `661d42e3` (560 files, the 07:04
  crash) and project `102` pack `948b4c0f` (1,588 files, 2.7 GB, uploaded yesterday and stuck in processing). Both are **paused** (so nothing touches them) and
  every worker is stopped. The 1,588-file pack is fully uploaded and only needs reading; the 560-file one also needs the rest of the folder re-dropped.
  Resume = start the stack with your normal AI provider, press Resume on each pack. The real run will spend provider money (the 9 earlier calls cost $0.70, vision calls ~$0.08 each).
* Incident I caused and reversed: when I first started the workers they were on the mock provider and read 132 files of pack `948b4c0f` (44 classified by mock,
  38 parked as too large, 10 rejected). I reset the 44 mock-classified files to `received` (their classification rows deleted; the audit trail keeps the entries).
* e2e (mocked and real-backend) were not re-run after the UI changes: `intake-scale.spec.ts` is written, `tender-intake.spec.ts` / `ai-first-intake.spec.ts` were only
  adapted for the new `/tree` shape and will need UI-assertion updates.
* Unit (705), integration (313 + new) and API (107) suites passed separately before the last fixes; the last fixes were re-run on the intake files only.
