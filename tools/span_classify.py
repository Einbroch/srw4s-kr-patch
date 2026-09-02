#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 레코드에서 **번역 대상 span**만 골라낸다.

S00/S01의 대부분은 산문이 아니라 창 그리기 스크립트다. 프레임 타일과 제어 토큰이
바이트의 다수를 차지하고, 실제로 번역할 라벨은 커서 위치 지정 토큰(`FC`/`FD`) 뒤에
붙는 글리프 런뿐이다. 도너도 같은 모델을 쓴다(`second_ui_scripts_overlay.json`의
`replacements`: record 안의 `[relative_start, relative_end)` span만 교체하고 나머지 바이트는
그대로 보존 — `structural_decoration_glyphs_preserved: true`).

여기서는 그 규칙을 우리 데이터에 적용해 span을 뽑고, 성장 계산의 분모를 만든다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from text_codec import parse_record                                   # noqa: E402
from decode_dnames import load_mapping, DEFAULT_MAP, TARGET_CHARACTER_OVERRIDES  # noqa: E402

POSITION_OPCODES = {0xFC, 0xFD}      # 커서 위치/출력 지정 — 라벨이 이 뒤에 온다
BREAK_OPCODES = {0xF6, 0xF7}         # 줄바꿈/페이지 — span은 이어질 수 있다

_MAP = None


def charmap():
    global _MAP
    if _MAP is None:
        rows = load_mapping(DEFAULT_MAP)
        m = {}
        for gid, row in rows.items():
            m[gid] = TARGET_CHARACTER_OVERRIDES.get(gid, row.get("character") or "")
        m.update({g: c for g, c in TARGET_CHARACTER_OVERRIDES.items()})
        _MAP = m
    return _MAP


JP = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")
LATIN = re.compile(r"[A-Za-z0-9]")


def spans(raw: bytes):
    """(byte_start, byte_end, text) 목록. byte 인덱스는 raw 안의 위치."""
    m = charmap()
    # dnames_sections의 raw는 **항상** 종단 FF를 뺀 형태다(text_end가 종단의 오프셋을
    # 돌려주므로). 마지막 바이트가 0xFF일 수 있으나 그것은 확장 글리프의 trail이거나
    # 제어 인수이지 종단이 아니다 — `endswith(FF)`로 판단하면 안 된다. 항상 붙인다.
    raw = raw + bytes([0xFF])
    # 2026-08-23: 예전에는 위치 지정 opcode 뒤에서만 글자를 모으는 `armed` 게이트가 있었다.
    # 그리기 DSL 피연산자를 텍스트로 오인하지 않으려는 의도였지만, **진짜 라벨을 조용히
    # 버렸다** — `資金`, `EXP順`, `射程が1増えます` 등이 스팬으로 만들어지지도 않아
    # 원문 그대로 화면에 남았다(실기 확인으로 발견). 이제 모든 글리프 런을 런으로 만들고
    # 걸러내는 일은 is_drawing/is_kana_grid/is_decoration/is_palette_row에게만 맡긴다.
    # 런 경계는 제어 토큰이 정하므로 게이트 제거로 기존 스팬의 (start,end)는 변하지 않는다.
    toks = parse_record(raw)
    out = []
    pos = 0
    cur = None          # [start, end, chars]
    for t in toks:
        size = len(t.raw)
        if t.kind == "glyph":
            ch = m.get(t.glyph_id, "")
            if cur is None:
                cur = [pos, pos + size, [ch]]
            else:
                cur[1] = pos + size
                cur[2].append(ch)
            pos += size
            continue
        # control / terminator
        if cur is not None:
            out.append((cur[0], cur[1], "".join(cur[2])))
            cur = None
        pos += size
    if cur is not None:
        out.append((cur[0], cur[1], "".join(cur[2])))
    # 잡음 제거: 일본어/라틴 글자가 하나도 없는 런은 버린다
    keep = []
    for a, b, txt in out:
        if JP.search(txt) or (LATIN.search(txt) and len(txt.strip()) >= 2):
            keep.append((a, b, txt))
    return keep


if __name__ == "__main__":
    import csv
    from analyze_structures import dnames_sections
    data = (ROOT / "extract" / "DAT" / "D_NAMES.BIN").read_bytes()
    secs = {s["section"]: s for s in dnames_sections(data) if s["start"] is not None}
    which = [int(x) for x in (sys.argv[1:] or ["0"])]
    for sn in which:
        seen = set()
        tot = span_b = 0
        shown = 0
        print(f"===== S{sn:02d}")
        for st in secs[sn]["strings"]:
            p = st["pointer"]
            if p in seen:
                continue
            seen.add(p)
            raw = st["raw"]
            tot += len(raw)
            sp = spans(raw)
            span_b += sum(b - a for a, b, _ in sp)
            if shown < 6 and sp:
                print(f"-- E{st['entry']:04d} {len(raw)}B, span {len(sp)}개")
                for a, b, txt in sp[:14]:
                    print(f"     [{a:4d},{b:4d}) {b-a:3d}B  {txt!r}")
                shown += 1
        print(f"S{sn:02d}: 총 {tot}B 중 번역 span {span_b}B ({span_b/tot*100:.1f}%)")


# ── 그리기 DSL / 이름입력 그리드 판별 ─────────────────────────────────────
# S00/S01의 창 그리기는 구조가 뚜렷하다. 행마다 `-…ー`(윗변) `F…G`(중간)
# `B…C`(구분선) `〜…?`(아랫변) 꼴이고 사이에 대문자 라틴이 섞인다.
# 도너도 이 부분을 `structural_decoration_glyphs_preserved`로 보존한다.
DRAW_HEAD = set("-FB〜~")
DRAW_TAIL = set("ーGC?")
DRAW_ALPHA = set("DKSZHINOCGEAPQRMWXYT+")
KANA = re.compile(r"[\u3040-\u30FF]")
KANJI = re.compile(r"[\u4E00-\u9FFF]")


def is_drawing(txt: str) -> bool:
    t = txt.strip()
    if len(t) < 3:
        return False
    if t[0] in DRAW_HEAD and t[-1] in DRAW_TAIL:
        return True
    upper = sum(1 for c in t if c in DRAW_ALPHA)
    return upper >= 3 and upper / len(t) >= 0.4


def is_kana_grid(txt: str) -> bool:
    """이름 입력 화면의 가나/기호 격자 — 번역 대상이 아니다(도너도 보존)."""
    t = txt.strip()
    if len(t) < 16:
        return False
    if KANJI.search(t):
        return False
    kana = len(KANA.findall(t))
    return kana / len(t) >= 0.6


def translatable(raw: bytes):
    """번역 대상 span. 위치 토큰이 하나도 없는 레코드(이름·용어 등)는 전체가 텍스트다."""
    # 통짜 span은 **제어 토큰이 하나도 없는 레코드에서만** 안전하다.
    # 2026-08-23: 예전에는 위치 opcode(FC/FD)만 없으면 `[0, 글리프바이트합)`을 한 span으로
    # 돌려줬는데, 그 오프셋은 제어 바이트를 빼고 센 값이라 raw 오프셋과 어긋난다. 그래서
    # F6/F8/FB 같은 토큰이 span 안에 들어갔고, 재인코딩 때 **제어 토큰이 삭제됐다** —
    # HP 수치 삽입점(F8)과 동적 selector(FB)가 사라져 실기에서 파일럿 능력창이 멈췄다.
    toks = parse_record(raw + bytes([0xFF]))
    if not any(t.kind == "control" for t in toks):
        glyph_bytes = 0
        chars = []
        m = charmap()
        for t in toks:
            if t.kind == "glyph":
                glyph_bytes += len(t.raw)
                chars.append(m.get(t.glyph_id, ""))
        txt = "".join(chars)
        if glyph_bytes and not is_drawing(txt) and not is_kana_grid(txt):
            return [(0, glyph_bytes, txt)]
        return []
    out = []
    for a, b, txt in spans(raw):
        if is_drawing(txt) or is_kana_grid(txt):
            continue
        out.append((a, b, txt))
    return out


# ── 스크립트 레코드 전용 추가 필터 ────────────────────────────────────────
# 창 그리기 DSL 말고도 UI 스크립트에는 번역 대상이 아닌 글리프 런이 섞인다.
#   * 문자 팔레트 행: 이름 입력 화면의 가나/영숫자 격자(문자가 서로 겹치지 않는 긴 런)
#   * 아이콘·커서 조각: `工C` `同C` `F州` `竜+` `枚ヂGゅ` 처럼 짧고 라틴과 일본어가 섞인 런
# 두 부류 모두 도너가 보존하는 것과 같은 성격이다
# (`structural_decoration_glyphs_preserved`, `kana_name_entry_grids_preserved`).
LATIN = re.compile(r"[A-Za-z]")


def is_palette_row(ids: list[int]) -> bool:
    """이름 입력 화면의 문자 팔레트 행.

    글리프 **ID의 연속성**으로 판정한다. 팔레트는 문자표를 순서대로 늘어놓은 것이라
    인접 ID 차이가 작고 단조 증가한다(`あいうえお`, `BDFHJLNPRTVXZ`). 반대로 실제 문장은
    한자·가나가 섞여 ID가 흩어진다. 디코딩된 텍스트의 '문자 중복률'로 판정하면
    `行動終了していないユニットが` 같은 정상 문장까지 걸러진다(실제로 걸렀다)."""
    if len(ids) < 12:
        return False
    steps = [b - a for a, b in zip(ids, ids[1:])]
    seq = sum(1 for d in steps if 0 < d <= 4)
    return seq / len(steps) >= 0.7


def is_decoration(txt: str) -> bool:
    """짧고 라틴과 일본어가 섞인 런 — 스크립트 안의 아이콘/커서 조각."""
    t = txt.strip()
    if not t or len(t) > 6:
        return False
    return bool(LATIN.search(t)) and bool(KANA.search(t) or KANJI.search(t))


def span_glyph_ids(raw: bytes, start: int, end: int) -> list[int]:
    """[start,end) 구간의 글리프 ID 목록."""
    ids, pos = [], 0
    for t in parse_record(raw + bytes([0xFF])):
        n = len(t.raw)
        if t.kind == "glyph" and start <= pos < end:
            ids.append(t.glyph_id)
        pos += n
    return ids


def translatable_strict(raw: bytes):
    """스크립트 레코드면 팔레트 행/장식 조각을 더 걸러낸다."""
    toks = parse_record(raw + bytes([0xFF]))
    is_script = any(t.kind == "control" and t.opcode in POSITION_OPCODES for t in toks)
    out = []
    for a, b, txt in translatable(raw):
        if is_script:
            if is_decoration(txt) or is_palette_row(span_glyph_ids(raw, a, b)):
                continue
        out.append((a, b, txt))
    return out
