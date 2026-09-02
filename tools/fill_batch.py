#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""번역 사전(KO = {레코드id: 역문})을 배치 TSV 의 ko 열에 채운다."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = "# id\tjp\tko"


def main() -> int:
    ns: dict = {}
    exec(Path(sys.argv[1]).read_text(encoding="utf-8"), ns)
    ko = ns["KO"]
    f = Path(sys.argv[2])
    if not f.is_absolute():
        f = ROOT / f
    rows = f.read_text(encoding="utf-8").splitlines()
    if rows[0].rstrip("\r") != HEADER:
        print(f"헤더가 다르다: {rows[0]!r}")
        return 1
    out, n, miss = [rows[0]], 0, []
    for line in rows[1:]:
        q = line.rstrip("\r").split("\t")
        if len(q) >= 3:
            if q[0] in ko:
                q[2] = ko[q[0]]
                n += 1
            elif not q[2].strip():
                miss.append(q[0])
        out.append("\t".join(q))
    f.write_text("\n".join(out) + "\n", encoding="utf-8")
    extra = set(ko) - {l.split("\t")[0] for l in rows[1:]}
    print(f"채움 {n}행 / 빈칸으로 남긴 것 {len(miss)}", miss[:8])
    if extra:
        print(f"!! 배치에 없는 id {sorted(extra)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
