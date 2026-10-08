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
  with one index child, 114 of 898 drawings were `ready` (183 extracting, 601 queued) when the run was stopped. (First attributed to host memory; that was wrong, see section 7.) Total wall clock is therefore not a meaningful number (the sampler recorded 3.5 h including idle time).

Bugs the runs found and fixed (all with tests): CAD PDFs in pdfplumber (above); a stalled upload held a DB transaction and blocked backend reload (idle timeout);
copies registered in a later batch attached to another copy instead of the root and stayed pending (recursive release); rejected junk kept a pack
"uploading" for ever; the dispatcher's uuid parameter; an addendum routed before its drawing; index tasks starving intake (own queue).

## 7. Why the drawing run showed 114 of 898 (diagnosis, re-run on 8 Oct)

**The earlier explanation (host out of memory) was wrong.** The run was slow and was stopped while it was still working; it kept
going afterwards: the same project now holds 858 `ready`, 21 `failed` and 19 others (898 drawings). Its job table
(`extraction_jobs`) gives the time per stage:

| stage | jobs | avg | median | p95 | max | total job time |
|---|---|---|---|---|---|---|
| `index_sheets` (index worker, 1 child) | 858 | 31.3 s | 15.0 s | 111 s | 250 s | **7.5 h** |
| `embed_sheet` | 858 | 4.6 s | 3.1 s | 14 s | 42 s | 1.1 h |
| `extract_geometry` | 858 | 2.4 s | 1.2 s | 8 s | 15 s | 0.6 h |
| `extract_title_block` | 3,033 | 1.0 s | 0.8 s | 2.5 s | 21 s | 0.9 h |
| `finalize` | 858 | 13 ms | | | | |

**Cause, in order of weight**

1. **Throughput of one worker child.** Reading the pages of a drawing (`index_sheets`: text, objects, page renders) is CPU-bound
   (the index container sits at about 120 % CPU) and takes about 4 s per sheet for small sheets and up to 13 s per sheet for the
   3-8 sheet CAD plans. With concurrency 1, 898 drawings are 7.5-8 hours of work however the host behaves. Nothing was hung.
2. **Queue order made it look worse than it was.** `extract_geometry_measurements` is routed to the *same* `index` queue, and the
   queue is first-in-first-out within a priority. A drawing's geometry task is only sent when its `index_sheets` ends, so it goes
   to the back of the line, behind every `index_sheets` still waiting. All drawings get indexed first and are finished afterwards
   (breadth first): `ready` stays flat while `extracting` grows. Seen in the broker: the priority-6 queue held 101 `index_sheets`
   and 22 geometry tasks in arrival order. That is the "114 ready, 183 extracting, 601 queued" picture: the 114 were the drawings
   that went through before the backlog built up.
3. **Long drawing sets hit the 300 s limit** (39-55 pages) and fail with a time-out; each holds the one child for 5 minutes.
4. By design the auto-measure list uses the lowest priority (9), so its drawings finish after everything a person asked for.
5. Memory was not the limit (peaks below).

**Small reproduction** (mock AI provider, project `REPRO-1`, 320-file pack = 143 drawings, auto-measure ON for `roads_civil`,
then "Measure all" for the other seven disciplines, the path a lead estimator uses):

* Upload and reading of 320 files: about 8 minutes (7 files refused as junk). Intake created 143 drawings as `indexed` and started
  measuring only the 18 `roads_civil` ones: **auto-measure behaves as designed.**
* Index time per drawing, first 59 finished: **avg 37 s, median 28 s, max 203 s**. Drawings of 1-2 sheets average 7 s (4.2 s per
  sheet), of 3-8 sheets 66 s (13 s per sheet). Embedding 3.3 s, geometry 2.5 s, title block 0.8 s on average.
* The last drawing reached `ready` at 09:54 and **none did for the next 42 minutes** while 59 `index_sheets` ran (at the end:
  ready 7, extracting 51, queued 82, failed 3): the index backlog has to drain before geometry runs.
* Two long sets failed on the 300 s limit; their `error_message` is raw SQLAlchemy text instead of the "took longer than 300
  seconds" sentence, because the limit fired inside a flush (see "Open").
* **Peak memory** (docker stats, 3 s samples, whole run): index worker 1,258 MiB of 2 GiB, default worker 1,161 MiB of 1.5 GiB,
  backend 711 MiB, Postgres 2,333 MiB (unlimited), SeaweedFS 880 MiB, Keycloak 492, vlm 353, email 228, quotation 217, convert 205,
  beat 147. Nothing near a limit, nothing killed. The host had 3.8 GB free of 15.9 GB with the Docker VM capped at 7.7 GB.
* I stopped the run at 59 of 143 indexed (about 1 h 15 min in; the remaining 82 drawings / 420 sheets needed another hour or more
  and would have blocked the other specs on the shared workers), purged the repro's own index queue, deleted the `REPRO-1` project
  and reset the auto-measure list to none. The poll log is `docs/intake-scale/repro-poll.log`.

**What would fix it** (not done; your decision): (a) send a drawing's continuation (geometry, finalize) one priority step above its
own `index_sheets`, so a drawing finishes before the next one starts (depth first; `ready` then climbs steadily); (b) a second
index child (`INDEX_CONCURRENCY=2` needs about 1.3 GB more; set it only after sizing the Docker VM at 10 GB); (c) a higher soft
limit or a per-sheet budget for long sets. (a) is a few lines in `index_sheets` plus its priority tests.

## 8. Tests (8 Oct, one suite at a time, final state)

| suite | result |
|---|---|
| backend unit | 719 passed |
| backend integration | 337 passed (one earlier run had 1 failure, a load-related flake of `test_every_readable_file...`; it passed 3 of 3 repeats and in the clean full re-run) |
| backend API | 113 passed |
| frontend tsc -b / build | clean / built |
| vitest | 307 passed (41 files) |
| oxlint | 0 errors (warnings that were already there) |
| mocked Playwright | 5 passed |
| real-backend, `--workers=1`, each alone | intake-scale 2 passed (+1 skipped: the opt-in 2,000-file test, needs `SCALE_PROJECT`); ai-first-intake 4; tender-intake 4; ai-walkthrough 2; project-pages 8; layout-widths 1 |

The tests for the new behaviour exist and pass: no auto-measure on intake (`test_intake_routes_drawings_as_indexed_and_starts_no_measurement`),
the auto-measure list at the lowest priority, on demand when opened (idempotent, bumps a queued bulk request), bulk measure by
discipline / type with audit and lead-only (`test_measure_all_picks_by_discipline...`, `test_bulk_measure_is_lead_only...`), priority
order against a real Redis broker (`test_celery_runs_the_urgent_message_first...`), cost estimate and confirm (`test_the_estimate_is_...`,
`test_a_pack_on_an_external_provider_does_not_start_until...`, API `test_cost_estimate_and_confirmation_are_lead_only`), cached-token
pricing (`test_ai_pricing_qwen.py`, API usage view).

**Failures found and how they were fixed**

* Product bug (fixed, with a regression test): **a later revision read before its predecessor never got `revision_of`.** Files are
  read in parallel now, so Rev B could be classified before Rev A, and the flag was only looked for among files already read. A file
  now also flags the later revisions that were read before it (`tender_intake_processing._flag_revision`).
* Specs that predated the new behaviour, updated. tender-intake: the upload list shows a few rows, macro workbooks are refused at
  registration and have no row, the folder list is virtualised, search / bulk wording changed, "Save" matched two buttons.
  ai-walkthrough and tender-intake: drawings are measured on request. ai-first-intake: poll for a consistent tree snapshot.
  intake-scale: wait on the server's uploaded count, not the panel's (which also counts refused files).

## Open (stated plainly)

* **Merged to master locally, not pushed.** MFA is left off (`DEV_DISABLE_MFA=true`, as in `deploy/.env`).
* **The two crashed packs are still not resumed**: project `102` pack `948b4c0f` (1,588 files) and project `103` pack `661d42e3`
  (560 files) are `paused` and untouched (checked after the stack started and after the tests). Resuming means pressing Resume
  with the real provider; the new flow shows the cost estimate and asks for confirmation first.
* The drawing-queue ordering of section 7 is diagnosed, not changed.
* **Bug, not fixed:** when the 300 s limit fires inside a database flush, the drawing's `error_message` is SQLAlchemy's "transaction
  has been rolled back ..." text (or a bare `CancelledError`) instead of the intended "took longer than 300 seconds" sentence,
  because `_record_index_failure` only recognises a bare `SoftTimeLimitExceeded`.
* The 2,000-file Playwright test is opt-in (`SCALE_PROJECT`) and was not run; the synthetic proof run of section 6 stands.
* Postgres (peak 2.3 GB) and SeaweedFS are the largest consumers; size the Docker VM at 10 GB (the `.wslconfig` is documented in
  `docs/deploy-deltas.md`, not applied on this machine).
* Earlier incident, reversed: a few mock-provider reads of pack `948b4c0f`; those 44 files were reset to `received`.
