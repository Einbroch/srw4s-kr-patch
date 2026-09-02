#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C_DEMOG 한글판 빌드 — 폰트 두 번째 사본에 글꼴 주입 (크기 불변)."""
from __future__ import annotations
import hashlib, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from font_inject import COPIES, inject, load_alloc, bank_hashes   # noqa: E402
from hangul_font import HangulFont                                 # noqa: E402


def main() -> int:
    name, src, dst, offs = [c for c in COPIES if c[0] == "C_DEMOG"][0]
    ref_name, ref_src, _, ref_offs = [c for c in COPIES if c[0] == "STAYDAT"][0]
    d = bytearray((ROOT / "extract" / src).read_bytes())
    ref = (ROOT / "extract" / ref_src).read_bytes()
    # Expected Write: 두 사본의 세 뱅크가 원본에서 바이트 동일해야 한다
    a, b = bank_hashes(bytes(d), offs), bank_hashes(ref, ref_offs)
    if a != b:
        print("FAIL: 두 폰트 사본의 뱅크가 원본에서 다르다", a, b)
        return 1
    n = inject(d, offs, load_alloc(), HangulFont())
    out = ROOT / "build" / dst
    out.write_bytes(bytes(d))
    print(f"글리프 {n}자 주입 -> {dst}")
    print(f"C_DEMOG {len(d):,}B  sha {hashlib.sha256(bytes(d)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
