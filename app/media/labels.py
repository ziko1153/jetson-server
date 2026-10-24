"""Bitmap labels for virtual cameras. This FFmpeg build has no drawtext filter."""

from __future__ import annotations

from pathlib import Path

GLYPHS = {
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "11100"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
}


def write_label(path: Path, text: str, accent: tuple[int, int, int] = (255, 255, 255), scale: int = 5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_label(text, accent, scale))


def render_label(text: str, accent: tuple[int, int, int] = (255, 255, 255), scale: int = 5) -> bytes:
    rows = _rows(text.upper())
    padding = 8
    stripe = 10
    width = stripe + padding + (len(rows[0]) * scale) + padding
    height = padding + (len(rows) * scale) + padding
    if width % 2:
        width += 1
    if height % 2:
        height += 1
    black = bytes((0, 0, 0))
    white = bytes((255, 255, 255))
    accent_pixel = bytes(accent)
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            if x < stripe:
                pixels.extend(accent_pixel)
                continue
            glyph_x = x - stripe - padding
            glyph_y = y - padding
            if glyph_x < 0 or glyph_y < 0:
                pixels.extend(black)
                continue
            column = glyph_x // scale
            row = glyph_y // scale
            if row < len(rows) and column < len(rows[row]) and rows[row][column] == "1":
                pixels.extend(white)
            else:
                pixels.extend(black)
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + bytes(pixels)


def render_clock_frame(
    width: int,
    height: int,
    camera_id: str,
    clock_text: str,
    accent: tuple[int, int, int],
    sweep: int,
) -> bytes:
    colors = _bar_colors(accent)
    bar_width = max(width // len(colors), 1)
    rows = []
    for _y in range(height):
        row = bytearray()
        for index, color in enumerate(colors):
            span = bar_width if index < len(colors) - 1 else width - bar_width * (len(colors) - 1)
            row.extend(color * span)
        column = sweep % width
        row[column * 3 : column * 3 + 3] = b"\xff\xff\xff"
        rows.append(row)
    _stamp(rows, width, camera_id, 24, 28, 5)
    clock_scale = 8 if width >= 480 else 5
    clock_w, clock_h = _text_size(clock_text, clock_scale)
    _stamp(rows, width, clock_text, max(0, (width - clock_w) // 2), max(0, (height - clock_h) // 2), clock_scale)
    return b"".join(rows)


def _bar_colors(accent: tuple[int, int, int]) -> list[bytes]:
    colors = []
    for index in range(8):
        factor = 0.35 + (0.65 * index / 7)
        colors.append(bytes(max(0, min(255, int(channel * factor))) for channel in accent))
    return colors


def _text_size(text: str, scale: int) -> tuple[int, int]:
    glyph_rows = _rows(text)
    return len(glyph_rows[0]) * scale, len(glyph_rows) * scale


def _stamp(rows: list[bytearray], width: int, text: str, x: int, y: int, scale: int) -> None:
    glyph_rows = _rows(text)
    text_w = len(glyph_rows[0]) * scale
    text_h = len(glyph_rows) * scale
    pad = 8
    height = len(rows)
    for py in range(y - pad, y + text_h + pad):
        if py < 0 or py >= height:
            continue
        start = max(0, x - pad)
        end = min(width, x + text_w + pad)
        rows[py][start * 3 : end * 3] = b"\x00\x00\x00" * (end - start)
    for gy, glyph in enumerate(glyph_rows):
        for gx, bit in enumerate(glyph):
            if bit != "1":
                continue
            for sy in range(scale):
                py = y + gy * scale + sy
                if py < 0 or py >= height:
                    continue
                for sx in range(scale):
                    px = x + gx * scale + sx
                    if 0 <= px < width:
                        offset = px * 3
                        rows[py][offset : offset + 3] = b"\xff\xff\xff"


def _rows(text: str) -> list[str]:
    glyphs = []
    for char in text:
        glyph = GLYPHS.get(char)
        if glyph is None:
            raise ValueError(f"label cannot include {char!r}")
        glyphs.append(glyph)
    gap = "0"
    rows = []
    for row_index in range(7):
        pieces = [glyph[row_index] for glyph in glyphs]
        rows.append(gap.join(pieces))
    return rows
