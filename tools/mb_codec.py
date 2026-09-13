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
    # **\uc804\uac01\uacf5\ubc31(U+3000)\uc740 \ub354 \uc548 \uc4f4\ub2e4** (2026-09-13).
    #   0x3FF \uc5d0 \ubc15\uc544 \ub480\ub294\ub370, \ud55c\uae00 \ubc30\uc815\uc774 \uadf8 \uce78\uc744 \u300c\ube48 \uce78\u300d\uc73c\ub85c \ubcf4\uace0 `\uac1a` \uc744 \ub123\uc5b4
    #   \ud654\uba74\uc5d0 `\uc644\uc131\ub3c4\u3000` \uac00 **`\uc644\uc131\ub3c4\uac1a`** \uc73c\ub85c \ub5b4\ub2e4. \uc804\uac01\uacf5\ubc31\uc740 \uc77c\ubc18 \uacf5\ubc31 \ub450 \uac1c\uc640
    #   **\ubc14\uc774\ud2b8\ub3c4 \ud53d\uc140\ub3c4 \uac19\uc73c\ubbc0\ub85c**(2 B / 16 px) \uc5ed\ubb38\uc5d0\uc11c\ub294 \ub450 \uce78\uc73c\ub85c \uc4f4\ub2e4.
    #   \uc5ec\uae30\uc11c \ube7c \ub450\uba74 \uc2e4\uc218\ub85c `\u3000` \ub97c \ub123\uc5c8\uc744 \ub54c KeyError \ub85c \uc2dc\ub044\ub7fd\uac8c \uc8fd\ub294\ub2e4.
    p = ROOT / "translation" / "glyph_alloc.json"
    if p.exists():
        for ch, h in json.loads(p.read_text(encoding="utf-8"))["hangul"].items():
            enc[ch] = int(h, 16)
    # **\uce78\uc774 \uacb9\uce58\uba74 \uba48\ucd98\ub2e4.** \ud55c\uae00\ub07c\ub9ac(\uadf8\ub9ac\uace0 \uacf5\ubc31\uacfc) \uac19\uc740 \uae00\ub9ac\ud504 ID \ub97c \uc4f0\uba74
    #   \ud558\ub098\uac00 \ub2e4\ub978 \ud558\ub098\ub85c \ud654\uba74\uc5d0 \ub72c\ub2e4. charmap \uc758 \uc6d0\ubb38 \uae00\uc790\uc640 \uacb9\uce58\ub294 \uac83\uc740
    #   \uc815\uc0c1\uc774\ub2e4 \u2014 \ud55c\uae00 \ubc30\uc815\uc774 \uadf8 \uce78\uc744 **\uac00\uc838\uac00\ub294** \uac83\uc774\uae30 \ub54c\ubb38\uc774\ub2e4.
    _own: dict[int, str] = {}
    for _ch, _g in enc.items():
        if _ch == " " or "\uac00" <= _ch <= "\ud7a3":
            if _g in _own and _own[_g] != _ch:
                raise ValueError(
                    f"\uae00\ub9ac\ud504 0x{_g:03X} \uac00 {_own[_g]!r} \uc640 {_ch!r} \uc5d0 \uacb9\uccd0 \ubc30\uc815\ub410\ub2e4")
            _own[_g] = _ch
    # **\uc6d0\ud310\uc774 \uc544\uc9c1 \uc4f0\ub294 \uce78\uc740 \ubabb \uac00\uc838\uac04\ub2e4.** \u300c\ube48 \uce78\u300d \uc9d1\uacc4\uac00 \uc774\uac78 \uc548 \uc138\uc11c
    #   2026-09-13 \uc5d0 `\uac1a` \uc744 0x3FF(\uc804\uac01\uacf5\ubc31)\uc5d0 \ub123\uc5c8\uace0, \uc6d0\ud310 D_NAMES \uac00 \uadf8 \uae00\ub9ac\ud504\ub97c
    #   47\uacf3\uc5d0\uc11c \uc4f0\ub294 \ubc14\ub78c\uc5d0 \ubbf8\ubc88\uc5ed \uc904\uc5d0 \u300c\uac1a\u300d\uc774 \ubc15\ud614\ub2e4(\uc2e4\uae30: \u300c\uc644\uc131\ub3c4\uac1a\u300d).
    #   0x100 \uc740 \ud654\uba74\uc5d0\uc11c \uc624\ub978\ucabd \uc808\ubc18\uc774 \uc548 \uadf8\ub824\uc9c4\ub2e4(\uc6d0\uc778 \ubbf8\uc0c1).
    _FORBIDDEN = {
        0x3FF: "\uc6d0\ud310 \uc804\uac01\uacf5\ubc31 (\uc6d0\ud310 D_NAMES \uac00 47\uacf3\uc5d0\uc11c \uc4f4\ub2e4)",
        0x100: "\ud654\uba74\uc5d0\uc11c \uae00\ub9ac\ud504 \uc624\ub978\ucabd \uc808\ubc18\uc774 \uc548 \uadf8\ub824\uc9c4\ub2e4",
    }
    if p.exists():
        _pres = {int(_k, 16): _v for _k, _v
                 in json.loads(p.read_text(encoding="utf-8"))
                 .get("preserved_ids", {}).items()}
        for _ch, _g in enc.items():
            if not ("\uac00" <= _ch <= "\ud7a3"):
                continue
            if _g in _FORBIDDEN:
                raise ValueError(f"\ud55c\uae00 {_ch!r} \uc744 \uae00\ub9ac\ud504 0x{_g:03X} \uc5d0 \ubc30\uc815\ud588\ub2e4 "
                                 f"\u2014 {_FORBIDDEN[_g]}")
            if _g in _pres:
                raise ValueError(f"\ud55c\uae00 {_ch!r} \uc744 \ubcf4\uc874 \uae00\ub9ac\ud504 0x{_g:03X}"
                                 f"({_pres[_g]}) \uc5d0 \ubc30\uc815\ud588\ub2e4")
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
