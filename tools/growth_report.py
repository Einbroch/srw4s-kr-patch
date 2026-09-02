#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""레코드별 바이트 증가분 보고서 — 어디를 줄여야 슬롯에 들어가는지.

원문 대비 늘어난 바이트를 세고, 줄이기 쉬운 순(산문/메뉴 > 고유명사)으로 보여준다.
이름류는 용어 통일을 마친 뒤라 건드리지 않는다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections   # noqa: E402

ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 2, 0xFD: 2, 0xFE: 1}


def toklen(d: bytes, p: int) -> int:
    q = p
    while q < len(d):
        b = d[q]
        if b == 0xFF:
            return q + 1 - p
        q += 1 if b < 0xF0 else (2 if b <= 0xF5 else 1 + ARITY[b])
    return 0


def main() -> int:
    only = {int(x) for x in sys.argv[1].split(",")} if len(sys.argv) > 1 else None
    o = (ROOT / "extract" / "DAT" / "D_NAMES.BIN").read_bytes()
    n = (ROOT / "build" / "D_NAMES_ko.BIN").read_bytes()
    remap = {int(k, 16): int(v, 16)
             for k, v in json.loads((ROOT / "build" / "dnames_remap.json").read_text()).items()}
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    led = {r["id"]: r for r in L["records"]}

    rows = []
    for s in dnames_sections(o):
        if s.get("status") == "null":
            continue
        i = s["section"]
        if only is not None and i not in only:
            continue
        for st in s["strings"]:
            p = st["pointer"]
            if p not in remap:
                continue
            d = toklen(n, remap[p]) - (len(st["raw"]) + 1)
            if d > 0:
                rows.append((d, i, p))
    rows = sorted(set(rows), reverse=True)

    out, tot = [], 0
    for d, i, p in rows:
        tot += d
        r = led.get(f"DN:{p:04X}")
        out.append(f"### DN:{p:04X}  S{i:02d}  +{d}B")
        if r:
            for k, sp in enumerate(r["spans"]):
                ko = sp.get("ko") or ""
                if ko:
                    out.append(f"  [{k:2d}] ({len(ko):2d}자) {ko}")
        out.append("")
    dst = ROOT / "translation" / "_growth_report.md"
    dst.write_text(f"# 증가 레코드 {len(rows)}개 / 합계 +{tot:,}B\n\n" + "\n".join(out),
                   encoding="utf-8")
    print(f"{len(rows)}레코드 / 합계 +{tot:,}B -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
