#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""마크업 왕복 게이트: encode(jp) 가 원본 raw 와 바이트 동일해야 한다."""
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode, markers   # noqa: E402

L = json.loads((ROOT / "translation" / "mbanks_ledger.json").read_text(encoding="utf-8"))
enc = build_encoder()
ok = bad = keyerr = 0
badids: list[str] = []
misschar: Counter = Counter()
for r in L["records"]:
    raw = bytes.fromhex(r["raw_hex"])
    try:
        got = encode(r["jp"], enc)
    except KeyError as e:
        keyerr += 1
        misschar[e.args[0]] += 1
        continue
    if got == raw:
        ok += 1
    else:
        bad += 1
        if len(badids) < 8:
            badids.append(r["id"])
print(f"레코드 {len(L['records']):,}개")
print(f"  왕복 일치 {ok:,}  불일치 {bad:,}  인코딩 불가 {keyerr:,}")
if misschar:
    print(f"  문자표에 없는 글자 {len(misschar)}종: {''.join(list(misschar)[:30])!r}")
if badids:
    print(f"  불일치 예: {badids}")
print("PASS" if bad == 0 and keyerr == 0 else "FAIL")
raise SystemExit(0 if bad == 0 and keyerr == 0 else 1)
