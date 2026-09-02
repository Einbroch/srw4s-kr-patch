#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""페이지 단위 역문 교체 — {(레코드id, 페이지번호): 새 페이지} 를 담은 파이썬 파일을 받는다.

원장과 배치 TSV 를 함께 갱신한다(배치가 재조판의 정본이므로 둘 다 맞춰야 한다).
"""
from __future__ import annotations
import glob, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = "# id\tjp\tko"


def main() -> int:
    ns: dict = {}
    exec(Path(sys.argv[1]).read_text(encoding="utf-8"), ns)
    fix = ns["FIX"]
    p = ROOT / "translation" / "mbanks_ledger.json"
    L = json.loads(p.read_text(encoding="utf-8"))
    new: dict[str, str] = {}
    for r in L["records"]:
        pg = r["ko"].split("{P}") if r["ko"] else []
        hit = False
        for (rid, i), s in fix.items():
            if rid == r["id"] and i < len(pg):
                pg[i] = s
                hit = True
        if hit:
            r["ko"] = "{P}".join(pg)
            new[r["id"]] = r["ko"]
    p.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in glob.glob(str(ROOT / "translation" / "batches" / "*.tsv")):
        rows = Path(f).read_text(encoding="utf-8").splitlines()
        if not rows or rows[0].rstrip("\r") != HEADER:
            continue
        out, n = [rows[0]], 0
        for line in rows[1:]:
            q = line.rstrip("\r").split("\t")
            if len(q) >= 3 and q[0] in new and q[2] != new[q[0]]:
                q[2] = new[q[0]]
                n += 1
            out.append("\t".join(q))
        if n:
            Path(f).write_text("\n".join(out) + "\n", encoding="utf-8")
    miss = {rid for rid, _ in fix} - set(new)
    print(f"{len(new)}개 레코드 갱신" + (f" / 못 찾음 {sorted(miss)}" if miss else ""))
    return 1 if miss else 0


if __name__ == "__main__":
    raise SystemExit(main())
