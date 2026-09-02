#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""남은 M_BANKS 대사 역문을 원장에 채운다.

두 갈래로 나눠 넣는다.

  QUOTE  앞머리가 표 데이터인 레코드 — 「」 **안쪽만** 바꾸고 바깥은 원문 그대로.
         (`{A}` 레코드는 verify_mb_ledger 게이트가 이걸 강제한다)
  WHOLE  앞머리가 깨끗한 레코드 — 화자 이름까지 통째로 바꾼다.

별칭이 많은 `{A}` 레코드 다섯(32A18/34DD2/36F36/37E26/38C0C)은 예전에 넣었다가
게이트가 별칭 깨짐을 잡아 되돌린 자리다. 여기서도 제외한다.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "translation" / "mbanks_ledger.json"

QUOTE = {
    "MB:02933": "아까 못 여쭤봤는데, 티탄즈가{N}뭔가요?",
    "MB:09F41": "어라? 야, 우추타, 저 콜로니{N}움직이는 거 아냐?",
    "MB:0CC39": "{C:06}발진!!",
    "MB:0F771": "나에게 압박을 가하다니!?",
    "MB:100E4": "쿄시로, 나나, 무리하지 마라!",
    "MB:200E4": "반죠 님, 하란 재벌 메인 컴퓨터에{N}침입자가 있었던 모양입니다",
    "MB:22C4F": "...흐음, 그럼 별문제 없다는 거군",
    "MB:286D1": "크윽...분하다...아이잠...나는, 나는{N}그대를 죽게 하고 싶지 않았다...",
    "MB:2AFAE": "휴, 어떻게든 추격은 따돌렸군요...",
    "MB:2FFCC": "거짓말이지!? 이런 데서...",
    "MB:3B1C3": "아앙...그래, 늘었네, 코우...아,{N}안 돼, 그렇게 거칠게 하면! 좀 더 천천히...{N}그래...부드럽게...",
    "MB:400E4": "뭐...슈우!! 너, 갑자기 뭐 하는 짓이야!!{N}그라비트론 캐논을 쏴 갈기다니, 배짱 좋군!!{N}또 우리랑 붙을 셈이냐!?",
    "MB:46045": "이쯤이면 되겠지. 토레스, 진로 변경,{N}달로",
    "MB:62745": "다바, 크와산 상태는 어때?",
    "MB:6489F": "아, 아무로! 또 만났네",
    "MB:6884A": "카미유=비단!! 죽어라!!",
    "MB:6FF3F": "어라? GG걸즈 멤버 바뀌지{N}않았나? 로라는 그만뒀잖아?",
}

WHOLE = {
    "MB:30609": "{B:1E80}「에〜, 멍하니 있었어요?」",
    "MB:3062B": "{B:1E80}「좀, 생각할 게 있었거든요」",
    "MB:30643": "{B:1E80}「응? 아아, 좀 생각할 게 있어서」",
    "MB:30659": "{B:1E80}「어? 아아, 좀 생각할 게 있었을 뿐이다」",
    "MB:30706": "{B:1E80}「그렇다니까요. 왠지 그리워져{N}버려서요」",
    "MB:307D5": "{B:1E80}「아니에요. 그런 거 아닙니다」",
    "MB:307ED": "{B:1E80}「아뇨아뇨, 옛날 일 생각할 틈 같은 건{N}없어. 지금 일이 더 바빠서 말이야」",
    "MB:3084D": "{B:1E80}「설마. 이미 지난 일이다」",
    "MB:3413E": "「윽...기억해 둬라!!」",
    "MB:3683A": "「호오, 제법이군」",
    "MB:70257": "{B:1E80}「네. 여러분과 합류하기 전에, 정체불명의{N}적에게 습격당한 적이 있어요. 그때 상대가{N}지금 저놈들이었습니다」",
    "MB:7029C": "{B:1E80}「!? 저 적 로봇, 혹시...」",
    "MB:702C6": "{B:1E80}「알고 싶어, {B:3080}?」",
    "MB:70314": "{B:3080}「...그대로 당했으면 좋았을 것을」",
    "MB:70353": "{B:1E80}「으〜음, 으〜음...조금만 더 하면 떠오를{N}것 같은데...뭐였더라」",
}


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    n, skip = 0, []
    for r in L["records"]:
        if r["ko"]:
            continue
        q, w = QUOTE.get(r["id"]), WHOLE.get(r["id"])
        if q:
            s = r["jp"]
            a, b = s.rfind("「"), s.rfind("」")
            if not (0 <= a < b):
                skip.append(r["id"]); continue
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
    else:
        print("(--apply 를 붙여야 반영된다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
