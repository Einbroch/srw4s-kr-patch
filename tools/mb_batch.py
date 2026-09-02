#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 번역 배치 내보내기/병합 (D_NAMES batch.py와 같은 규약).

내보내기 우선순위: closure 도달분 -> 참조 슬롯이 많은 것 -> 짧은 것.
병합 시 원장의 보호 필드(jp)와 대조해 다르면 stale로 차단한다.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "translation" / "mbanks_ledger.json"


def load():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def export(args):
    L = load()
    import re as _re
    strip = lambda t: _re.sub(r"\{[^}]*\}", "", t)
    want = int(str(args.table).lstrip("Hh")) if args.table is not None else None
    rows = []
    for r in L["records"]:
        if args.live_only and not r["live"]:
            continue
        if r["ko"]:
            continue
        n = len(strip(r["jp"]))
        if not (args.min_len <= n <= args.max_len):
            continue
        if want is None:
            rows.append((-len(r["owners"]), n, r["id"], r["jp"]))
            continue
        # 표를 지정하면 슬롯 순 = 장면 진행 순으로 내보낸다
        slots = [int(o.split(":")[1][1:]) for o in r["owners"]
                 if int(o.split(":")[0][1:]) == want]
        if slots:
            rows.append((min(slots), n, r["id"], r["jp"]))
    rows.sort()
    rows = rows[:args.limit]
    p = Path(args.out)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# id\tjp\tko\n")
        for _, _, rid, jp in rows:
            fh.write(rid + chr(9) + jp + chr(9) + chr(10))
    print(f"{len(rows)}개 span -> {p}")
    return 0


def merge(args):
    L = load()
    idx = {r["id"]: r for r in L["records"]}
    ok = stale = blank = 0
    bp = Path(args.batch)
    if not bp.is_absolute():
        bp = ROOT / bp
    for line in bp.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.rstrip("\r").split("\t")
        if len(f) < 3:
            continue
        rid, jp, ko = f[0], f[1], f[2]
        s = idx.get(rid)
        if s is None or s["jp"] != jp:
            stale += 1
            continue
        if not ko.strip():
            blank += 1
            continue
        # 글꼴에 없는 문자를 미리 잡는다. `~`(U+007E) 는 없고 `〜`(U+301C) 만 있다.
        ko = ko.replace("~", "〜").replace("～", "〜")
        ko = ko.replace("—", "-").replace("–", "-").replace("…", "...")
        s["ko"] = ko
        s["status"] = args.status
        s["note"] = args.note
        ok += 1
    LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"병합: 적용 {ok} / 빈칸 {blank} / stale·미매칭 {stale}")
    return 0


def stats(args):
    L = load()
    tot = live = tk = lk = 0
    for r in L["records"]:
        tot += 1
        if r["ko"]:
            tk += 1
        if r["live"]:
            live += 1
            if r["ko"]:
                lk += 1
    print(f"전체 레코드 {tot:,} / 역문 {tk:,} ({tk/tot*100:.1f}%)")
    print(f"closure {live:,} / 역문 {lk:,} ({lk/live*100:.1f}%)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("--out", required=True)
    e.add_argument("--table", default=None, help="H55 처럼 표를 지정하면 슬롯(장면) 순으로 내보낸다")
    e.add_argument("--limit", type=int, default=300)
    e.add_argument("--min-len", type=int, default=1)
    e.add_argument("--max-len", type=int, default=999)
    e.add_argument("--live-only", action="store_true")
    e.set_defaults(fn=export)
    m = sub.add_parser("merge"); m.add_argument("--batch", required=True)
    m.add_argument("--status", default="needs_review"); m.add_argument("--note", default=None)
    m.set_defaults(fn=merge)
    s = sub.add_parser("stats"); s.set_defaults(fn=stats)
    a = ap.parse_args()
    raise SystemExit(a.fn(a))
