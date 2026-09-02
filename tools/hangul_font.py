#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한글 16x16 글꼴 — Galmuri11 을 12px 로 래스터라이즈해 SRW4S 배치로 낸다.

**핵심: 저장 칸은 16x16 이지만 실제 글리프 상자는 11x12 다.**
  원본 16x16 글리프 1,536개를 전수 조사하면 최대 사용 열이 10인 것이 1,440개,
  11인 것이 34개, 12인 것이 1개다. 행은 2~13.
  즉 렌더러는 **한 글자를 12px 정도 전진**시키고, 열 11~15 는 다음 글자 자리다.
  16px 글꼴을 그대로 넣으면 오른쪽 3~4열이 다음 글자에 겹쳐 그려져
  화면에서 글자가 통째로 뭉개진다(2026-08-24 실기: 이것이 "글자 깨짐"의 진짜 원인).

그래서 12px 설계에 가까운 Galmuri11 을 12px 로 그린다 — 열 0~10, 행 3~13 에 앉고
획이 1px 라 원본 한자와 굵기가 같다. (Neo둥근모는 16px 설계라 11px 로 줄이면 획이 뭉개지고,
Galmuri11-Bold 는 2px 라 원본보다 굵다.)

SRW4S 16x16 글리프 배치 = **좌우 분리**
    byte[y]      -> y행의 x=0..7
    byte[16 + y] -> y행의 x=8..15
  각 바이트는 bit7 이 왼쪽 픽셀(MSB-first).
"""
from __future__ import annotations

import functools
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_TTF = Path(r"D:/Games/Kor Patch/CLude/폰트/Galmuri-v2.24.29/Galmuri11.ttf")
SIZE, DY = 12, 0
BOX_COL, BOX_ROW = 10, 13        # 원본 글리프가 쓰는 최대 열/행
GLYPH_BYTES = 32


@functools.lru_cache(maxsize=1)
def _font() -> ImageFont.FreeTypeFont:
    if not FONT_TTF.exists():
        raise SystemExit(f"글꼴 파일이 없다: {FONT_TTF}")
    return ImageFont.truetype(str(FONT_TTF), SIZE)


@functools.lru_cache(maxsize=4096)
def _raster(ch: str) -> tuple[tuple[int, ...], ...]:
    im = Image.new("1", (16, 16), 0)
    d = ImageDraw.Draw(im)
    d.fontmode = "1"                     # 안티앨리어싱 끔
    d.text((0, DY), ch, font=_font(), fill=1)
    return tuple(tuple(1 if im.getpixel((c, r)) else 0 for c in range(16))
                 for r in range(16))


def extent(rows) -> tuple[int, int]:
    """(최대 사용 열, 최대 사용 행). 빈 글리프면 (-1, -1)."""
    mc = mr = -1
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                mc, mr = max(mc, x), max(mr, y)
    return mc, mr


def to_target_layout(rows) -> bytes:
    left, right = bytearray(16), bytearray(16)
    for y in range(16):
        lv = rv = 0
        for x in range(8):
            lv = (lv << 1) | rows[y][x]
            rv = (rv << 1) | rows[y][8 + x]
        left[y], right[y] = lv, rv
    return bytes(left) + bytes(right)


class HangulFont:
    """음절 -> SRW4S 배치 32바이트."""

    def __contains__(self, ch: str) -> bool:
        mc, mr = extent(_raster(ch))
        return mc >= 0 and mc <= BOX_COL and mr <= BOX_ROW

    @property
    def syllables(self) -> list[str]:
        """상자 안에 그릴 수 있는 음절 전부."""
        return [c for c in (chr(x) for x in range(0xAC00, 0xD7A4)) if c in self]

    def glyph(self, ch: str) -> bytes:
        rows = _raster(ch)
        mc, mr = extent(rows)
        if mc < 0:
            raise KeyError(f"글꼴에 없는 문자: {ch!r}")
        if mc > BOX_COL or mr > BOX_ROW:
            raise SystemExit(
                f"{ch!r} 가 글리프 상자를 넘는다 (열 {mc} > {BOX_COL} 또는 행 {mr} > {BOX_ROW}) "
                f"— 넘치면 다음 글자에 겹쳐 그려진다")
        return to_target_layout(rows)


if __name__ == "__main__":
    f = HangulFont()
    for ch in "주인공설정":
        g = f.glyph(ch)
        print(ch)
        for y in range(16):
            print("  " + "".join(
                "#" if (g[(0 if x < 8 else 16) + y] >> (7 - (x & 7))) & 1 else "."
                for x in range(16)))
