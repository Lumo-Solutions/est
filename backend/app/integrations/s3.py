from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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


async def get_object_bytes(object_key: str, settings: Settings | None = None, *, bucket: str | None = None) -> bytes:
    settings = settings or get_settings()
    async with s3_client(settings) as client:
        resp = await client.get_object(Bucket=bucket or settings.s3_bucket_drawings, Key=object_key)
        return await resp["Body"].read()


async def presign_get_url(
    object_key: str, expires_in: int = 300, settings: Settings | None = None, *, bucket: str | None = None
) -> str:
    settings = settings or get_settings()
    async with s3_client(settings) as client:
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
