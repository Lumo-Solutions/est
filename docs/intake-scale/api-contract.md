# Intake at scale: API contract (what the UI builds against)

Backend: `backend/app/schemas/tender_intake.py` (the source of truth for field names) and
`backend/app/api/v1/routes/tender_intake.py`. All paths are under `/api/v1`. Auth/CSRF are the existing cookie
session + `X-CSRF-Token` header (use `frontend/src/lib/api.ts`; a raw `fetch` for the file PUT must send the same
CSRF header and `credentials: 'same-origin'`; look at how `api.ts` builds its headers).

## Upload (resumable)

1. **Hash** every file in the browser (SHA-256, streamed in chunks: never read a whole big file into memory).
2. **Register** in batches of at most 500 files:
   `POST /projects/{projectId}/tender-packages/register`
   ```json
   { "package_id": null, "new_package": false, "label": "Transmittal 2026-10-01", "transmittal_ref": null,
     "received_date": "2026-10-01", "total_files": 1600,
     "files": [{ "path": "Drawings/Roads/R-101.pdf", "size": 1234567, "sha256": "<64 hex>" }] }
   ```
   * Send `total_files` (the whole drop's count) on every call. The server rejects a drop over `INTAKE_MAX_FILES_PER_PACK`
     (3000) with a 422 whose `detail` is a ready-to-show message.
   * Without `package_id` the server **resumes the project's unfinished upload** (package status `uploading`) or starts a
     new package. Pass the `package_id` from the first response on the following batches. `new_package: true` forces a
     new one.
   * Response `RegisterPackageOut`: `{ package_id, status, resumed, expected_count, files: [{ path, sha256,
     document_id, state, upload, reason }] }`.
     * `state`: `pending` (needs bytes, or waits for another file with the same bytes) | `uploaded` (already on the server: skip) |
       `rejected` (not accepted, `reason` says why, show it; `document_id` is null).
     * `upload: true` means **send this file's bytes**. `upload: false` with `state: pending` is a file whose bytes are
       identical to another file in the drop: nothing to send, it completes when that other file does.
3. **Upload** each file with `upload: true`, 3-5 at a time, one request per file:
   `PUT /tender-packages/{packageId}/documents/{documentId}/content` with the **raw file as the body** (`fetch(url,
   { method: 'PUT', body: file })`, not FormData), `Content-Type: application/octet-stream`.
   * Response `UploadResult`: `{ document_id, state, package_status, registered, uploaded, expected_count }`.
   * 409 when the pack is paused ("This pack is paused...") or cancelled: stop the loop and show the message.
   * 422 when the digest does not match or the file is over the limit: that file failed, show the `detail`.
   * Retry other failures (network, 5xx) with backoff, a few times, then report that file as failed and carry on.
4. **Resume** = drop the same folder again: hash, register (the server answers `uploaded` for what it has), upload only
   the `upload: true` rest. Nothing is stored in the browser.

Progress "X / N": use the server's own counters from `UploadResult` (`uploaded` of `expected_count`), plus the
registered files that came back `uploaded`/`rejected` before any upload.

## Project page data (counts and paged lists; no list of all files any more)

* `GET /projects/{projectId}/tender-documents/tree` -> `TreeOut`:
  `{ summary, groups, folders, packages }` (**no `items`**).
  * `summary` (`TreeSummary`): `total, by_display_status, by_class, needs_check, in_progress, pending_upload,
    drawings_total, drawings_ready, boq_documents: [{id, name}], first_drawing_id, addenda, packages_processing,
    auto_accept_min, ai_available, ai_message`. `total` excludes files that have not arrived yet (`pending_upload`).
  * `groups`: `[{ doc_class, discipline, drawing_type, count }]`: counts of the "by document type" tree
    (class -> (drawings only) discipline -> drawing type). `null` = not set. Roll up by summing.
  * `folders`: `[{ folder, count }]`: files per upload folder, directly in it (`''` = top level). Build the folder tree
    client-side and roll counts up.
  * `packages`: `[{ id, label, status, created_at, expected_count, registered, uploaded, waiting, pending_upload }]`
    with `status` one of `uploading | processing | ready | failed | paused | cancelled`.
* `GET /projects/{projectId}/tender-documents/items` -> `{ items: TreeItem[], total, limit, offset }`. Query params
  (all optional): `package_id, doc_class, discipline, drawing_type, display_status, decided_by, flag, folder,
  include_subfolders, has_class, exclude_flags (repeat the param: `exclude_flags=conflict&exclude_flags=injection_suspected`), q,
  limit (<=500, default 100), offset`.
  * `doc_class | discipline | drawing_type` accept the literal `none` for "not set".
  * `folder=''` is the top level; `folder=A/B` is exactly that folder; add `include_subfolders=true` for its subtree.
  * `display_status`: `queued | reading | classified | extracting | ready | needs_check | failed | excluded`
    (`TreeItem` is unchanged from before, incl. `display_status`, `status_reason`).
  * Stable order (created_at, name, id). A group's files = the same filter the group's count came from.

## Bulk actions (server-side, every matching file)

Both take a `DocFilter` (same field names as the query params above, plus `exclude_flags: string[]`,
`has_class: bool`) in `filter`, **instead of** `document_ids`, and work in chunks (`INTAKE_BULK_CHUNK`, default 100):
the response carries `next_cursor`; call again with `cursor: <next_cursor>` until it is `null`.

* `POST /projects/{projectId}/tender-documents/bulk-confirm` body `{ "filter": {...}, "cursor": null }`
  -> `{ confirmed, failed, skipped, results, matched, next_cursor }` (`matched` = how many matched when the first call
  started, use it for "Confirmed X of Y").
  "Confirm all" in Needs your check = `filter: { display_status: "needs_check", has_class: true,
  exclude_flags: ["conflict", "injection_suspected"] }` (the two excluded flags need a one-by-one look).
* `POST /projects/{projectId}/tender-documents/bulk-reclassify` body `{ "filter": {...}, "doc_class": "...",
  "sub_type": null, "drawing_type": null, "note": null, "confirm": true, "cursor": null }` -> same response.
* The explicit `document_ids` forms still work (<= 1000 ids).

## Pack controls (lead_estimator and above; audited)

`POST /tender-packages/{packageId}/pause | resume | cancel` -> `{ package_id, status, cancelled_documents }`.
Pause: nothing new starts (uploads get 409, workers stop picking files). Resume: continues. Cancel: final; files not yet
read are excluded ("pack cancelled"), anything already classified stays. 409 for a state that does not allow it.

## Files that are "too large"

A file over the automatic-reading limit (or with too many pages, or one that took too long) arrives as a document with
`status: proposed`, `doc_class: null`, `flags: ["too_large"]`, `display_status: needs_check` and
`status_reason: "Too large to read automatically: ... Choose its class yourself."`. It has **no proposed class**, so
"Confirm" must not be offered for it, only "Change" (pick a class).

## Statuses

Document `status` gains `pending_upload` (registered, bytes not here yet; never listed by `/items`). Package `status` gains
`uploading`, `paused`, `cancelled`.
