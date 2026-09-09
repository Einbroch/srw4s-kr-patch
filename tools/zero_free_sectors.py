#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ISO 디렉터리상 **미할당**인 섹터의 사용자 데이터를 0 으로 비운다.

파일을 트랙 꼬리로 옮기면 원래 자리에 옛 바이트가 남는다. 디렉터리가 그 자리를
가리키지 않으므로 게임은 읽지 않지만, `patch_image_reloc.py --grow` 는 "비어 있지
않다"며 거부한다. 이 도구가 그 자리를 0 으로 만들어 확대 경로를 연다.

**안전 장치**: 지우려는 섹터가 리스팅의 어떤 파일 범위와도 겹치면 실패한다.
디렉터리가 할당의 정본이다.
"""
from __future__ import annotations
import argparse
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "reference" / "srwcb-korean-patch" / "tools"))

from isotool import RAW, HDR, USER                     # noqa: E402
from patch_image_resize import load_listing            # noqa: E402
from patch_raw_track_exes import rebuild_mode2_form1   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--listing", default=str(ROOT / "records" / "iso-listing.txt"))
    ap.add_argument("--from-lba", type=int, required=True)
    ap.add_argument("--to-lba", type=int, required=True, help="포함")
    args = ap.parse_args()

    files, _ = load_listing(Path(args.listing))
    for name, (lba, size) in files.items():
        end = lba + max(1, math.ceil(size / USER))
        if lba <= args.to_lba and end > args.from_lba:
            print(f"FAIL {name}(LBA {lba}..{end-1})가 지우려는 범위와 겹친다")
            return 1

    out = Path(args.out)
    if str(out) != args.source:
        shutil.copyfile(args.source, out)
        print(f"복사: {Path(args.source).name} -> {out.name}")

    n = 0
    with out.open("r+b") as fh:
        for lba in range(args.from_lba, args.to_lba + 1):
            fh.seek(lba * RAW)
            sector = bytearray(fh.read(RAW))
            if all(b == 0 for b in sector[HDR:HDR + USER]):
                continue
            sector[HDR:HDR + USER] = bytes(USER)
            rebuild_mode2_form1(sector)
            fh.seek(lba * RAW)
            fh.write(sector)
            n += 1
    print(f"미할당 섹터 {args.from_lba}..{args.to_lba} 중 {n}개를 0 으로 비웠다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
