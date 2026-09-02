#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""표 밖 전투 대사 — **같은 대사의 다른 사본**에 이미 만든 역문을 재사용한다.

같은 문장이 두 벌씩 있다. 이름표 없는 것(`「くっ!」`)과 화자 앞머리가 붙은 것
(`{C:0F}Sゃ「くっ!」`)이다. **화면에 뜨는 건 이름표 붙은 쪽**이라 한쪽만 번역하면
게임에서는 그대로 일본어로 보인다(2026-09-01 실기 확인).

「」 안쪽만 옮겨 붙이고 앞뒤(화자 앞머리·제어 토큰)는 원문 그대로 둔다.
칸이 고정이라 모자란 만큼은 닫는 괄호 앞에 공백으로 메운다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode     # noqa: E402

LEDGER = ROOT / "translation" / "mbankb_hidden_ledger.json"


def quote(s):
    a, b = s.rfind("「"), s.rfind("」")
    return (a, b, s[a + 1:b]) if 0 <= a < b else None


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()
    done = {}
    for r in L["records"]:
        if not r["ko"]:
            continue
        qj, qk = quote(r["jp"]), quote(r["ko"])
        if qj and qk:
            done[qj[2]] = qk[2]
    n, over = 0, []
    for r in L["records"]:
        if r["ko"]:
            continue
        qj = quote(r["jp"])
        if not qj or qj[2] not in done:
            continue
        a, b, _ = qj
        want = r["end"] - r["offset"]
        base = r["jp"][:a + 1] + done[qj[2]] + r["jp"][b:]
        try:
            pad = want - len(encode(base, enc))
        except KeyError:
            continue
        if pad < 0:
            over.append((r["id"], qj[2])); continue
        ko = r["jp"][:a + 1] + done[qj[2]] + " " * pad + r["jp"][b:]
        if len(encode(ko, enc)) != want:
            over.append((r["id"], qj[2])); continue
        if apply:
            r["ko"] = ko
        n += 1
    print(f"재사용 {n}개" + (f" / 자리 초과 {len(over)}개" if over else ""))
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"원장에 반영 — 누적 {sum(1 for r in L['records'] if r['ko'])} / {len(L['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
