#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 대사창 조판 규약.

실측으로 확정한 값이다.
  * 저뱅크 글리프(1바이트, ID 0x00-0xEF)는 **8x16 반각** — stride 16 으로 완벽히 그려진다.
  * 중/고뱅크 글리프(2바이트)는 16x16 전각.
  * 한 줄은 **296px**. 넘기면 넘친 만큼이 같은 줄 맨 앞으로 감겨 앞부분을 덮어쓴다.
    실기로 눈금을 맞췄다 — 320px 은 16px, 312px 은 8px, **304px 도 8px** 넘쳤다
    (정확히 304px 인 줄에서 마지막 `」` 가 잘렸다). 296px 이 실제 한도다.
  * 한 페이지는 **3줄**. 원본도 3줄을 넘지 않는다.
  * `{B:xxxx}` 는 이름/값 삽입이라 폭이 실행 중에 정해진다 — **5전각(80px)** 으로 예산을 잡는다.
    기본 애칭은 3자(`그레이`)지만 사용자가 더 길게 지을 수 있다. 원본의 이름표식 있는 줄도
    문자 부분이 99.7% 224px 이하라(=304-80) 이 예산과 맞는다.
"""
from __future__ import annotations
import re

# 2026-09-06 **296 -> 288.** 원문 줄 폭을 전수로 재니 절벽이 분명하다 — 순수 글자
# 줄은 288px 를 절대 안 넘고, 296px 인 원문은 딱 두 줄뿐인데 **둘 다 `{B:}`**(이름
# 삽입)를 갖는다. 그 80px 추정 때문에 부풀려 재진 것이지 실제 폭이 아니다.
# 296 으로 두는 동안 역문 250줄이 그 틈으로 새어 나가 화면에서 넘쳤다
# (사용자 실기: 가라리아 대사 MB:1800E, 296px 줄이 감겨 앞을 덮어썼다).
LINE_PX = 296 - 8
PAGE_LINES = 3

# **판정용은 296 그대로 둔다.** wide_window() 는 "원문 자신이 규약을 넘느냐"로
# 넓은 창을 가려내는데, 여기까지 288 로 조이면 `{B:}` 때문에 296 으로 재진 평범한
# 대사 61개가 넓은 창(9줄)으로 잘못 넘어가 역문이 부풀 자리가 생긴다.
# 재는 기준(296)과 지키는 기준(288)은 다른 값이다.
DETECT_PX = 296

# 유닛/캐릭터 도감은 대사창이 아니라 **넓은 창**에 그려진다.
# 창이 넓어 보이는 건 **줄 수**(최대 9줄)이지 줄 폭이 아니다 — 폭은 대사창과 비슷하다.
#
# 2026-08-31 실기: 도감 설명이 한 줄 걸러 잘려 나왔다. 원인은 이 상수를 잘못 잰 것.
# 처음에 원문 줄 폭을 "일본어 글자는 전부 16px"으로 세어 440px이 나왔는데,
# **반각 가나(1바이트)는 8px**이다. atom_px 로 다시 재니:
#     줄 폭   99.7% <= 288px, 최댓값 312px(이름표식 포함)
#     줄 수   페이지당 최대 9줄
# 440px로 채운 역문은 화면 폭을 넘어가 잘렸다. 재는 함수를 바꿔 재지 말 것 —
# 폭은 반드시 atom_px(=저뱅크 8px / 중고뱅크 16px)로 잰다.
WIDE_PX = 288
WIDE_LINES = 9
NAME_PX = 80
HALF, FULL = 8, 16
ATOM = re.compile(r"\{[^}]*\}|.", re.S)


_HALF = None


def _half() -> set:
    """반각(8x16) 문자 집합 = 저뱅크(글리프 ID < 0xF0) 에 있는 글자들.
    폭은 뱅크만으로 정해지므로 인코더(=글리프 배정)에 기대지 않는다 —
    아직 배정 안 된 새 한글이 있어도 조판을 계산할 수 있어야 한다."""
    global _HALF
    if _HALF is None:
        from span_classify import charmap
        _HALF = {c for g, c in charmap().items() if c and g < 0xF0}
        _HALF.add(" ")
    return _HALF


def atom_px(a: str, enc) -> int:
    if a.startswith("{") and a.endswith("}"):
        if a in ("{N}", "{P}"):
            return 0
        if a.startswith("{B:"):
            # 인수가 4바이트면(형식 0C/08) 이름 삽입이 아니라 아무것도 안 그리는 제어다
            return 0 if len(a) > len("{B:XXXX}") else NAME_PX
        if a.startswith("{G:"):
            return FULL                      # 미매핑 글리프 = 전각 1자
        return 0                             # 나머지는 제어 토큰, 폭 없음
    return HALF if a in _half() else FULL


def atoms(markup: str) -> list[str]:
    return ATOM.findall(markup)


def layout(markup: str, enc) -> list[list[int]]:
    """[[줄폭...], ...] 페이지별 줄 폭(px)."""
    pg, ln, w = [], [], 0
    for a in atoms(markup):
        if a == "{P}":
            ln.append(w); pg.append(ln); ln = []; w = 0
        elif a == "{N}":
            ln.append(w); w = 0
        else:
            w += atom_px(a, enc)
    ln.append(w); pg.append(ln)
    return pg


# 「...」{N}화자「...」 — 한 레코드에 담긴 **두 갈래 응답**의 경계다(주인공 성별·기종에
# 따라 한쪽만 나온다). 조판이 이 자리를 지우면 두 대사가 한 줄로 붙고, 줄 수도
# **갈래마다** 따로 세야 한다 — 한 번에 한 갈래만 창에 뜨기 때문이다.
VARIANT = re.compile(r"(?<=」)\{N\}(?=(?:\{[^}]*\})*[^「」{]{0,12}「)")


def violations(markup: str, enc, line_px: int | None = None,
               page_lines: int | None = None):
    """(넘친 줄 [(페이지,줄,폭)], 줄 수 넘긴 페이지 [(페이지,줄수)])

    창마다 규약이 다르다 — 대사창 296px/3줄, 유닛 도감 440px/7줄.
    """
    line_px = LINE_PX if line_px is None else line_px
    page_lines = PAGE_LINES if page_lines is None else page_lines
    wide, deep = [], []
    pi = 0
    for page in markup.split("{P}"):
        for part in VARIANT.split(page):        # 갈래마다 따로 센다
            lines = layout(part, enc)[0]
            if len(lines) > page_lines:
                deep.append((pi, len(lines)))
            for li, w in enumerate(lines):
                if w > line_px:
                    wide.append((pi, li, w))
        pi += 1
    return wide, deep


def _breaks(seq: list[str]) -> dict[int, bool]:
    """끊을 수 있는 자리 {인덱스: 그 자리 원소를 버릴지}.

    (1) 띄어쓰기 앞 — 그 공백은 버린다. 줄 끝 공백은 폭을 차지하지 않는 셈이 된다.
    (2) `...` **뒤** — 버리지 않는다. 한국어 역문은 말줄임표 뒤에 공백을 두지 않아서,
        이걸 끊을 자리로 안 보면 긴 덩어리가 통째로 다음 줄로 밀린다.
        점 하나하나 뒤가 아니라 **연속된 점이 끝난 자리**여야 한다(`후.. .` 사고).
        점이 **하나뿐이면 끊지 않는다** — `라.기어스`, `윌.윕스` 처럼 이름 속의 점이라
        거기서 끊으면 다시 합칠 때 `라. 기어스` 로 벌어진다.
    """
    ok = {}
    for i, a in enumerate(seq):
        if i == 0:
            continue
        if a == " ":
            ok[i] = True
        elif (seq[i - 1] == "." and a != "."
                and i >= 2 and seq[i - 2] == "."):
            ok[i] = False
    return ok


def _split_line(line: str, enc, line_px: int | None = None) -> list[str]:
    line_px = LINE_PX if line_px is None else line_px
    seq = atoms(line)
    w = [atom_px(a, enc) for a in seq]
    if sum(w) <= line_px:
        return ["".join(seq)]
    ok = _breaks(seq)
    out, start, cur, last = [], 0, 0, -1
    for i in range(len(seq)):
        if i in ok and i > start:
            last = i
        if cur + w[i] > line_px and i > start:
            if last > start:
                out.append("".join(seq[start:last]))
                start = last + (1 if ok[last] else 0)
            else:
                out.append("".join(seq[start:i]))
                start = i
            cur = sum(w[start:i])
            last = -1
            for k in range(start + 1, i):
                if k in ok:
                    last = k
        cur += w[i]
    if start < len(seq):
        out.append("".join(seq[start:]))
    return [x for x in out if x]


def rewrap(markup: str, enc, line_px: int | None = None) -> str:
    """**넘치는 줄만 쪼갠다.** 줄을 합치지는 않는다 —
    `{N}` 자리를 지우면 한국어는 단어가 붙어 버린다("모르는당신을").
    기존 `{N}`/`{P}` 는 사람이 정한 끊는 자리이므로 그대로 둔다."""
    return "{P}".join(
        "{N}".join(x for line in page.split("{N}")
                   for x in _split_line(line, enc, line_px))
        for page in markup.split("{P}")
    )


def wide_window(jp: str, enc) -> bool:
    """원문 자신이 대사창 규약을 넘으면 그 레코드는 넓은 창에 그려진다."""
    for page in jp.split("{P}"):
        segs = page.split("{N}")
        if len(segs) > PAGE_LINES:
            return True
        for seg in segs:
            if sum(atom_px(a, enc) for a in atoms(seg)) > DETECT_PX:
                return True
    return False


# 넓은 창을 쓰는 표 — 유닛/파일럿 도감이다. 표를 눈으로 확인해 고정한다.
# 레코드 하나만 보고 판정하면 같은 표 안에서 3줄에 들어가는 짧은 설명이
# 대사창 규약으로 잘못 잡힌다(H50 에서 37건이 그렇게 걸렸다).
WIDE_TABLES = {"H48", "H49", "H50", "H51"}


def budget(jp: str, enc, owners=()) -> tuple[int, int]:
    """그 레코드가 지켜야 할 (줄 폭, 줄 수)."""
    if any(o.split(":")[0] in WIDE_TABLES for o in owners):
        return (WIDE_PX, WIDE_LINES)
    return (WIDE_PX, WIDE_LINES) if wide_window(jp, enc) else (LINE_PX, PAGE_LINES)
