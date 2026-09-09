#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""별칭이 **원문 접미사 사본**으로 떨어지는 개수를 고정한다 (회귀 감시선).

`M_BANKS` 에는 레코드 안쪽을 가리키는 별칭이 1,942개 있다. 역문은 길이가 달라
그 안쪽 자리가 어긋나므로, 옮길 근거가 없는 별칭은 원문 접미사 사본을 읽는다 —
화면에 일본어가 그대로 나온다.

이 검사는 **정확성을 증명하지 않는다.** `ko_alias_offsets` 를 그대로 써서 세므로
같은 로직의 오류는 못 잡는다([[gate-must-not-self-verify]]). 목적은 하나다:
매핑을 건드렸을 때 **구제 수가 줄어들면 실패**시켜 회귀를 잡는 것.

기준선은 2026-09-06 실측이다.
  앞머리 그대로 885 / 매핑됨 51 / 원문 사본 1,006
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

BASE_MAPPED = 51          # 이보다 줄면 실패


def main() -> int:
    from mb_codec import build_encoder, encode
    from mb_alias import ko_alias_offsets
    enc = build_encoder()
    doc = json.loads((ROOT / "translation" / "mbanks_ledger.json").read_text(encoding="utf-8"))
    tot = head = mapped = lost = 0
    for r in doc["records"]:
        if not r["ko"] or not r["alias_starts"]:
            continue
        raw = bytes.fromhex(r["raw_hex"])
        try:
            nb = encode(r["ko"], enc)
        except KeyError:
            continue
        cpl = 0
        while cpl < min(len(raw), len(nb)) and raw[cpl] == nb[cpl]:
            cpl += 1
        kmap = ko_alias_offsets(r["jp"], r["ko"], enc)
        for a in r["alias_starts"]:
            rel = int(a, 16) - r["offset"]
            tot += 1
            if 0 < rel <= cpl:
                head += 1
            elif rel in kmap:
                mapped += 1
            else:
                lost += 1
    print(f"별칭 {tot:,} / 앞머리 {head:,} / 매핑됨 {mapped:,} / 원문 사본 {lost:,}")
    if mapped < BASE_MAPPED:
        print(f"FAIL: 매핑된 별칭이 기준선 {BASE_MAPPED} 아래로 떨어졌다")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
