#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFC 한글패치의 글리프 -> 음절 표를 비트맵 최근접 대조로 만든다.

SFC판과 PS1판은 **같은 글꼴을 공유한다**(일본판 SFC ROM 안에 PS1 STAYDAT 와 바이트가 같은
low/mid/high 뱅크가 있다: 0x2e8000 / 0x2e0000 / 0x224000). 한글패치는 mid/high 를 한글로
덮었고, 그 글꼴은 Galmuri9 계열이다(기준 글리프 2개에서 512비트 중 4비트 차 — 버전 차이).

정확 일치가 아니므로 **최근접 + 여유 판정**으로 고른다:
  1등 거리가 임계 이하이고, 2등과 충분히 벌어질 때만 채택한다.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BDF = Path("D:/Games/Kor Patch/CLude/폰트/Galmuri-v2.24.29/Galmuri9.bdf")
KROM = ROOT / "reference/sfc-kor/Dai-4-ji Super Robot Taisen (Korea) (Rev 1) v1.01.sfc"
JROM = ROOT / "reference/sfc-kor/Dai-4-ji Super Robot Taisen (Japan) (Rev 1).sfc"
MID, HIGH = 0x2E0000, 0x224000
DX, DY = 1, 4
MAX_D, MARGIN = 12, 4          # 1등 거리 <= 12 이고 2등과 4비트 이상 차이


def glyph_off(g: int) -> int:
    return MID + (g - 0x100) * 32 if g < 0x500 else HIGH + (g - 0x500) * 32


def load_bdf(p: Path) -> dict[str, tuple]:
    t = p.read_text(encoding="latin-1")
    out = {}
    for m in re.finditer(r"STARTCHAR[^\n]*\nENCODING (-?\d+)\n(.*?)\nBITMAP\n(.*?)\nENDCHAR", t, re.S):
        code = int(m.group(1))
        if not (0xAC00 <= code <= 0xD7A3):
            continue
        bb = re.search(r"BBX (-?\d+) (-?\d+) (-?\d+) (-?\d+)", m.group(2))
        w, h, ox, oy = map(int, bb.groups())
        rows = []
        for line in m.group(3).strip().split("\n"):
            v, nb = int(line, 16), len(line) * 4
            rows.append([(v >> (nb - 1 - x)) & 1 for x in range(w)])
        out[chr(code)] = (w, h, rows)
    return out


def to_bits(glyph) -> np.ndarray:
    w, h, rows = glyph
    grid = np.zeros((16, 16), np.uint8)
    for y in range(h):
        for x in range(w):
            X, Y = x + DX, y + DY
            if 0 <= X < 16 and 0 <= Y < 16:
                grid[Y, X] = rows[y][x]
    return grid.reshape(-1)


def raw_bits(b: bytes) -> np.ndarray:
    g = np.zeros((16, 16), np.uint8)
    for y in range(16):
        for x in range(16):
            g[y, x] = (b[(0 if x < 8 else 16) + y] >> (7 - (x & 7))) & 1
    return g.reshape(-1)


def main() -> int:
    k, j = KROM.read_bytes(), JROM.read_bytes()
    bdf = load_bdf(BDF)
    syl = sorted(bdf)
    ref = np.stack([to_bits(bdf[c]) for c in syl]).astype(np.int8)

    changed = [g for g in range(0x100, 0x700)
               if k[glyph_off(g):glyph_off(g) + 32] != j[glyph_off(g):glyph_off(g) + 32]]
    tgt = np.stack([raw_bits(k[glyph_off(g):glyph_off(g) + 32]) for g in changed]).astype(np.int8)

    # 해밍 거리 = XOR 합
    d = (tgt[:, None, :] ^ ref[None, :, :]).sum(2)
    order = np.argsort(d, axis=1)
    best, second = d[np.arange(len(changed)), order[:, 0]], d[np.arange(len(changed)), order[:, 1]]

    out, weak = {}, []
    for i, g in enumerate(changed):
        if best[i] <= MAX_D and second[i] - best[i] >= MARGIN:
            out[g] = syl[order[i, 0]]
        else:
            weak.append((g, syl[order[i, 0]], int(best[i]), int(second[i])))
    print(f"바뀐 글리프 {len(changed)} / 확정 {len(out)} / 보류 {len(weak)}")
    print("  보류 예시:", [(hex(g), c, b, s) for g, c, b, s in weak[:10]])
    dst = ROOT / "build" / "sfc_glyph_map.json"
    dst.write_text(json.dumps({f"0x{g:03X}": c for g, c in sorted(out.items())},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", dst.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
