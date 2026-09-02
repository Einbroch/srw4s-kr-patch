#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""재삽입 산출물 검증 — 새 D_NAMES가 원본과 같은 규약으로 읽히는지 본다.

  1. 구조: dnames_sections가 18개 헤더를 원본과 같은 엔트리 수로 되찾는가
  2. 내용: 모든 테이블 엔트리가 기대한 레코드 바이트를 정확히 가리키는가
     (토큰 정합 — 공유 배치가 경계를 벗어나면 여기서 걸린다)
  3. 크기: 상주 슬롯 53,248 B 안인가
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections, text_end   # noqa: E402
from text_codec import parse_record                         # noqa: E402

SLOT = 55296


def main() -> int:
    old = (ROOT / "extract" / "DAT" / "D_NAMES.BIN").read_bytes()
    new = (ROOT / "build" / "D_NAMES_ko.BIN").read_bytes()
    remap = {int(k, 16): int(v, 16) for k, v in
             json.loads((ROOT / "build" / "dnames_remap.json").read_text()).items()}
    osecs, nsecs = dnames_sections(old), dnames_sections(new)
    errs = []

    for o, n in zip(osecs, nsecs):
        if (o["start"] is None) != (n["start"] is None):
            errs.append(f"S{o['section']:02d} null 여부 불일치"); continue
        if o["start"] is None:
            continue
        if o["count"] != n["count"]:
            errs.append(f"S{o['section']:02d} 엔트리 수 {o['count']}->{n['count']}")

    for o, n in zip(osecs, nsecs):
        if o["start"] is None or o["count"] != n["count"]:
            continue
        for a, b in zip(o["strings"], n["strings"]):
            want = remap.get(a["pointer"])
            if want is None:
                errs.append(f"remap 누락 0x{a['pointer']:04X}"); continue
            if b["pointer"] != want:
                errs.append(f"S{o['section']:02d}E{a['entry']:04d} 포인터 {b['pointer']:#06x} != {want:#06x}")
                continue
            try:
                parse_record(new[b["pointer"]:text_end(new, b["pointer"])] + bytes([0xFF]))
            except Exception as exc:
                errs.append(f"S{o['section']:02d}E{a['entry']:04d} 파싱 실패: {exc}")

    print(f"원본 {len(old):,}B -> 새 {len(new):,}B   슬롯 {SLOT:,} 대비 {len(new)-SLOT:+,}")
    print(f"섹션 {sum(1 for s in nsecs if s['start'] is not None)}개 / "
          f"엔트리 {sum(s['count'] for s in nsecs if s['start'] is not None)}개 검사")
    if len(new) > SLOT:
        errs.append(f"슬롯 초과 {len(new)-SLOT}B")
    if errs:
        print(f"FAIL: {len(errs)}건")
        for e in errs[:10]:
            print("   ", e)
        return 1
    print("PASS: 구조·포인터·토큰 정합 이상 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
