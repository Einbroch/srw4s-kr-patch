#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 마크업 <-> 바이트 변환.

마크업은 '글자 + 인라인 제어 표식'이다:
    {N} 줄바꿈 F6 · {P} 페이지 F7 · {A} FA
    {8:xx} {9:xx} {E:xx}  1바이트 인수
    {8:xx} {9:xx} {C:xx} {E:xx}  1바이트 · {B:xxxx} {D:xxxx}  2바이트
역문은 원문과 **같은 표식을 같은 개수로** 가져야 한다 — 제어 토큰이 빠지면 게임이 멈춘다
(D_NAMES에서 F8 수치삽입점과 FB selector를 삼켜 실기 프리즈를 만든 적이 있다).
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from text_codec import glyph_bytes          # noqa: E402
from span_classify import charmap           # noqa: E402

OP = {"N": 0xF6, "P": 0xF7, "8": 0xF8, "9": 0xF9, "A": 0xFA,
      "B": 0xFB, "C": 0xFC, "D": 0xFD, "E": 0xFE}
TOKEN = re.compile(r"\{([NP89ABCDE])(?::([0-9A-Fa-f]+))?\}")
# 문자표가 단사가 아니고(같은 글자에 ID 둘: 父=3D9/3E6 등) 여러 글자로 풀리는 글리프도 있다
# (HP=0x0EE 하나). 그런 글리프는 문자로 적으면 왕복이 깨지므로 ID를 그대로 적는다.
GLYPH = re.compile(r"\{G:([0-9A-Fa-f]{1,3})\}")


def build_encoder() -> dict[str, int]:
    cm = charmap()
    enc: dict[str, int] = {}
    for gid, ch in sorted(cm.items()):
        if ch and ch not in enc:
            enc[ch] = gid
    enc[" "] = 0x000
    enc["\u3000"] = 0x3FF
    p = ROOT / "translation" / "glyph_alloc.json"
    if p.exists():
        for ch, h in json.loads(p.read_text(encoding="utf-8"))["hangul"].items():
            enc[ch] = int(h, 16)
    return enc


def encode(markup: str, enc: dict[str, int]) -> bytes:
    out = bytearray()
    i = 0
    while i < len(markup):
        g = GLYPH.match(markup, i)
        if g:
            out += glyph_bytes(int(g.group(1), 16))
            i = g.end()
            continue
        m = TOKEN.match(markup, i)
        if m:
            out.append(OP[m.group(1)])
            if m.group(2):
                out += bytes.fromhex(m.group(2))
            i = m.end()
            continue
        ch = markup[i]
        if ch not in enc:
            raise KeyError(ch)
        out += glyph_bytes(enc[ch])
        i += 1
    out.append(0xFF)
    return bytes(out)


def markers(markup: str) -> list[str]:
    return [m.group(0) for m in TOKEN.finditer(markup)]


def ambiguous_glyphs() -> set:
    """문자로 적으면 왕복이 깨지는 글리프 ID 집합."""
    cm = charmap()
    cm[0x000] = " "
    first: dict[str, int] = {}
    bad = set()
    for gid, ch in sorted(cm.items()):
        if not ch:
            continue
        if len(ch) != 1:
            bad.add(gid)            # 여러 글자로 풀리는 글리프 (HP 등)
            continue
        if ch in first:
            bad.add(gid)            # 같은 글자의 두 번째 ID
        else:
            first[ch] = gid
    return bad
