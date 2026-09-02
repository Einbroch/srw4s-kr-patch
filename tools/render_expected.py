#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""패치된 STAYDAT의 실제 글꼴로 문자열을 그린다.

왜 필요한가: 16x16 비트맵 한글·한자는 PS1 해상도에서 자형이 압축돼 **스크린샷 육안 판독이
믿을 수 없다.** 실제로 `이름`을 `0틑`로, `까`를 `刀`로, `4月14日`을 `4들14ㅂ`로 오독해
멀쩡한 빌드를 세 번이나 "깨졌다"고 잘못 진단했다. 렌더 판정은 반드시 이 도구로 기대 문자열을
그려 화면과 대조한다.

  python tools/render_expected.py "주인공설정" out.png [--scale 8]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from span_classify import charmap  # noqa: E402

STAY = ROOT / "build" / "STAYDAT_ko.BIN"
LOW, MID = 0x36838, 0x37838


def encoder() -> dict[str, int]:
    cm = charmap()
    enc: dict[str, int] = {}
    for gid, ch in sorted(cm.items()):
        if ch and ch not in enc:
            enc[ch] = gid
    enc[" "] = 0x000
    enc["\u3000"] = 0x3FF
    alloc = json.loads((ROOT / "translation" / "glyph_alloc.json").read_text(encoding="utf-8"))
    for ch, h in alloc["hangul"].items():
        enc[ch] = int(h, 16)
    return enc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("out")
    ap.add_argument("--scale", type=int, default=8)
    a = ap.parse_args()

    stay = STAY.read_bytes()
    enc = encoder()
    cells = []
    for ch in a.text:
        gid = enc.get(ch)
        if gid is None:
            print(f"  ! 문자표에 없음: {ch!r}")
            cells.append((None, 8))
            continue
        if gid < 0x100:                       # 8x16 반각
            off = LOW + gid * 16
            cells.append((stay[off:off + 16], 8))
        else:                                 # 16x16 전각
            off = MID + (gid - 0x100) * 32
            cells.append((stay[off:off + 32], 16))
    w = sum(c[1] for c in cells)
    im = Image.new("L", (max(w, 1), 16), 0)
    px = im.load()
    x = 0
    for data, cw in cells:
        if data:
            for y in range(16):
                for i in range(8):
                    if (data[y] >> (7 - i)) & 1:
                        px[x + i, y] = 255
                    if cw == 16 and (data[16 + y] >> (7 - i)) & 1:
                        px[x + 8 + i, y] = 255
        x += cw
    im.resize((im.width * a.scale, 16 * a.scale), Image.NEAREST).save(a.out)
    print(f"{a.text!r} -> {a.out}  ({w}px 폭, {len(a.text)}자)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
