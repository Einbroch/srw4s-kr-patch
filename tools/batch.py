#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""번역 배치 내보내기/병합.

배치 파일에는 보호 스냅샷(record id, span 좌표, 원문)을 함께 실어 보낸다. 병합할 때
현재 원장의 보호 필드와 대조해 다르면 stale로 차단한다 — Agent 응답이 보호 영역을
덮어쓰지 못하게 하는 장치다(`translation-artifacts.md` §1).

형식: TSV  `id<TAB>start<TAB>end<TAB>jp<TAB>ko`
개행은 `\n`, 탭은 `\t`로 이스케이프한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "translation" / "dnames_ledger.json"


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\t", "\t").replace("\n", "\n")


def unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append({"t": "\t", "n": "\n", "\\": "\\"}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def sections_of(rec) -> set[str]:
    return {o.split(":")[0] for o in rec["owners"]}


def cmd_export(args) -> int:
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    want = set(args.sections.split(",")) if args.sections else None
    rows = []
    for rec in L["records"]:
        if want and not (sections_of(rec) & want):
            continue
        for s in rec["spans"]:
            if s["ko"] and not args.include_translated:
                continue
            rows.append((rec["id"], s["start"], s["end"], s["jp"]))
    rows.sort(key=lambda r: (-(r[2] - r[1]), r[0]))
    if args.limit:
        rows = rows[: args.limit]
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("# id\tstart\tend\tjp\tko   (ko 열만 채운다. 다른 열은 보호 필드)\n")
        for rid, a, b, jp in rows:
            fh.write(f"{rid}\t{a}\t{b}\t{esc(jp)}\t\n")
    print(f"내보낸 span {len(rows)}개 -> {out}")
    print(f"  원문 바이트 합계 {sum(b-a for _,a,b,_ in rows)}")
    return 0


def cmd_merge(args) -> int:
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    index = {(r["id"], s["start"], s["end"]): s for r in L["records"] for s in r["spans"]}
    applied = skipped = stale = 0
    for line in Path(args.batch).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        rid, a, b, jp, ko = parts[0], int(parts[1]), int(parts[2]), unesc(parts[3]), unesc(parts[4])
        s = index.get((rid, a, b))
        if s is None:
            stale += 1
            continue
        if s["jp"] != jp:
            stale += 1
            continue
        if not ko.strip():
            skipped += 1
            continue
        s["ko"] = ko
        s["status"] = args.status
        s["note"] = args.note
        applied += 1
    LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"병합: 적용 {applied} / 빈칸 {skipped} / stale·미매칭 {stale}")
    return 1 if stale else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--out", required=True)
    e.add_argument("--sections", default="")
    e.add_argument("--limit", type=int, default=0)
    e.add_argument("--include-translated", action="store_true")
    e.set_defaults(func=cmd_export)
    m = sub.add_parser("merge")
    m.add_argument("--batch", required=True)
    m.add_argument("--status", default="needs_review")
    m.add_argument("--note", default=None)
    m.set_defaults(func=cmd_merge)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
