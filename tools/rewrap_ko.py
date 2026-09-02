#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""역문을 대사창 규약(320px / 페이지 3줄)에 맞게 다시 조판한다.

`{N}` 은 순수 조판이라 원문과 개수가 달라도 된다. 나머지 표식은 손대지 않는다.
3줄에 안 들어가는 페이지는 **고치지 않고 보고**한다 — 줄이는 건 사람이 할 일이다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, markers          # noqa: E402
from mb_layout import rewrap, violations             # noqa: E402

LEDGER = ROOT / "translation" / "mbanks_ledger.json"


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()
    changed, still = 0, []
    for r in L["records"]:
        if not r["ko"]:
            continue
        new = rewrap(r["ko"], enc)
        # {N} 외의 표식은 하나도 잃지 않았는지 확인
        keep = lambda m: [x for x in markers(m) if x != "{N}"]
        if keep(new) != keep(r["ko"]):
            print(f"FAIL: {r['id']} 재조판이 표식을 바꿨다")
            return 1
        wide, deep = violations(new, enc)
        if wide:
            print(f"FAIL: {r['id']} 재조판 후에도 줄이 넘친다 {wide[0]}")
            return 1
        if deep:
            still.append((r["id"], deep))
        if new != r["ko"]:
            changed += 1
            if apply:
                r["ko"] = new
    print(f"재조판 {changed}개 / 3줄 초과로 남은 레코드 {len(still)}개")
    for rid, d in still[:80]:
        print(f"   {rid}  " + " ".join(f"p{p}={n}줄" for p, n in d))
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장에 반영했다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
