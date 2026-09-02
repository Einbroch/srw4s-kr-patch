#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""역문 수정을 **배치 TSV(정본)** 에 반영한다. 페이지 단위로 지정한다.

    apply_ko_fix.py fix.json      # {"MB:xxxxx": {"0": "새 본문", ...}, ...}

원장을 직접 고치면 `reflow_ko.py` 가 배치에서 다시 읽어 되돌린다 — 정본은 배치다.
"""
from __future__ import annotations
import glob, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAB = "\t"
HEADER = "# id" + TAB + "jp" + TAB + "ko"


def main() -> int:
    fix = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    L = json.loads((ROOT / "translation" / "mbanks_ledger.json").read_text(encoding="utf-8"))
    idx = {r["id"]: r for r in L["records"]}
    full = {}
    for rid, pages in fix.items():
        r = idx.get(rid)
        if r is None or not r["ko"]:
            print(f"FAIL: {rid} 없음/미번역")
            return 1
        pg = r["ko"].split("{P}")
        for k, txt in pages.items():
            i = int(k)
            if i >= len(pg):
                print(f"FAIL: {rid} p{i} 없음 (페이지 {len(pg)}개)")
                return 1
            pg[i] = txt
        full[rid] = "{P}".join(x.replace("{N}", " ") for x in pg)
    hit, files = 0, 0
    for f in sorted(glob.glob(str(ROOT / "translation" / "batches" / "mb_*.tsv"))
                    + glob.glob(str(ROOT / "translation" / "mb_batches" / "*.tsv"))):
        rows = Path(f).read_text(encoding="utf-8").splitlines()
        if not rows or rows[0].rstrip("\r") != HEADER:
            continue
        out, n = [rows[0]], 0
        for line in rows[1:]:
            q = line.rstrip("\r").split(TAB)
            if len(q) >= 3 and q[0] in full and idx.get(q[0]) and idx[q[0]]["jp"] == q[1]:
                q[2] = full[q[0]]; n += 1
            out.append(TAB.join(q))
        if n:
            Path(f).write_text("\n".join(out) + "\n", encoding="utf-8")
            hit += n; files += 1
    missing = [r for r in full if r not in {q for q in full}]  # noqa
    print(f"배치 {files}개 파일 / {hit}행 갱신 / 대상 레코드 {len(full)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
