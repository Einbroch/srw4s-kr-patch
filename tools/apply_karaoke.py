#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""가라오케 가사 역문을 D_NAMES 원장에 넣는다.

역문은 `records/karaoke_lyrics.tsv` 의 `ko` 칸에서 읽는다(사용자가 채운 것).
곡 제목·기체명 7줄은 이미 원장에 더 나은 역문이 있으므로 **그쪽을 지킨다**
(줄인 판이 `마징가Z` -> `마징가` 처럼 고유명사를 깎아 놓았다).

넣기 전에 줄마다 인코딩해 원문 스팬 바이트를 넘지 않는지 확인하고, 폰트에 없는
음절은 남은 글리프 칸에 새로 배정한다.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

TSV = ROOT / "records" / "karaoke_lyrics.tsv"
LEDGER = ROOT / "translation" / "dnames_ledger.json"
ALLOC = ROOT / "translation" / "glyph_alloc.json"

# 2026-09-02 재번역본은 제목 7줄도 온전하다 — 되돌릴 것이 없다.
KEEP: dict[str, str] = {}


def main() -> int:
    apply = "--apply" in sys.argv
    from mb_codec import build_encoder, encode
    enc = build_encoder()

    rows = list(csv.DictReader(TSV.open(encoding="utf-8"), delimiter="\t"))
    ko_of = {r["id"]: KEEP.get(r["id"], (r["ko"] or "").strip()) for r in rows}
    jp_of = {r["id"]: r["jp"] for r in rows}

    # 빈 칸은 건드리지 않는다 — 원장에 이미 있는 역문을 지우면 그 줄이 일본어로 돌아간다
    blank = sorted(k for k, v in ko_of.items() if not v)
    if blank:
        print(f"역문이 비어 있어 건너뛴 줄 {len(blank)}개: {' '.join(blank)}")
        for k in blank:
            ko_of.pop(k)

    # 폰트에 없는 음절 배정
    alloc = json.loads(ALLOC.read_text(encoding="utf-8"))
    used = {int(v, 16) for v in alloc["hangul"].values()}
    pres = {int(k, 16) for k in alloc["preserved_ids"]}
    free = [g for g in range(0x100, 0x700) if g not in used and g not in pres]
    need = sorted({c for s in ko_of.values() for c in s
                   if 0xAC00 <= ord(c) <= 0xD7A3 and c not in alloc["hangul"]})
    if len(need) > len(free):
        print(f"FAIL: 새 글리프 {len(need)}자가 필요한데 빈 칸은 {len(free)}개")
        return 1
    for c, g in zip(need, free):
        alloc["hangul"][c] = f"0x{g:03X}"
        enc[c] = g
    print(f"새 글리프 {len(need)}자 배정: {''.join(need)}  (남는 칸 {len(free) - len(need)})")

    # 길이 검사
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    bad, hit, jpb, kob = [], 0, 0, 0
    for r in L["records"]:
        ko = ko_of.get(r["id"])
        if ko is None:
            continue
        for s in r["spans"]:
            if s["jp"] != jp_of[r["id"]]:
                continue
            n = s["end"] - s["start"]
            b = len(encode(ko, enc)) - 1
            jpb += n
            kob += b
            if b > n:
                bad.append((r["id"], n, b, ko))
            if apply:
                s["ko"] = ko
                s["status"] = "needs_review"
            hit += 1
    print(f"대상 스팬 {hit}개 / 원문 {jpb:,} B -> 역문 {kob:,} B ({kob - jpb:+,} B)")
    # 레코드는 늘어나도 된다 — 한도는 스팬이 아니라 D_NAMES 총량(53,248 B)이고
    # `build_staydat_ko.py` 가 그걸 검사한다. 여기서는 늘어난 줄만 알려 준다.
    if bad:
        print(f"원문보다 길어진 줄 {len(bad)}개 (총량이 줄었으므로 통과)")
        for i, n, b, ko in bad[:10]:
            print(f"   {i} {n} -> {b} B  {ko}")
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        ALLOC.write_text(json.dumps(alloc, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장·글리프 배정 반영")
    else:
        print("(--apply 를 붙여야 반영된다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
