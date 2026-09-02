#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 주소 계산 훅 — 뱅크 베이스 마스크를 없앤다.

원래 (MAP 오버레이 RAM 0x801540A0~)
    a2 = header[bank] & 0xFFFF0000     ; 뱅크 베이스가 64KiB 경계에 묶인다
    offset = a2 + rel                  ; rel 은 u16

바꾼 뒤
    a2 = header[bank]                  ; **표가 놓인 자리가 곧 베이스**
    offset = a2 + rel

이러면 뱅크를 64KiB 경계에 맞출 필요가 없어져, `[표][그 표의 구간들]` 을 독립 블록으로
어디에나 놓을 수 있다. 표가 블록 맨 앞이므로 rel >= 0x200 이 보장되고,
블록이 64KiB 만 넘지 않으면 된다(실측 최대 39,460 B).

명령 두 줄만 nop 으로 바꾼다. `lui $v0,0xFFFF` 가 싣던 $v0 는 바로 다음 줄(0x801540AC)에서
덮어쓰이므로 지워도 안전하다.

  주소        원본                   바꾼 것
  0x801540A4  lui $v0,0xFFFF         nop
  0x801540A8  and $a2,$a2,$v0        nop

**주의**: 부팅 시 표를 읽는 루프(0x80153F8C~)는 `header[bank]` 를 그대로 파일 오프셋으로
쓰므로 손댈 필요가 없다. 그쪽은 원래부터 마스크를 쓰지 않는다.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELTA = 0x80106380                     # MAP 해제물 offset + DELTA = RAM

PATCH = [
    (0x801540A4, 0x3C02FFFF, 0x00000000, "nop (lui $v0,0xFFFF 제거)"),
    (0x801540A8, 0x00C23024, 0x00000000, "nop (and $a2,$a2,$v0 제거)"),
]


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "MAP_orig.dec"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "build" / "MAP_hook.dec"
    d = bytearray(src.read_bytes())
    for ram, old, new, note in PATCH:
        off = ram - DELTA
        cur = struct.unpack_from("<I", d, off)[0]
        if cur != old:
            print(f"FAIL: {ram:#010x} (파일 {off:#07x}) 가 {cur:08X}, 기대 {old:08X}")
            return 1
        struct.pack_into("<I", d, off, new)
        print(f"  {ram:#010x}  {old:08X} -> {new:08X}  {note}")
    dst.write_bytes(bytes(d))
    print(f"-> {dst.name}  {len(d):,}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
