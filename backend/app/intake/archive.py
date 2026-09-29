"""Safe zip expansion for tender packs.

Never uses ``extractall`` and never turns a member name into a filesystem
path: names are validated and kept as text (``archive_path``). Any hostile
property of the archive (bomb ratio, too many entries, encrypted members,
traversal names, too-deep nesting) rejects the archive as a whole with a
reason; a clean archive yields its files, with nested archives expanded up
to the configured depth (default 2).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from app.core.enums import AttachmentSafetyStatus

_ZIP_MAGIC = b"PK\x03\x04"
_DRIVE = re.compile(r"^[A-Za-z]:")
_SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_entries: int = 1_000
    max_entry_bytes: int = 60 * 1024 * 1024
    max_total_bytes: int = 500 * 1024 * 1024
    max_ratio: int = 100
    max_depth: int = 2

    @classmethod
    def from_settings(cls, settings) -> "ArchiveLimits":
        return cls(
            max_entries=settings.intake_zip_max_entries,
            max_entry_bytes=settings.intake_max_file_size_bytes,
            max_total_bytes=settings.intake_zip_max_total_bytes,
            max_ratio=settings.intake_zip_max_ratio,
            max_depth=settings.intake_zip_max_depth,
        )


@dataclass(frozen=True, slots=True)
class ExpandedFile:
    path: str  # normalised posix path inside the archive, nested zips joined with "/"
    data: bytes


@dataclass(slots=True)
class ArchiveResult:
    files: list[ExpandedFile] = field(default_factory=list)
    # (status, reason) when the archive as a whole must be rejected; files is empty then.
    fatal: tuple[str, str] | None = None


class _Fatal(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def safe_member_path(name: str) -> str | None:
    """Normalised relative posix path, or None when the name is unsafe."""
    if "\x00" in name:
        return None
    path = name.replace("\\", "/")
    if path.startswith("/") or _DRIVE.match(path):
        return None
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _is_skipped(path: str) -> bool:
    parts = path.split("/")
    return parts[0] == "__MACOSX" or parts[-1].lower() in _SKIP_NAMES


class _Budget:
    def __init__(self, limits: ArchiveLimits) -> None:
        self.limits = limits
        self.entries = 0
        self.total = 0


def _expand(data: bytes, prefix: str, depth: int, budget: _Budget, out: list[ExpandedFile]) -> None:
    limits = budget.limits
    if depth > limits.max_depth:
        raise _Fatal(AttachmentSafetyStatus.REJECTED_ARCHIVE.value, f"archive nesting deeper than {limits.max_depth}")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _Fatal(AttachmentSafetyStatus.REJECTED_ARCHIVE.value, f"not a readable zip archive: {exc}") from exc
    with zf:
        infos = zf.infolist()
        # Header-declared checks first: reject before decompressing anything.
        for info in infos:
            if info.is_dir():
                continue
            budget.entries += 1
            if budget.entries > limits.max_entries:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value, f"more than {limits.max_entries} entries")
            if info.flag_bits & 0x1:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ENCRYPTED.value, "archive contains an encrypted member")
            if safe_member_path(info.filename) is None:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ARCHIVE.value, f"unsafe member path {info.filename!r}")
            if info.compress_size > 0 and info.file_size / info.compress_size > limits.max_ratio:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value, f"member {info.filename!r} compression ratio too high")
            if info.compress_size == 0 and info.file_size > 1024:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value, f"member {info.filename!r} has an implausible ratio")
            if info.file_size > limits.max_entry_bytes:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_SIZE.value, f"member {info.filename!r} exceeds the size limit")
            budget.total += info.file_size
            if budget.total > limits.max_total_bytes:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value, "total uncompressed size over the limit")

        for info in infos:
            if info.is_dir():
                continue
            path = safe_member_path(info.filename)
            assert path is not None  # validated above
            if _is_skipped(path):
                continue
            # Headers can lie: read with a hard cap instead of trusting file_size.
            with zf.open(info) as fh:
                body = fh.read(limits.max_entry_bytes + 1)
            if len(body) > limits.max_entry_bytes:
                raise _Fatal(AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value, f"member {info.filename!r} expands past the limit")
            full = f"{prefix}{path}"
            if body.startswith(_ZIP_MAGIC) and path.lower().endswith(".zip"):
                _expand(body, f"{full}/", depth + 1, budget, out)
            else:
                out.append(ExpandedFile(full, body))


def expand_zip(data: bytes, limits: ArchiveLimits) -> ArchiveResult:
    """Expand a top-level zip (depth 1). Never raises for hostile input."""
    result = ArchiveResult()
    try:
        _expand(data, "", 1, _Budget(limits), result.files)
    except _Fatal as exc:
        return ArchiveResult(files=[], fatal=(exc.status, exc.reason))
    return result
