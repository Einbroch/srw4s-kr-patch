#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""후보 문자열이 실제로 어떻게 끊기는지 보여 준다 (줄바꿈 자리를 눈으로 고르기 위한 것)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder                      # noqa: E402
from mb_layout import _split_line, atom_px, atoms       # noqa: E402
from reflow_ko import flatten                           # noqa: E402


def main() -> int:
    enc = build_encoder()
    for s in sys.argv[1:]:
        lines = _split_line(flatten(s), enc)
        print(f"{len(lines)}줄")
        for ln in lines:
            print(f"   {sum(atom_px(a, enc) for a in atoms(ln)):4d}  {ln}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
