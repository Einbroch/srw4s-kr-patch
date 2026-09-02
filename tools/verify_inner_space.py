#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""원문의 **글자 사이 공백**이 역문에서 사라졌는지 본다.

왜 필요한가
  공백 글리프는 `0x000` 이고 charmap 은 이 자리를 **빈 문자열**로 준다. 그래서 추출 단계에서
  원문의 공백이 통째로 사라지고, 번역자는 처음부터 붙어 있는 문장을 보게 된다.
  (2026-08-24 실기: 생일 입력 화면의 `1 2 3 4 5 決定` 이 `12345결정` 이 되어
   커서 보폭과 글자 위치가 어긋났다. 커서는 원문 간격을 기준으로 움직인다.)

끝쪽 공백은 칸 채우기라 무해하므로 **가운데 공백만** 센다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from span_classify import charmap      # noqa: E402
from text_codec import parse_record    # noqa: E402


def main() -> int:
    cm = dict(charmap())
    cm[0] = " "
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    bad = []
    for r in L["records"]:
        raw = bytes.fromhex(r["raw_hex"])
        toks = None
        for cand in (raw, raw + bytes([0xFF])):
            try:
                toks = parse_record(cand)
                break
            except Exception:
                pass
        if toks is None:
            continue
        pos, mp = 0, {}
        for t in toks:
            mp[pos] = t
            pos += len(t.raw)
        for k, s in enumerate(r["spans"]):
            ko = (s.get("ko") or "").strip()
            if not ko:
                continue
            st, en = s.get("start"), s.get("end")
            if st is None or en is None:
                continue
            txt, p = "", st
            while p < en and p in mp:
                t = mp[p]
                txt += cm.get(t.glyph_id, "?") if t.kind == "glyph" else "\x00"
                p += len(t.raw)
            ja = txt.strip()
            if ja.count(" ") > ko.count(" "):
                bad.append((ja.count(" ") - ko.count(" "), r["id"], k, ja, ko))
    bad.sort(reverse=True)
    for d, rid, k, ja, ko in bad:
        print(f"  -{d} {rid}[{k}]  원문={ja[:40]!r}  ko={ko[:40]!r}")
    print(f"가운데 공백이 빠진 span {len(bad)}개")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
