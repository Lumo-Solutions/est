from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aioboto3
from botocore.config import Config

from app.core.config import Settings, get_settings


def _session(settings: Settings) -> aioboto3.Session:
    return aioboto3.Session(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


@asynccontextmanager
async def s3_client(settings: Settings | None = None) -> AsyncIterator:
    settings = settings or get_settings()
    session = _session(settings)
    async with session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        config=Config(s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"}),
    ) as client:
        yield client


async def put_object_streaming(
    object_key: str, data: bytes, content_type: str | None, settings: Settings | None = None, *, bucket: str | None = None
) -> str:
    """Uploads bytes already buffered in memory (drawing files are capped at
    MAX_UPLOAD_SIZE_BYTES, so this is bounded) and returns the sha256 hex
    digest computed over the same bytes, for Drawing.sha256 dedup. `bucket`
    defaults to S3_BUCKET_DRAWINGS for backward compatibility with the
    Module B call sites; Module C passes S3_BUCKET_PROCUREMENT explicitly."""
    settings = settings or get_settings()
    digest = hashlib.sha256(data).hexdigest()
    async with s3_client(settings) as client:
        await client.put_object(
            Bucket=bucket or settings.s3_bucket_drawings,
            Key=object_key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
    return digest


class UploadAborted(Exception):
    """The stream ended in a way that must not leave an object behind (too big, or the digest did not match)."""


@dataclass(frozen=True, slots=True)
class StreamedObject:
    sha256: str
    size: int


async def put_object_from_stream(
    object_key: str,
    chunks: AsyncIterator[bytes],
    *,
    bucket: str,
    expected_sha256: str | None = None,
    max_bytes: int | None = None,
    part_bytes: int = 8 * 1024 * 1024,
    content_type: str = "application/octet-stream",
    settings: Settings | None = None,
) -> StreamedObject:
    """Streams a body straight to S3 without ever holding more than one part (`part_bytes`) in memory: the sha256
    is computed on the way through, a body up to one part is a single PUT, anything larger is a multipart upload.
    When `expected_sha256` is given the object only becomes visible if the digest matches (the multipart upload is
    completed after the check, a small body is put after it); a mismatch or an oversize body raises `UploadAborted`
    and nothing is left behind."""
    settings = settings or get_settings()
    digest = hashlib.sha256()
    size = 0
    buf = bytearray()
    upload_id: str | None = None
    parts: list[dict] = []
    async with s3_client(settings) as client:

        async def send_part(body: bytes) -> None:
            nonlocal upload_id
            if upload_id is None:
                created = await client.create_multipart_upload(Bucket=bucket, Key=object_key, ContentType=content_type)
                upload_id = created["UploadId"]
            number = len(parts) + 1
            resp = await client.upload_part(Bucket=bucket, Key=object_key, UploadId=upload_id, PartNumber=number, Body=body)
            parts.append({"ETag": resp["ETag"], "PartNumber": number})

        try:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise UploadAborted(f"the file is larger than the {max_bytes // (1024 * 1024)} MiB limit")
                digest.update(chunk)
                buf += chunk
                while len(buf) > part_bytes:  # more than one part's worth: this is a multipart upload
                    body = bytes(buf[:part_bytes])
                    del buf[:part_bytes]
                    await send_part(body)
            sha = digest.hexdigest()
            if expected_sha256 is not None and sha != expected_sha256:
                raise UploadAborted("the uploaded bytes do not match the registered sha256")
            if upload_id is None:
                await client.put_object(Bucket=bucket, Key=object_key, Body=bytes(buf), ContentType=content_type)
            else:
                if buf:
                    await send_part(bytes(buf))
                await client.complete_multipart_upload(
                    Bucket=bucket, Key=object_key, UploadId=upload_id, MultipartUpload={"Parts": parts}
                )
            return StreamedObject(sha256=sha, size=size)
        except BaseException:
            if upload_id is not None:
                try:
                    await client.abort_multipart_upload(Bucket=bucket, Key=object_key, UploadId=upload_id)
                except Exception:  # noqa: BLE001 -- best effort; the partial upload is invisible anyway
                    pass
            raise


async def object_exists(object_key: str, *, bucket: str, settings: Settings | None = None) -> bool:
    async with s3_client(settings or get_settings()) as client:
        try:
            await client.head_object(Bucket=bucket, Key=object_key)
            return True
        except Exception:  # noqa: BLE001 -- not found / forbidden both mean "not there for us"
            return False


async def get_object_bytes(object_key: str, settings: Settings | None = None, *, bucket: str | None = None) -> bytes:
    settings = settings or get_settings()
    async with s3_client(settings) as client:
        resp = await client.get_object(Bucket=bucket or settings.s3_bucket_drawings, Key=object_key)
        return await resp["Body"].read()


async def presign_get_url(
    object_key: str, expires_in: int = 300, settings: Settings | None = None, *, bucket: str | None = None
) -> str:
    """Signed against `s3_public_endpoint`, not `s3_endpoint` -- the client's
    configured endpoint_url is baked into both the returned URL's host AND
    the signature itself, so the URL must be built against the host it will
    actually be fetched from (a real browser), never rewritten after the
    fact. This is a pure, local computation (no network call), so a second
    client purely for signing costs nothing extra."""
    settings = settings or get_settings()
    session = _session(settings)
    async with session.client(
        "s3",
        endpoint_url=settings.s3_public_endpoint,
        config=Config(s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"}),
    ) as client:
        return await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket or settings.s3_bucket_drawings, "Key": object_key},
            ExpiresIn=expires_in,
        )


async def ensure_bucket(settings: Settings | None = None, *, bucket: str | None = None) -> None:
    settings = settings or get_settings()
    target = bucket or settings.s3_bucket_drawings
    async with s3_client(settings) as client:
        try:
            await client.head_bucket(Bucket=target)
        except Exception:  # noqa: BLE001 -- bucket-not-found is dialect-specific across S3 impls
            await client.create_bucket(Bucket=target)
