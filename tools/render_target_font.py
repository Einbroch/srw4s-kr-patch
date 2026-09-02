#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the MAP font descriptor's resident glyph regions for visual QA."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
STAY = ROOT / "_work" / "extract" / "DAT" / "STAYDAT.BIN"
OUTPUT = ROOT / "_work" / "analysis" / "font_descriptor"


def render_low(data: bytes, start: int, count: int, columns: int, scale: int) -> Image.Image:
    rows = (count + columns - 1) // columns
    image = Image.new("1", (columns * 8, rows * 16), 1)
    pixels = image.load()
    for glyph in range(count):
        cell_x = (glyph % columns) * 8
        cell_y = (glyph // columns) * 16
        raw = data[start + glyph * 16 : start + (glyph + 1) * 16]
        for y, value in enumerate(raw):
            for x in range(8):
                pixels[cell_x + x, cell_y + y] = 0 if value & (0x80 >> x) else 1
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def render_wide(data: bytes, start: int, count: int, columns: int, scale: int) -> Image.Image:
    rows = (count + columns - 1) // columns
    image = Image.new("1", (columns * 16, rows * 16), 1)
    pixels = image.load()
    for glyph in range(count):
        cell_x = (glyph % columns) * 16
        cell_y = (glyph // columns) * 16
        raw = data[start + glyph * 32 : start + (glyph + 1) * 32]
        for y in range(16):
            for half in range(2):
                value = raw[y + half * 16]
                for bit in range(8):
                    x = half * 8 + bit
                    pixels[cell_x + x, cell_y + y] = 0 if value & (0x80 >> bit) else 1
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def glyph_bitmap(data: bytes, glyph: int) -> Image.Image:
    image = Image.new("1", (16, 16), 1)
    pixels = image.load()
    if glyph < 0x100:
        raw = data[0x36838 + glyph * 16 : 0x36838 + (glyph + 1) * 16]
        for y, value in enumerate(raw):
            for bit in range(8):
                pixels[4 + bit, y] = 0 if value & (0x80 >> bit) else 1
    else:
        base = 0x37838 if glyph < 0x500 else 0x3F838
        relative = glyph - (0x100 if glyph < 0x500 else 0x500)
        raw = data[base + relative * 32 : base + (relative + 1) * 32]
        for y in range(16):
            for half in range(2):
                value = raw[y + half * 16]
                for bit in range(8):
                    pixels[half * 8 + bit, y] = 0 if value & (0x80 >> bit) else 1
    return image


def render_review_sheet(data: bytes, glyphs: list[int]) -> Image.Image:
    columns = 4
    cell_width, cell_height = 160, 170
    rows = (len(glyphs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, glyph in enumerate(glyphs):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        bitmap = glyph_bitmap(data, glyph).resize((128, 128), Image.Resampling.NEAREST)
        sheet.paste(bitmap.convert("RGB"), (x + 16, y + 24))
        draw.text((x + 8, y + 5), f"glyph {glyph:03X}", fill="black")
    return sheet


def main() -> None:
    data = STAY.read_bytes()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Descriptor at RAM 0x80056800 / STAY +0x36800 points to three
    # contiguous glyph banks.  The fourth pointer marks their end.
    render_low(data, 0x36838, 0x100, 16, 3).save(OUTPUT / "glyph_000_0ff.png")
    render_wide(data, 0x37838, 0x400, 32, 2).save(OUTPUT / "glyph_100_4ff.png")
    render_wide(data, 0x3F838, 0x200, 32, 2).save(OUTPUT / "glyph_500_6ff.png")
    review_glyphs = [
        0x00C,
        0x0EA,
        0x0ED,
        0x100,
        0x348,
        0x3FF,
        0x44C,
        0x515,
        0x562,
        0x596,
        0x5C2,
        0x5F7,
        0x646,
        0x649,
        0x652,
        0x667,
        0x698,
        0x6FE,
    ]
    render_review_sheet(data, review_glyphs).save(OUTPUT / "unresolved_glyphs.png")
    print(f"output={OUTPUT}")


if __name__ == "__main__":
    main()
