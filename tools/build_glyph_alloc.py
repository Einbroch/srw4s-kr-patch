#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""글리프 할당표 생성.

원칙
  1. **보존 글리프는 원래 ID에 그대로 둔다.** 미번역 원문이 ID로 참조하므로 옮기면 깨진다.
  2. 한글은 남는 슬롯에만 넣고, 한 번 정한 ID는 이후 단계에서도 바꾸지 않는다(안정성).
  3. 슬롯 선택 순위: ① 아무도 안 쓰는 칸 ② M_BANKS 사용 빈도가 낮은 칸 ③ ID 오름차순.
     대사(M_BANKS)가 아직 일본어인 중간 빌드에서 **덮어써서 생기는 피해를 최소화**하기 위함이다.
     중간 빌드에서 깨지는 대사 글리프 수는 리포트에 그대로 적는다.
"""
from __future__ import annotations
import json, sys, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from glyph_census import mbanks_glyphs, dnames_survivors  # noqa: E402
from span_classify import charmap                          # noqa: E402
from hangul_font import HangulFont                         # noqa: E402

SLOT_LO, SLOT_HI = 0x100, 0x700
OUT = ROOT / "translation" / "glyph_alloc.json"


def main() -> int:
    mb, _, _ = mbanks_glyphs()
    keep, _ = dnames_survivors()
    cm = charmap()

    preserved = {g for g in keep if SLOT_LO <= g < SLOT_HI}
    cand = [g for g in range(SLOT_LO, SLOT_HI) if g not in preserved]
    cand.sort(key=lambda g: (mb.get(g, 0), g))          # 미사용 -> 저빈도 -> ID순

    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    syl = sorted({ch for r in L["records"] for s in r["spans"] if s["ko"]
                  for ch in s["ko"] if "\uac00" <= ch <= "\ud7a3"})

    font = HangulFont()
    missing = [c for c in syl if c not in font]
    if missing:
        print(f"FAIL: 글꼴에 없는 음절 {len(missing)}자: {''.join(missing[:20])}")
        return 1
    if len(syl) > len(cand):
        print(f"FAIL: 수요 {len(syl)} > 가용 {len(cand)}")
        return 1

    alloc = {c: cand[i] for i, c in enumerate(syl)}
    used = set(alloc.values())
    clash = sorted(g for g in used if mb.get(g, 0))
    dmg = sum(mb[g] for g in clash)

    doc = {
        "schema": "srw4s-glyph-alloc-v1",
        "policy": {
            "preserved_ids_are_fixed": "미번역 원문이 ID로 참조하므로 보존 글리프는 이동하지 않는다",
            "hangul_ids_are_stable": "이후 단계(대사 번역)에서도 재배치하지 않는다",
            "slot_order": "M_BANKS 미사용 -> 저빈도 -> ID 오름차순",
        },
        "supply": {
            "slots_16x16": SLOT_HI - SLOT_LO,
            "preserved": len(preserved),
            "candidates": len(cand),
        },
        "demand": {"hangul_syllables": len(syl)},
        "intermediate_build": {
            "note": "대사(M_BANKS)가 일본어인 빌드에서는 아래 슬롯이 겹쳐 그 글리프가 한글로 보인다",
            "clashing_slots": len(clash),
            "affected_dialogue_glyph_uses": dmg,
        },
        "preserved_ids": {f"0x{g:03X}": cm.get(g, "") for g in sorted(preserved)},
        "hangul": {c: f"0x{alloc[c]:03X}" for c in syl},
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"16x16 슬롯 {SLOT_HI-SLOT_LO}  보존 {len(preserved)}  가용 {len(cand)}")
    print(f"한글 {len(syl)}자 할당 -> ID 0x{min(used):03X}..0x{max(used):03X}")
    print(f"중간 빌드 충돌 슬롯 {len(clash)}칸 / 영향받는 대사 글리프 사용 {dmg:,}회")
    print(f"할당 후 남는 칸 {len(cand)-len(syl)}")
    print(f"기록: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
