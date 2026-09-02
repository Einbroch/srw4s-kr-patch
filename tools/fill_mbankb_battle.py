#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB 전투 대사 역문을 원장에 채운다.

레코드가 `[표 데이터]「대사」[뒤쪽 데이터]` 꼴이다. 칸 길이가 고정이므로
  * 「」 **밖**은 원문 바이트 그대로 둔다 (앞머리가 표라 한 바이트도 못 건드린다)
  * 모자란 만큼은 닫는 「」 **앞**에 공백을 넣어 메운다
    (뒤에 붙이면 」 이후 바이트가 밀린다)
"""
from __future__ import annotations
import json, runpy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode      # noqa: E402

LEDGER = ROOT / "translation" / "mbankb_ledger.json"
TABLE = ROOT / "translation" / "mbankb_battle_ko.py"


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    Q = runpy.run_path(str(TABLE))["Q"]
    enc = build_encoder()
    sp = encode(" ", enc)[:-1]
    done, miss, bad = 0, {}, []
    for r in L["records"]:
        if r["ko"]:
            continue
        s = r["jp"]
        a, b = s.rfind("「"), s.rfind("」")
        if not (0 <= a < b):
            continue
        qj = s[a + 1:b]
        qk = Q.get(qj)
        if qk is None:
            if "{" not in qj and len(qj) <= 40:
                miss[qj] = miss.get(qj, 0) + 1
            continue
        nj, nk = len(encode(qj, enc)) - 1, len(encode(qk, enc)) - 1
        if nk > nj:
            bad.append((r["id"], qj, nj, nk))
            continue
        qk = qk + " " * ((nj - nk) // len(sp))
        ko = s[:a + 1] + qk + s[b:]
        if len(encode(ko, enc)) != r["end"] - r["offset"]:
            bad.append((r["id"], qj, r["end"] - r["offset"], len(encode(ko, enc))))
            continue
        if apply:
            r["ko"] = ko
        done += 1
    if bad:
        for rid, q, x, y in bad:
            print(f"FAIL {rid}: {q[:24]!r} {x}B -> {y}B")
        return 1
    print(f"채운 레코드 {done}개" + (f" / 표에 없는 대사 {len(miss)}종" if miss else ""))
    for q, n in list(miss.items())[:10]:
        print(f"   미등록 x{n}: {q[:40]!r}")
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장에 반영했다")
    else:
        print("(--apply 를 붙여야 반영된다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
