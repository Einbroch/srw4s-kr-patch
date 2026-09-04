#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 원장 검증 게이트.

  1. 출처 sha256 (stale 차단)
  2. 보호 필드(jp/raw_hex)가 현재 추출과 같은가
  3. **표식 보존** — 역문이 원문과 같은 표식을 같은 개수로 갖는가.
     제어 토큰이 빠지면 게임이 멈춘다(D_NAMES에서 F8·FB를 삼켜 실증).
  4. 역문이 실제로 인코딩되는가 (문자표 밖 글자 차단)
  5. 0x400 런타임 창을 넘지 않는가
"""
from __future__ import annotations
import collections, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode, markers   # noqa: E402
from span_classify import charmap                     # noqa: E402
from hangul_font import HangulFont                    # noqa: E402
from mb_codec import TOKEN, GLYPH                     # noqa: E402
from mb_layout import violations, budget, LINE_PX, PAGE_LINES   # noqa: E402
from reflow_ko import NO_REFLOW, is_menu, VARIANT                         # noqa: E402

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
WINDOW = 0x400


SPEAKER: dict = {}
try:
    import runpy as _rp
    SPEAKER = _rp.run_path(str(ROOT / "translation" / "mbanks_speaker_fix.py"))["SPEAKER"]
except Exception:
    pass


def main() -> int:
    d = SRC.read_bytes()
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    err = collections.defaultdict(list)
    if L["source"]["sha256"] != hashlib.sha256(d).hexdigest():
        print("FAIL: source.sha256 불일치 (stale)")
        return 1
    enc = build_encoder()
    cm = charmap(); cm[0x000] = " "
    font = HangulFont()
    low = {c for g, c in cm.items() if c and g < 0xF0}
    low.add(" ")
    drawable = set(low) | {c for c in cm.values() if c} | set(font.syllables)
    ntr = 0
    for r in L["records"]:
        raw = bytes.fromhex(r["raw_hex"])
        if d[r["offset"]:r["end"]] != raw:
            err["raw_mismatch"].append(r["id"])
            continue
        if not r["ko"]:
            continue
        ntr += 1
        # {N} 은 순수 조판(줄바꿈)이라 개수가 달라도 된다 — 한국어는 끊는 자리가 다르다.
        # 대신 아래에서 진짜 제약인 줄 폭과 페이지당 줄 수를 강제한다.
        drop = lambda ms: collections.Counter(m for m in ms if m != "{N}")
        a, b = drop(markers(r["jp"])), drop(markers(r["ko"]))
        if a != b:
            miss = (a - b) or (b - a)
            err["marker"].append(f"{r['id']} {dict(miss)}")
            continue
        bad = [c for c in TOKEN.sub("", GLYPH.sub("", r["ko"]))
               if c not in drawable]
        if bad:
            err["undrawable"].append(f"{r['id']} {''.join(sorted(set(bad)))!r}")
            continue
        # 표식 폭을 2바이트로 어림잡으면 표식이 많은 레코드가 과대평가된다 —
        # 인코딩이 되는 문자열은 실측 바이트를 쓴다.
        try:
            est = len(encode(r["ko"], enc))
        except KeyError:
            est = 2 * len(markers(r["ko"]))
            for c in TOKEN.sub("|", GLYPH.sub("|", r["ko"])):
                est += 1 if c in low else 2
        if est > WINDOW:
            err["too_long"].append(f"{r['id']} {est}B")
            continue
        # 선택지 페이지의 {N} 은 조판이 아니라 구조다. 지우면 선택지가 한 줄로 붙고,
        # 선행 공백을 잃으면 커서 자리만큼 왼쪽으로 밀린다.
        jps, kos = r["jp"].split("{P}"), r["ko"].split("{P}")
        if len(jps) == len(kos):
            for pj, pk in zip(jps, kos):
                if not is_menu(pj, enc):
                    continue
                lead = len(pj) - len(pj.lstrip(" "))
                if pj.count("{N}") != pk.count("{N}") or                         len(pk) - len(pk.lstrip(" ")) != lead:
                    err["menu_page"].append(f"{r['id']} {pk!r}")
                    break
            # 두 갈래 응답의 경계는 조판이 아니라 구조다 — 지우면 두 대사가 붙는다
            for pj, pk in zip(jps, kos):
                if len(VARIANT.split(pj)) != len(VARIANT.split(pk)):
                    err["variant_page"].append(
                        f"{r['id']} 원문 {len(VARIANT.split(pj))}갈래 -> 역문 {len(VARIANT.split(pk))}갈래")
                    break
        if r["id"] in NO_REFLOW:
            continue          # 바이너리 앞머리 + 대사 꼬리 — 조판 검사가 의미 없다
        if "{A}" in r["jp"]:
            # 앞머리가 표 데이터라 통째로 재면 폭이 뻥튀기된다(원문도 마찬가지).
            # 화면에 글자로 나오는 건 「」 안쪽뿐이니 거기만 잰다.
            # 「」 **밖**은 데이터다 — 원문과 한 글자라도 달라지면 표가 어긋난다.
            # (2026-09-01: 역문을 일괄 치환하다 MB:00014 의 표를 1B 줄여 먹었다.)
            def _out(s):
                a, b = s.rfind("「"), s.rfind("」")
                return (s[:a + 1], s[b:]) if 0 <= a < b else None
            oj, ok_ = _out(r["jp"]), _out(r["ko"])
            # 「 바로 앞의 화자 이름은 표가 아니라 화면에 나오는 글자다.
            # 선언한 치환(translation/mbanks_speaker_fix.py)만 예외로 허용한다 —
            # 적지 않은 변경은 그대로 실패한다.
            if oj != ok_ and r["id"] in SPEAKER:
                jp_nm, ko_nm = SPEAKER[r["id"]]
                if oj and oj[0].endswith(jp_nm + "「"):
                    oj = (oj[0][:-len(jp_nm) - 1] + ko_nm + "「", oj[1])
            if oj != ok_:
                err["data_prefix"].append(f"{r['id']} 「」 밖이 원문과 다르다")
            i, j = r["ko"].rfind("「"), r["ko"].rfind("」")
            if 0 <= i < j:
                w, _ = violations(r["ko"][i + 1:j], enc, LINE_PX, PAGE_LINES)
                if w:
                    err["line_overflow"].append(f"{r['id']} 대사 {w[0][2]}px>{LINE_PX}")
            continue
        lpx, plines = budget(r["jp"], enc, r.get("owners", ()))   # 창마다 규약이 다르다
        wide, deep = violations(r["ko"], enc, lpx, plines)
        if wide:
            err["line_overflow"].append(f"{r['id']} {wide[0][2]}px>{lpx}")
        if deep:
            err["page_lines"].append(f"{r['id']} {deep[0][1]}줄>{plines}")
    tot = sum(len(v) for v in err.values())
    print(f"레코드 {len(L['records']):,} / 역문 {ntr:,}")
    for k, v in err.items():
        print(f"  {k}: {len(v)}건 예: {v[:4]}")
    print("PASS: 오류 없음" if tot == 0 else f"FAIL: {tot}건")
    return 0 if tot == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
