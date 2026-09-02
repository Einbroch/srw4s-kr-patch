#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 원장 용어 통일 — 도너(컴플리트 박스) 승인 용어집을 SSOT로 적용한다.

적용 순서와 근거
  1. glossary_names_ko.json `variants` (이형 표기 -> 승인 표기)
  2. 수동 판정 교정표 FIXES (오독·오역. 근거를 주석에 남긴다)
  3. 무장명 span은 공백을 전부 제거한다.
     근거: 도너 third-ui/inject_third_ui.py:358 — 사전 등록분만 지우면 폭에 들어가는
     172종을 놓쳐 같은 표에서 표기가 갈린다(제보 #15a). 인코딩 직전 무조건 건다.
  4. despace_nospace.json 전값 일치 (메뉴·상태 라벨의 폭 초과 공백 제거)

--apply 없이 실행하면 변경 후보만 출력한다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from measure_growth import build_lowbank_chars  # noqa: E402

REF = ROOT / "reference" / "srwcb-korean-patch" / "translation"
LEDGER = ROOT / "translation" / "dnames_ledger.json"

# 수동 판정. 왼쪽이 현재 역문 전값, 오른쪽이 확정 표기.
FIXES = {
    # 早乙女 = 사오토메. '신오토메'는 오독이다. 지형 타일은 4~6칸이라 '新'을 떼어
    # 폭을 지키면서 이름을 바로잡는다(지형표에 早乙女 단독 항목이 없어 모호하지 않다).
    "신오토메": "사오토메",
    "석신오토메": "석사오토메",
    "야신오토메": "야사오토메",
    # 같은 원문 'ゲッタ-ロボ!'에 역문이 둘이었다. 목록 칸이라 붙여 쓴 쪽으로 통일한다.
    "게터로보!": "겟타로보!",
}
# 무장 표는 D_NAMES 섹션 S08이다(S09·S10은 같은 문자열 풀을 가리키는 별칭이라
# 포인터가 S08로 합쳐진다). 배치 tsv로 고르면 한자 무장명만 잡혀 가타카나 무장명을
# 통째로 놓친다 — 도너가 겪은 제보 #15a와 같은 함정이다.
WEAPON_SECTIONS = {8, 9, 10}


def weapon_record_ids() -> set:
    sec = json.loads((ROOT / "translation" / "_section_map.json").read_text(encoding="utf-8"))
    return {rid for rid, i in sec.items() if i in WEAPON_SECTIONS}


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    variants = json.loads((REF / "glossary_names_ko.json").read_text(encoding="utf-8"))["variants"]
    despace = json.loads((REF / "despace_nospace.json").read_text(encoding="utf-8"))
    wids = weapon_record_ids()
    low = build_lowbank_chars()

    changes = []
    for rec in L["records"]:
        for s in rec["spans"]:
            ko = s["ko"]
            if not ko:
                continue
            orig, why = ko, []
            for bad, good in variants.items():
                if bad in ko:
                    ko = ko.replace(bad, good); why.append(f"variants:{bad}>{good}")
            if ko in FIXES:
                why.append(f"fix:{ko}>{FIXES[ko]}"); ko = FIXES[ko]
            if rec["id"] in wids and (" " in ko or "\u3000" in ko):
                ko = ko.replace(" ", "").replace("\u3000", ""); why.append("weapon-despace")
            elif " " in ko or "\u3000" in ko:
                nk = ko.replace(" ", "").replace("\u3000", "")
                if nk in despace and despace[nk] != ko:
                    ko = despace[nk]; why.append("despace-dict")
            if ko != orig:
                changes.append((rec["id"], s["jp"], orig, ko, ",".join(why)))
                if apply:
                    s["ko"] = ko

    w = lambda t: sum(1 if c in low else 2 for c in t)
    print(f"변경 {len(changes)}건")
    for cat in ("fix", "variants", "weapon-despace", "despace-dict"):
        sub = [c for c in changes if c[4].startswith(cat) or f",{cat}" in c[4]]
        print(f"  [{cat}] {len(sub)}건")
        for _, jp, a, b, _w in sub[:6]:
            print(f"      {jp}  |  {a} -> {b}  (폭 {w(a)}->{w(b)}, 원문 {w(jp)})")
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장에 반영했다.")
    else:
        print("(--apply 없이 실행: 원장은 그대로다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
