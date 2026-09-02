#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 번역 원장 검증 게이트.

확인 항목
  1. 출처: 원장의 source.sha256이 현재 추출 기준선과 같은가(stale 차단)
  2. 보호 필드: 모든 레코드의 raw_hex가 현재 추출에서 다시 만든 값과 같은가
  3. span 무결성: [start,end)가 레코드 안이고, 서로 겹치지 않고, 순서대로이고,
     그 구간 바이트에서 디코딩한 원문이 span.jp와 같은가
  4. 역문 글리프 커버리지: ko의 모든 문자가 표현 가능한가
     (low bank 문자이거나 KS X 1001 한글). 불가능하면 **빌드 에러**로 취급한다.
  5. 상태값이 정의된 집합 안인가
  6. 재인코딩 시뮬레이션: span을 역문으로 바꾼 레코드가 토큰 계약을 지키는가
     (`parse_record`가 통과하고 종단이 정확히 하나)
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_structures import dnames_sections     # noqa: E402
from span_classify import translatable_strict as translatable, charmap  # noqa: E402
from text_codec import parse_record, glyph_bytes   # noqa: E402
from measure_growth import build_lowbank_chars     # noqa: E402
from hangul_font import HangulFont                 # noqa: E402

DN = ROOT / "extract" / "DAT" / "D_NAMES.BIN"
LEDGER = ROOT / "translation" / "dnames_ledger.json"
VALID_STATUS = {"untranslated", "in_progress", "needs_review",
                "needs_human_review", "complete"}

_ovr = ROOT / "translation" / "span_overrides.json"
OVERRIDES: dict[str, list] = {}
if _ovr.exists():
    for _rid, _a, _b, _why in json.loads(_ovr.read_text(encoding="utf-8"))["force_include"]:
        OVERRIDES.setdefault(_rid, []).append((_a, _b))


def main() -> int:
    data = DN.read_bytes()
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    errors = defaultdict(list)

    if L["source"]["sha256"] != hashlib.sha256(data).hexdigest():
        print("FAIL: 원장 source.sha256이 현재 추출과 다르다 (stale)")
        return 1

    # 현재 추출에서 기준선 재생성
    base = {}
    seen = set()
    for sec in dnames_sections(data):
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            p = st["pointer"]
            if p in seen:
                continue
            seen.add(p)
            raw_ff = st["raw"] + bytes([0xFF])
            sp = list(translatable(st["raw"]))
            # 휴리스틱이 잘못 버린 스팬은 span_overrides.json이 정본이다(빌더와 같은 규약).
            for a, b in OVERRIDES.get(f"DN:{p:04X}", []):
                if not any(x[0] == a and x[1] == b for x in sp):
                    m = charmap(); pos = 0; chars = []
                    for t in parse_record(raw_ff):
                        if t.kind == "glyph" and a <= pos < b:
                            chars.append(m.get(t.glyph_id, ""))
                        pos += len(t.raw)
                    sp.append((a, b, "".join(chars)))
            sp.sort(key=lambda x: x[0])
            base[f"DN:{p:04X}"] = (raw_ff, sp)

    low = build_lowbank_chars()
    font = HangulFont()
    ko_chars = set()

    for rec in L["records"]:
        rid = rec["id"]
        if rid not in base:
            errors["missing_in_baseline"].append(rid)
            continue
        raw, spans = base[rid]
        if rec["raw_hex"] != raw.hex().upper():
            errors["raw_mismatch"].append(rid)
            continue
        ref = {(a, b): jp for a, b, jp in spans}
        prev_end = -1
        for s in rec["spans"]:
            a, b = s["start"], s["end"]
            if not (0 <= a < b <= len(raw)):
                errors["span_range"].append(f"{rid}[{a},{b})")
                continue
            if a < prev_end:
                errors["span_overlap"].append(f"{rid}[{a},{b})")
            prev_end = b
            if (a, b) not in ref:
                errors["span_not_in_baseline"].append(f"{rid}[{a},{b})")
            elif ref[(a, b)] != s["jp"]:
                errors["span_jp_mismatch"].append(f"{rid}[{a},{b})")
            if s["status"] not in VALID_STATUS:
                errors["bad_status"].append(f"{rid}:{s['status']}")
            if s["ko"]:
                ko_chars.update(s["ko"])

        # 재인코딩 시뮬레이션
        out = bytearray()
        cur = 0
        ok = True
        for s in sorted(rec["spans"], key=lambda x: x["start"]):
            out += raw[cur:s["start"]]
            if s["ko"]:
                try:
                    # 실제 글리프 ID 할당 전이므로 길이만 맞춘 자리표시 인코딩
                    for ch in s["ko"]:
                        out += glyph_bytes(0x20 if ch in low else 0x100)
                except ValueError:
                    ok = False
            else:
                out += raw[s["start"]:s["end"]]
            cur = s["end"]
        out += raw[cur:]
        if ok:
            try:
                toks = parse_record(bytes(out))
                if sum(1 for t in toks if t.kind == "terminator") != 1:
                    errors["reencode_terminator"].append(rid)
            except Exception as exc:
                errors["reencode_parse"].append(f"{rid}: {exc}")

    # 글리프 커버리지
    #   표현 가능 = low bank 문자 | KS X 1001 한글 | 원본 폰트에 이미 있는 글리프
    # 마지막 부류(× ⊕ ▲ 〜 Ⅱ 전각공백 …)는 **보존 대상 원문 글리프**다. 한글과 같은
    # 16x16 슬롯을 먹으므로 몇 종인지 함께 보고한다(FONT.md 할당 계산의 입력).
    existing = {c for c in charmap().values() if c}
    unmappable = sorted(c for c in ko_chars
                        if c not in low and c not in font
                        and c not in existing and c != "\n")
    preserve = sorted(c for c in ko_chars
                      if c not in font and c not in low and c in existing)
    print(f"보존해야 할 원문 글리프 {len(preserve)}종: {''.join(preserve)}")
    if unmappable:
        errors["unmappable_chars"] = unmappable

    total = sum(len(v) for v in errors.values())
    print(f"레코드 {len(L['records'])}개 / span {sum(len(r['spans']) for r in L['records'])}개 검증")
    print(f"역문에 쓰인 고유 문자 {len(ko_chars)}자 "
          f"(한글 {sum(1 for c in ko_chars if '\uac00' <= c <= '\ud7a3')}자)")
    if total == 0:
        print("PASS: 오류 없음")
        return 0
    print(f"FAIL: 오류 {total}건")
    for k, v in errors.items():
        print(f"  {k}: {len(v)}건 예: {v[:5]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
