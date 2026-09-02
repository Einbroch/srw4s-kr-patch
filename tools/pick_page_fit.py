#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""후보 여러 개 중 3줄에 드는 첫 판을 골라 페이지 교체안(FIX)을 만든다.

한국어는 어절 단위로 끊어서 줄마다 40~90px 가 남는다 — 총 폭이 한도 안이어도
줄 수가 넘칠 수 있다. 그래서 폭이 아니라 **실제 줄 수**로 고른다.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder            # noqa: E402
from mb_layout import _split_line, PAGE_LINES  # noqa: E402
from reflow_ko import flatten                  # noqa: E402


def main() -> int:
    ns: dict = {}
    exec(Path(sys.argv[1]).read_text(encoding="utf-8"), ns)
    enc = build_encoder()
    out, bad = [], 0
    for key, cands in ns["CAND"].items():
        for c in cands:
            n = len(_split_line(flatten(c), enc))
            if n <= PAGE_LINES:
                out.append((key, c))
                print(f"  {key[0]} p{key[1]}  {n}줄  {c}")
                break
        else:
            bad += 1
            print(f"!! {key[0]} p{key[1]} 후보 전부 4줄 이상 "
                  f"(최소 {min(len(_split_line(flatten(c), enc)) for c in cands)}줄)")
    dst = Path(sys.argv[2])
    dst.write_text("# -*- coding: utf-8 -*-\nFIX = {\n" +
                   "".join(f"{k!r}:{v!r},\n" for k, v in out) + "}\n", encoding="utf-8")
    print(f"-> {dst}  (통과 {len(out)} / 실패 {bad})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
