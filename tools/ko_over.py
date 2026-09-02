#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3줄을 넘긴 역문 페이지를 폭과 함께 보여 준다 (줄일 분량 판단용)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder                      # noqa: E402
from mb_layout import violations, atom_px, atoms, LINE_PX, PAGE_LINES  # noqa: E402
from reflow_ko import NO_REFLOW                                        # noqa: E402

enc = build_encoder()
L = json.loads((ROOT / "translation" / "mbanks_ledger.json").read_text(encoding="utf-8"))
cap = LINE_PX * PAGE_LINES
for r in L["records"]:
    if not r["ko"] or r["id"] in NO_REFLOW:
        continue
    _, deep = violations(r["ko"], enc)
    if not deep:
        continue
    pgs = r["ko"].split("{P}")
    for pi, cnt in deep:
        flat = pgs[pi].replace("{N}", " ")
        px = sum(atom_px(a, enc) for a in atoms(pgs[pi]))
        print(f'{r["id"]} p{pi} {cnt}줄 {px}px (한도 {cap}, 여유 {cap-px:+d})')
        print(f'   {flat}')
