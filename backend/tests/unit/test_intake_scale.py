"""Intake at scale, unit level (docs/intake-scale/report.md): the streaming upload never buffers more than a part and
only publishes an object whose digest matches; the AI breaker is shared between worker processes; files that are too
big or have too many pages are parked instead of read; PDF renders are capped so an A0 sheet cannot allocate hundreds
of MB. No database, no network."""

from __future__ import annotations

import hashlib
import io
import uuid

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.integrations import s3 as s3mod
from app.services import tender_intake_processing as processing

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)
SETTINGS = Settings(**_REQUIRED)  # type: ignore[arg-type]
CTX = RequestContext(tenant_id=uuid.uuid4(), user_id=None, sub=None, roles=frozenset(), is_system=True)


# ------------------------------------------------------------------ streaming upload
class FakeS3:
    """Records what the streaming upload asks S3 to do, and the largest body it was ever handed."""

    def __init__(self) -> None:
        self.puts: list[bytes] = []
        self.parts: list[bytes] = []
        self.created = 0
        self.completed: list[list[dict]] = []
        self.aborted = 0

    async def put_object(self, *, Bucket, Key, Body, ContentType):
        self.puts.append(Body)

    async def create_multipart_upload(self, *, Bucket, Key, ContentType):
        self.created += 1
        return {"UploadId": "u1"}

    async def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        self.parts.append(Body)
        return {"ETag": f"e{PartNumber}"}

    async def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        self.completed.append(MultipartUpload["Parts"])

    async def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.aborted += 1


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3()

    class _Ctx:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(s3mod, "s3_client", lambda settings=None: _Ctx())
    return client


async def chunks(data: bytes, size: int):
    for i in range(0, len(data), size):
        yield data[i : i + size]


async def test_a_small_body_is_one_put_and_the_digest_is_returned(fake_s3):
    data = b"x" * 1000
    out = await s3mod.put_object_from_stream("k", chunks(data, 100), bucket="b", expected_sha256=hashlib.sha256(data).hexdigest(), part_bytes=4096, settings=SETTINGS)
    assert out.sha256 == hashlib.sha256(data).hexdigest() and out.size == 1000
    assert fake_s3.puts == [data] and fake_s3.created == 0


async def test_a_big_body_goes_up_in_parts_and_no_part_exceeds_the_part_size(fake_s3):
    data = bytes(range(256)) * 100  # 25,600 bytes
    out = await s3mod.put_object_from_stream("k", chunks(data, 777), bucket="b", expected_sha256=hashlib.sha256(data).hexdigest(), part_bytes=10_000, settings=SETTINGS)
    assert out.size == len(data)
    assert fake_s3.created == 1 and fake_s3.puts == [] and fake_s3.aborted == 0
    assert max(len(p) for p in fake_s3.parts) <= 10_000
    assert b"".join(fake_s3.parts) == data
    assert [p["PartNumber"] for p in fake_s3.completed[0]] == [1, 2, 3]


async def test_exactly_one_part_of_bytes_is_still_a_single_put(fake_s3):
    data = b"a" * 4096
    await s3mod.put_object_from_stream("k", chunks(data, 1024), bucket="b", part_bytes=4096, settings=SETTINGS)
    assert fake_s3.puts == [data] and fake_s3.created == 0


async def test_a_wrong_digest_leaves_nothing_behind_for_a_small_and_for_a_multipart_body(fake_s3):
    with pytest.raises(s3mod.UploadAborted):
        await s3mod.put_object_from_stream("k", chunks(b"abc", 1), bucket="b", expected_sha256="0" * 64, settings=SETTINGS)
    assert fake_s3.puts == []
    big = b"z" * 30_000
    with pytest.raises(s3mod.UploadAborted):
        await s3mod.put_object_from_stream("k", chunks(big, 1000), bucket="b", expected_sha256="0" * 64, part_bytes=10_000, settings=SETTINGS)
    assert fake_s3.completed == [] and fake_s3.aborted == 1  # parts were sent, but the upload is aborted, never completed


async def test_an_oversize_body_is_cut_off_as_soon_as_it_exceeds_the_limit(fake_s3):
    seen = 0

    async def endless():
        nonlocal seen
        while True:
            seen += 1
            yield b"y" * 1024

    with pytest.raises(s3mod.UploadAborted):
        await s3mod.put_object_from_stream("k", endless(), bucket="b", max_bytes=5 * 1024, part_bytes=2048, settings=SETTINGS)
    assert seen <= 7 and fake_s3.completed == []  # it stopped reading, it did not drain the stream


async def test_a_failing_source_aborts_the_multipart_upload(fake_s3):
    async def broken():
        yield b"q" * 6000
        raise ConnectionResetError("client went away")

    with pytest.raises(ConnectionResetError):
        await s3mod.put_object_from_stream("k", broken(), bucket="b", part_bytes=4096, settings=SETTINGS)
    assert fake_s3.aborted == 1 and fake_s3.completed == []


# ------------------------------------------------------------------ the shared AI breaker
class FakeRedis:
    store: dict[str, bytes] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value.encode() if isinstance(value, str) else value

    async def incr(self, key):
        self.store[key] = str(int(self.store.get(key, b"0")) + 1).encode()
        return int(self.store[key])

    async def expire(self, key, seconds):
        return True

    async def delete(self, key):
        self.store.pop(key, None)

    async def aclose(self):
        return None


@pytest.fixture
def fake_redis(monkeypatch):
    import redis.asyncio as redis

    FakeRedis.store = {}
    monkeypatch.setattr(redis, "from_url", lambda url: FakeRedis())
    return FakeRedis


async def test_a_failure_streak_counted_across_runs_opens_the_breaker_for_every_worker(fake_redis):
    tenant = uuid.uuid4()
    n = SETTINGS.intake_ai_max_consecutive_failures
    for _ in range(n):
        run = processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS))  # one run per file, as in the worker
        await run.record_failure("the AI step failed")
    other_worker = processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS))
    await other_worker.sync_in()
    assert other_worker.stopped_reason == "the AI step failed"


async def test_a_success_resets_the_shared_streak(fake_redis):
    tenant = uuid.uuid4()
    for _ in range(SETTINGS.intake_ai_max_consecutive_failures - 1):
        await processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS)).record_failure("boom")
    await processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS)).record_success()
    await processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS)).record_failure("boom")
    fresh = processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS))
    await fresh.sync_in()
    assert fresh.stopped_reason is None


async def test_a_hard_stop_is_published_at_once(fake_redis):
    tenant = uuid.uuid4()
    await processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS)).record_hard_stop("AI is not configured")
    other = processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", tenant, SETTINGS))
    await other.sync_in()
    assert other.stopped_reason == "AI is not configured"


async def test_the_breaker_is_per_tenant(fake_redis):
    await processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", uuid.uuid4(), SETTINGS)).record_hard_stop("off")
    other_tenant = processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", uuid.uuid4(), SETTINGS))
    await other_tenant.sync_in()
    assert other_tenant.stopped_reason is None


async def test_without_redis_the_run_keeps_working_on_its_own_state(monkeypatch):
    import redis.asyncio as redis

    def down(url):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(redis, "from_url", down)
    run = processing.AiRun(SETTINGS, processing.SharedBreaker("redis://x", uuid.uuid4(), SETTINGS))
    await run.sync_in()
    for _ in range(SETTINGS.intake_ai_max_consecutive_failures):
        await run.record_failure("nope")
    assert run.stopped_reason == "nope"  # the local breaker still trips


# ------------------------------------------------------------------ size and page gates
def _snap(size: int, name: str = "Big.pdf") -> processing.DocSnapshot:
    return processing.DocSnapshot(uuid.uuid4(), uuid.uuid4(), name, "pdf", None, "b", "k", False, size)


def _pdf_with_pages(n: int) -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


async def test_a_file_over_the_processing_limit_is_never_downloaded(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("an oversize file must not be downloaded")

    monkeypatch.setattr(processing, "get_object_bytes", never)
    run = processing.AiRun(SETTINGS)
    prepared = await processing.prepare_document(CTX, _snap(SETTINGS.intake_max_process_bytes + 1), run)
    assert prepared.too_large and "MB" in prepared.too_large and prepared.content is None and prepared.model is None
    assert run.calls == 0  # and no AI call was made for it


async def test_a_pdf_with_too_many_pages_is_parked_not_rejected(monkeypatch):
    data = _pdf_with_pages(5)

    async def get(*a, **k):
        return data

    monkeypatch.setattr(processing, "get_object_bytes", get)
    small = Settings(INTAKE_MAX_PDF_PAGES=3, **_REQUIRED)  # type: ignore[arg-type]
    prepared = await processing.prepare_document(CTX, _snap(len(data)), processing.AiRun(small))
    assert prepared.too_large and "5 pages" in prepared.too_large


async def test_a_file_under_the_limits_is_still_read(monkeypatch):
    data = _pdf_with_pages(1)

    async def get(*a, **k):
        return data

    monkeypatch.setattr(processing, "get_object_bytes", get)
    run = processing.AiRun(SETTINGS)
    run.stop("AI is off for this test")  # rules only: no provider in a unit test
    prepared = await processing.prepare_document(CTX, _snap(len(data), "a.pdf"), run)
    assert prepared.too_large is None and prepared.content is not None


def test_the_limits_have_sane_defaults():
    s = SETTINGS
    assert s.intake_max_files_per_pack == 3000
    assert s.intake_max_process_bytes < s.intake_max_file_size_bytes  # big files can be uploaded and parked
    assert s.intake_task_soft_limit_s < s.intake_task_hard_limit_s
    assert s.intake_stuck_after_s > s.intake_task_hard_limit_s  # a healthy task never looks stuck
    assert s.celery_max_memory_per_child_kb > 0 and s.celery_max_tasks_per_child > 0


# ------------------------------------------------------------------ renders are capped
def _big_page_pdf(w_pt: int, h_pt: int) -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=w_pt, height=h_pt)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _png_size(png: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        return img.size


def test_an_a0_page_is_rendered_under_the_pixel_cap_by_default():
    from app.takeoff.pdf import render_page_png

    a0 = _big_page_pdf(2384, 3370)  # points; at 150 dpi that would be 4967 x 7021 px
    w, h = _png_size(render_page_png(a0, 0, dpi=150, max_side_px=2000))
    assert max(w, h) <= 2001 and abs(w / h - 2384 / 3370) < 0.01


def test_an_ordinary_page_is_rendered_exactly_as_before(monkeypatch):
    from app.takeoff.pdf import render_page_png

    monkeypatch.setattr("app.core.config.get_settings", lambda: SETTINGS)

    a4 = _big_page_pdf(595, 842)
    uncapped = render_page_png(a4, 0, dpi=150, max_side_px=None)
    assert render_page_png(a4, 0, dpi=150) == uncapped  # under the default cap: identical bytes (the AI cache keys on them)


def test_the_title_block_corner_can_be_rendered_without_the_full_page():
    from app.takeoff.pdf import render_title_block_png

    huge = _big_page_pdf(5000, 3500)
    w, h = _png_size(render_title_block_png(huge, 0, dpi=170, max_side_px=1800))
    assert max(w, h) <= 1801  # ~35% x 30% of the page, capped: never a 12,000 px bitmap


def test_build_images_uses_the_corner_render_only_for_very_large_pages(monkeypatch):
    from app.intake import classifier
    from app.intake.extract import DocContent
    from app.takeoff import pdf as pdf_mod

    calls = {"full": [], "corner": 0}
    real_render = pdf_mod.render_page_png

    def spy_render(data, idx, dpi=150, **kw):
        calls["full"].append(dpi)
        return real_render(data, idx, dpi=dpi, **kw)

    def spy_corner(*a, **k):
        calls["corner"] += 1
        return pdf_mod.render_title_block_png.__wrapped__(*a, **k) if hasattr(pdf_mod.render_title_block_png, "__wrapped__") else b"png"

    monkeypatch.setattr(pdf_mod, "render_page_png", spy_render)
    monkeypatch.setattr(pdf_mod, "render_title_block_png", spy_corner)
    content = DocContent(filename="a.pdf", ext="pdf", sniffed="pdf", title_block_text="DRAWING NO C-1", pages=1)
    classifier.build_images("pdf", _big_page_pdf(595, 842), content)  # A4: the old path, a 170 dpi full-page render
    assert 170 in calls["full"] and calls["corner"] == 0
    calls["full"].clear()
    classifier.build_images("pdf", _big_page_pdf(5000, 3500), content)  # far above A1: never a 170 dpi full-page render
    assert 170 not in calls["full"] and calls["corner"] == 1
