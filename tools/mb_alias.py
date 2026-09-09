#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""레코드 **안쪽**을 가리키는 별칭을 역문의 같은 자리로 옮긴다.

게임은 같은 줄을 화자 이름만 떼고(또는 둘째 문단부터) 재사용한다. 그 재사용은
레코드 시작이 아니라 **안쪽 바이트**를 가리키는 슬롯으로 표현된다.

원문에서 별칭이 `「`·`{P}`·`{N}`·기타 제어토큰 **바로 뒤**에 붙어 있으면, 역문에서
같은 순번의 같은 토큰 뒤가 대응 자리다. 문장 도중을 가리키는 별칭은 옮길 근거가
없으므로 건드리지 않는다(원문 접미사 사본이 그대로 남는다).

`{N}` 은 재조판이 개수를 바꿀 수 있으므로 **원문과 역문의 개수가 같을 때만** 옮긴다.
"""
from __future__ import annotations
import re

TOK = re.compile(r"\{[^}]*\}")


def chunks(s: str, enc: dict[str, int]) -> list[tuple[str, int]]:
    """문자열을 (토막, 시작 바이트) 목록으로. 토막은 한 글자 또는 제어토큰 하나."""
    from mb_codec import encode
    out: list[tuple[str, int]] = []
    i = b = 0
    while i < len(s):
        m = TOK.match(s, i)
        t = m.group(0) if m else s[i]
        out.append((t, b))
        b += len(encode(t, enc)) - 1        # 종결자 제외
        i += len(t)
    return out


def _anchor(tok: str) -> str | None:
    """이 토막이 별칭을 걸 만한 구조 경계인가."""
    if tok == "「":
        return "「"
    if tok.startswith("{"):
        return tok
    return None


def ko_alias_offsets(jp: str, ko: str, enc: dict[str, int]) -> dict[int, int]:
    """원문 바이트 오프셋 -> 역문 바이트 오프셋. 옮길 수 있는 자리만 담는다."""
    try:
        jc, kc = chunks(jp, enc), chunks(ko, enc)
    except KeyError:
        return {}
    # 역문 쪽 토막을 종류별 순번으로 색인
    kpos: dict[str, list[int]] = {}
    for i, (t, _b) in enumerate(kc):
        a = _anchor(t)
        if a:
            kpos.setdefault(a, []).append(i)
    out: dict[int, int] = {}
    seen: dict[str, int] = {}
    for i, (t, b) in enumerate(jc):
        a = _anchor(t)
        if not a:
            continue
        n = seen.get(a, 0)
        seen[a] = n + 1
        cand = kpos.get(a) or []
        if a.startswith("{N") and len(cand) != sum(1 for x, _ in jc if x.startswith("{N")):
            continue                        # 재조판으로 줄바꿈 개수가 달라졌다
        if n >= len(cand):
            continue
        j = cand[n]
        # 2026-09-06 **앵커 자신의 자리를 잇는 것은 되돌렸다.**
        #   `out[b] = kc[j][1]` 을 넣었더니 매핑이 51 -> 81 로 늘었지만, 실기에서
        #   **게임 시작부터 대사가 깨졌다** — 메시지 종단을 넘어가 다음 메시지까지
        #   한 줄로 이어 붙고 사이에 잡글자가 끼었다(`…마라!」QGQ카즈야「…`).
        #   앵커 자리를 가리키는 별칭이 전부 "화자 이름을 뗀 재사용"인 것은 아니고,
        #   그중에는 옮기면 안 되는 것이 섞여 있다. 근거 없이 일괄로 이으면 안 된다.
        if i + 1 >= len(jc) or j + 1 >= len(kc):
            continue
        out[jc[i + 1][1]] = kc[j + 1][1]    # 토큰 **뒤** 자리끼리 잇는다
        # 앵커 뒤로 **양쪽 토막이 글자까지 같은 동안** 계속 이어 준다.
        # `{P}{E:1F}Ⅱ화자「...`처럼 페이지 머리의 장식 글자가 원문·역문에 똑같이
        # 남아 있으면, 그 뒤(=화자 이름 시작)까지가 대응 자리다. 글자가 갈리는
        # 순간 멈추므로 문장 도중으로는 넘어가지 않는다.
        p, q = i + 1, j + 1
        while p + 1 < len(jc) and q + 1 < len(kc) and jc[p][0] == kc[q][0]:
            out[jc[p + 1][1]] = kc[q + 1][1]
            p += 1
            q += 1
    return out
