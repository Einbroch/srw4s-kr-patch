#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LZB 압축기 왕복 검증 — 원본 4개를 풀었다가 다시 압축해 **내용이 같은지** 본다.

이 프로젝트는 인코더가 없어 LZB 재삽입을 금지해 왔다. 이 검사를 통과해야 그 금지를 푼다.
크기가 원본보다 커도 무방하다(파일을 옮기면 된다). **내용 동일이 조건이다.**
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lzb            # noqa: E402
import lzb_encode     # noqa: E402

FILES = ["MAP.LZB", "MOVIE.LZB", "BTT/BATTLE.LZB", "BTT/M_BANKB.LZB"]


def main() -> int:
    bad = 0
    for rel in FILES:
        p = ROOT / "extract" / rel
        raw = p.read_bytes()
        dec, used = lzb.decompress(raw)
        enc = lzb_encode.compress(dec)
        back, _ = lzb.decompress(enc)
        ok = back == dec
        same = enc == raw[:used]
        print(f"{rel:18s} 원본 {used:8,}B -> 해제 {len(dec):8,}B -> 재압축 {len(enc):8,}B "
              f"({len(enc)/used:.2f}배)  왕복={ok}  원본과 동일={same}")
        if not ok:
            bad += 1
    print("PASS: 4개 전부 왕복 일치" if not bad else f"FAIL: {bad}개")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
