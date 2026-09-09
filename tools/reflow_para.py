#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""문단 단위 재조판 — 쪽 안의 줄을 **전부 이어 붙여** 다시 나눈다.

`mb_layout.rewrap` 은 **줄 하나씩** 다시 나눈다. 그래서 첫 줄만 넘치면 그 줄만
쪼개고 뒤 줄은 그대로 둬서 쪽당 줄 수를 넘긴다(296px 한 줄 -> 256+32 + 나머지 = 4줄).
한도를 288px 로 조였을 때 걸린 133건 중 **129건이 이 경우**였다 — 내용은 3x288 안에
들어가는데 나눌 자리를 못 찾은 것뿐이라, 문구를 줄일 이유가 없었다.

규칙
  * 쪽(`{P}`) 경계는 절대 안 넘는다. 쪽 안에서만 다시 흘린다.
  * **갈래 경계(`VARIANT`)도 안 넘는다.** `」{N}화자「` 의 `{N}` 은 조판이 아니라
    두 갈래 응답을 가르는 **구조**다 — 지우면 두 대사가 한 덩어리로 붙는다.
    (2026-09-06 실측: 이 처리를 빼먹어 MB:708CC 의 마사키 두 대사가 붙었고
     `verify_mb_ledger` 의 variant_page 가 잡았다.)
  * 줄바꿈 자리는 **공백으로** 바꿔 잇는다 — 안 그러면 단어가 붙는다
    ([[reflow-korean-spacing]]).
  * 다시 나누는 자리는 **공백에서만**. 단어 안을 쪼개지 않는다.
  * 제어 토큰(`{...}`)은 한 덩어리로 취급해 쪼개지지 않게 한다.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mb_layout import atoms, atom_px, VARIANT   # noqa: E402


def width(s: str, enc) -> int:
    return sum(atom_px(a, enc) for a in atoms(s))


def _reflow_seg(page: str, enc, cap: int) -> str:
    """갈래 하나를 이어 붙였다가 공백에서만 다시 나눈다."""
    flat = " ".join(seg.strip() for seg in page.split("{N}") if seg.strip())
    words, out, cur = flat.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w) if cur else w
        if width(cand, enc) <= cap:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return "{N}".join(out)


def reflow_page(page: str, enc, cap: int) -> str:
    return "{N}".join(_reflow_seg(v, enc, cap) for v in VARIANT.split(page))


def reflow(markup: str, enc, cap: int) -> str:
    return "{P}".join(reflow_page(p, enc, cap) for p in markup.split("{P}"))


def fits(markup: str, enc, cap: int, lines: int) -> bool:
    for p in markup.split("{P}"):
        rows = p.split("{N}")
        if len(rows) > lines:
            return False
        for r in rows:
            if width(r.rstrip(" "), enc) > cap:
                return False
    return True
