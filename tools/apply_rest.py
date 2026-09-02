#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""남은 미번역 대사를 원장에 채운다 — 별칭 잠김 21줄 + 꼬리 조각 12줄.

  QUOTE  앞머리가 표/애니 데이터인 레코드 — 마지막 「」 **안쪽만** 바꾼다.
         앞부분이 원본과 바이트 동일해야 그 안의 별칭이 살아남는다.
  WHOLE  앞머리가 깨끗하거나 아예 꼬리 조각인 레코드 — 통째로 바꾼다.

꼬리 조각은 원문도 문장 도중에서 시작한다(별칭 재사용의 흔적). 화면에는 그 상태로
한 줄이 통째로 뜨므로, 역문도 그 자리에서 말이 되게 짧은 한 줄로 옮긴다.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "translation" / "mbanks_ledger.json"

QUOTE = {
    # 애니 데이터 앞머리 + 대사 꼬리 (별칭 다수)
    "MB:37E26": "어림없다!",
    "MB:36F36": "이 정도라면!!",
    "MB:38C0C": "빔 따위 통하지 않는다!!",
    "MB:32A18": "으왓!! 이, 이대로는{N}당하고 만다!",
    "MB:34DD2": "훗...",
    "MB:2FFCC": "거짓말이지!? 이런 데서...",
    "MB:286D1": "으...분하다...아이잠...나는, 나는{N}그대를 죽게 하고 싶지 않았다...",
    "MB:6FF3F": "어라? GG걸즈 멤버 바뀌지{N}않았나? 로라는 그만뒀잖아?",
}

WHOLE = {
    # 앞머리가 깨끗한 대사
    "MB:30609": "{B:1E80}「에〜, 멍하니 있었어요?」",
    "MB:3062B": "{B:1E80}「좀, 생각할 게 있었거든요」",
    "MB:30643": "{B:1E80}「응? 아아, 좀 생각할 게 있어서」",
    "MB:30659": "{B:1E80}「어? 아아, 좀 생각할 게 있었을 뿐이다」",
    "MB:30706": "{B:1E80}「그렇다니까요. 왠지 그리워져{N}버려서요」",
    "MB:307D5": "{B:1E80}「아니에요. 그런 거 아닙니다」",
    "MB:307ED": "{B:1E80}「아뇨아뇨, 옛날 일 생각할 틈 같은 건{N}없어. 지금 일이 더 바빠서 말이야」",
    "MB:3084D": "{B:1E80}「설마. 이미 지난 일이다」",
    "MB:70257": "{B:1E80}「네. 여러분과 합류하기 전에{N}정체불명의 적에게 습격당했어요.{N}그때 상대가 지금 저놈들이었습니다」",
    "MB:7029C": "{B:1E80}「!? 저 적 로봇, 혹시...」",
    "MB:702C6": "{B:1E80}「알고 싶어, {B:3080}?」",
    "MB:70314": "{B:3080}「...그대로 당했으면 좋았을 것을」",
    "MB:70353": "{B:1E80}「으〜음, 으〜음...조금만 더 하면{N}떠오를 것 같은데...뭐였더라」",
    # 유닛 설명 (와이드 창)
    "MB:5F289": "OVA에서 라반이 타던 오라 배틀러.{N}그 흉흉한 자태는 그야말로 악마와도 같다.",
    # 꼬리 조각 — 원문도 문장 도중에서 시작한다
    "MB:33400": "{N}안 되겠군요」",
    "MB:33F82": "당했다아앗!」",
    "MB:3563E": "이거라면!!」",
    "MB:38F13": "안 통한다니까!!」",
    "MB:38F6E": " 쓸데없는 짓을!!」",
    "MB:73F14": "데미지가 너무 커!?」",
    "MB:74207": "안 통한다니까!」",
    "MB:74D58": "..조금만 더...」",
    "MB:77904": "읏! 하지만 이 정도면{N}아직 더 갈 수 있어!」",
    "MB:78007": "아니라니까!」",
    "MB:7805F": "그럴까 보냐!!」",
    "MB:780F0": "왓!! 신고!!{N}이 녀석 위험해!」",
}


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    n, skip = 0, []
    for r in L["records"]:
        q, w = QUOTE.get(r["id"]), WHOLE.get(r["id"])
        if q:
            s = r["jp"]
            a, b = s.rfind("「"), s.rfind("」")
            if not (0 <= a < b):
                skip.append(r["id"])
                continue
            ko = s[:a + 1] + q + s[b:]
        elif w:
            ko = w
        else:
            continue
        if apply:
            r["ko"] = ko
        n += 1
    print(f"채운 레코드 {n}개" + (f" / 「」 못 찾음 {skip}" if skip else ""))
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        tr = sum(1 for r in L["records"] if r["ko"])
        print(f"원장 반영 — 역문 {tr:,} / {len(L['records']):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
