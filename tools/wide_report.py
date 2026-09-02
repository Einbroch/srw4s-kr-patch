#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""폭 초과 런 보고서 — 어느 레코드의 어느 줄을 몇 칸 줄여야 하는지.

advance 모델은 도너에서 가져온 것이라 절대값을 믿지 않는다. 여기서는 **원문 대비 초과분**
만 쓴다(같은 모델로 양쪽을 재므로 차이는 의미가 있다). 1칸 ≈ 한글 1자 ≈ 2 B.
"""
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

W = json.loads((ROOT / "translation" / "_wide_runs.json").read_text(encoding="utf-8"))
L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
led = {r["id"]: r for r in L["records"]}

per = defaultdict(int)
for rid, op, ao, an in W:
    per[rid] += an - ao

lines = []
total = 0
for rid, over in sorted(per.items(), key=lambda x: -x[1]):
    r = led.get(rid)
    if not r:
        continue
    total += over
    sec = r["owners"][0].split(":")[0] if r["owners"] else "?"
    lines.append(f"### {rid}  {sec}  초과 {over}칸 (≈{over*2}B)")
    for i, sp in enumerate(r["spans"]):
        ko = sp.get("ko") or ""
        if ko:
            lines.append(f"  [{i:2d}] ({len(ko):2d}자) {ko}")
    lines.append("")
out = ROOT / "translation" / "_wide_report.md"
out.write_text(f"# 폭 초과 {len(per)}레코드 / 합계 {total}칸 (≈{total*2}B)\n\n" + "\n".join(lines),
               encoding="utf-8")
print(f"{len(per)}레코드 / 합계 {total}칸 ≈ {total*2}B -> {out}")
