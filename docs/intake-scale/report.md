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

(Sections 1-6 are filled in as the work is done.)
