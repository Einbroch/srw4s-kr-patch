#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""역문 안의 문자열을 배치 TSV(정본)에서 치환한다.

    ko_replace.py rules.json     # [{"id":"MB:xxxxx","from":"...","to":"..."}, ...]

이름 표식 `{B:xxxx}` 뒤에 조사가 붙으면 이름의 받침을 알 수 없어 틀린 조사가 나온다.
`{B:1E80}라고` -> `{B:1E80} 이라고` 처럼 받침과 무관한 형태로 바꾸는 데 쓴다.
"""
from __future__ import annotations
import glob, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAB = "\t"
HEADER = "# id" + TAB + "jp" + TAB + "ko"


def main() -> int:
    rules = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    by_id = {}
    for r in rules:
        by_id.setdefault(r["id"], []).append((r["from"], r["to"]))
    hit, miss = 0, set(by_id)
    for f in sorted(glob.glob(str(ROOT / "translation" / "batches" / "mb_*.tsv"))
                    + glob.glob(str(ROOT / "translation" / "mb_batches" / "*.tsv"))):
        rows = Path(f).read_text(encoding="utf-8").splitlines()
        if not rows or rows[0].rstrip("\r") != HEADER:
            continue
        out, n = [rows[0]], 0
        for line in rows[1:]:
            q = line.rstrip("\r").split(TAB)
            if len(q) >= 3 and q[0] in by_id and q[2].strip():
                new = q[2]
                for a, b in by_id[q[0]]:
                    if a in new:
                        new = new.replace(a, b)
                if new != q[2]:
                    q[2] = new; n += 1; miss.discard(q[0])
            out.append(TAB.join(q))
        if n:
            Path(f).write_text("\n".join(out) + "\n", encoding="utf-8"); hit += n
    print(f"치환 {hit}행 / 규칙 {len(rules)}개")
    if miss:
        print("FAIL: 적용 안 된 id:", sorted(miss))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
