#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_DEDMES 를 옮겨 D_NAMES 슬롯을 2 KB 넓힌다.

STAYDAT 상주 blob 배치
    before   0x49800 [D_NAMES 53,248] 0x56800 [D_DEDMES 1,166] 0x57000 [D_UNIT]
    after    0x49800 [D_NAMES 55,296 ............................] 0x57000 [D_UNIT]
                                        D_DEDMES -> 0x5D000 (IP.BIN 뒤 잔재 구간)

blob 의 RAM 주소는 코드가 아니라 **MAP 해제물의 주소표**에 들어 있다
(`0x58F68`~, RAM `0x8015F2E8`~). D_DEDMES 슬롯은 `0x58FB4`. 실행 파일·MAP·BATTLE
어디에도 이 주소를 만드는 `lui/addiu` 도, 리터럴도 없다 — 표를 거치는 길 하나뿐이라
u32 하나만 바꾸면 된다.

옮길 자리 `0x5D000` 은 IP.BIN 끝(`0x5C87F`)과 SC_04(`0x62000`) 사이 22 KB 구간이다.
주소표 어느 칸도 이 구간을 가리키지 않고, 세 파일 어디에도 주소 리터럴이 없다.
개발 잔재로 보이지만 **확신은 실기에서만 나온다** — 배포 후 부팅·가라오케 확인 필요.

파일 크기는 변하지 않는다. STAYDAT 도 MAP 해제물도 그대로다.
"""
from __future__ import annotations
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

DELTA = 0x80106380                 # MAP 해제물 offset + DELTA = RAM
SLOT = 0x58FB4                     # D_DEDMES 주소 칸 (RAM 0x8015F334)
OLD, NEW = 0x80076800, 0x8007D000


def main() -> int:
    from lzb import decompress
    from lzb_encode import compress

    src = ROOT / "build" / "MAP_hook.dec"
    d = bytearray(src.read_bytes())
    cur = struct.unpack_from("<I", d, SLOT)[0]
    if cur == NEW:
        print("이미 옮겨져 있다")
    elif cur != OLD:
        print(f"FAIL: MAP {SLOT:#07x} 가 {cur:08X}, 기대 {OLD:08X}")
        return 1
    else:
        struct.pack_into("<I", d, SLOT, NEW)
        print(f"  MAP {SLOT:#07x} (RAM {DELTA + SLOT:#010x})  {OLD:08X} -> {NEW:08X}")
        src.write_bytes(bytes(d))

    comp = compress(bytes(d))
    back, _ = decompress(comp)
    if bytes(back) != bytes(d):
        print("FAIL: 재압축 왕복 불일치")
        return 1
    out = ROOT / "build" / "MAP_hook.LZB"
    prev = out.stat().st_size if out.exists() else 0
    out.write_bytes(comp)
    print(f"-> {out.name}  {prev:,} -> {len(comp):,} B  (해제 {len(d):,} B, 왕복 확인)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
