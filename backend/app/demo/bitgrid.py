"""A tiny optical code so a *fixture* image can carry its own recorded answer for the mock AI provider.

The mock provider cannot OCR a scanned page. The synthetic scanned-BOQ fixture therefore prints, along the
top edge, a grid of black/white blocks that encodes the JSON of the rows the page shows (zlib-compressed).
The mock decodes it from the rendered page PNG and "reads" the page exactly as a recorded provider response
would. Blocks are large (6 px) so the code survives PDF rendering and resampling. A real provider ignores it
(it is just a few printed marks); production code never imports this module.
"""

from __future__ import annotations

import io
import json
import zlib
from typing import Any

from PIL import Image

BLOCK = 6
MARGIN = 6
LENGTH_BITS = 32


def _bits_of(data: bytes) -> list[int]:
    return [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]


def encode(payload: Any, width: int) -> Image.Image:
    """Returns a grayscale strip (white background) of the given pixel width encoding `payload` (JSON-able)."""
    raw = zlib.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"), 9)
    bits = [int(b) for b in format(len(raw), f"0{LENGTH_BITS}b")] + _bits_of(raw)
    per_row = (width - 2 * MARGIN) // BLOCK
    rows = 1 + (len(bits) + per_row - 1) // per_row  # row 0 is the calibration row
    img = Image.new("L", (width, MARGIN * 2 + rows * BLOCK), 255)
    px = img.load()

    def block(col: int, row: int, black: bool) -> None:
        if not black:
            return
        x0, y0 = MARGIN + col * BLOCK, MARGIN + row * BLOCK
        for x in range(x0, x0 + BLOCK):
            for y in range(y0, y0 + BLOCK):
                px[x, y] = 0

    for col in range(per_row):
        block(col, 0, col % 2 == 0)  # calibration: 1,0,1,0,...
    for i, bit in enumerate(bits):
        block(i % per_row, 1 + i // per_row, bool(bit))
    return img


def decode(png_or_image: bytes | Image.Image, *, top: int = 0) -> Any | None:
    """Reads a payload back from an image (or PNG bytes) whose code starts `top` pixels from the top edge.
    Returns None if there is no valid code (a real, unmarked page)."""
    img = Image.open(io.BytesIO(png_or_image)) if isinstance(png_or_image, bytes) else png_or_image
    img = img.convert("L")
    width, height = img.size
    per_row = (width - 2 * MARGIN) // BLOCK
    px = img.load()

    def bit(col: int, row: int) -> int | None:
        x, y = MARGIN + col * BLOCK + BLOCK // 2, top + MARGIN + row * BLOCK + BLOCK // 2
        if x >= width or y >= height:
            return None
        return 1 if px[x, y] < 128 else 0

    # calibration row must alternate 1,0,1,0
    for col in range(min(per_row, 24)):
        if bit(col, 0) != (1 if col % 2 == 0 else 0):
            return None

    def read(n_bits: int, start: int) -> list[int] | None:
        out = []
        for i in range(start, start + n_bits):
            b = bit(i % per_row, 1 + i // per_row)
            if b is None:
                return None
            out.append(b)
        return out

    head = read(LENGTH_BITS, 0)
    if head is None:
        return None
    length = int("".join(map(str, head)), 2)
    if length <= 0 or length > 200_000:
        return None
    body = read(length * 8, LENGTH_BITS)
    if body is None:
        return None
    data = bytes(int("".join(map(str, body[i : i + 8])), 2) for i in range(0, len(body), 8))
    try:
        return json.loads(zlib.decompress(data))
    except (zlib.error, ValueError):
        return None
