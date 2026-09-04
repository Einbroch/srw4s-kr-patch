#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BTT/BATTLE.LZB 한국어판 — M_BANKB 확장 구간을 오버레이에 써 넣는다.

M_BANKB 해제물(55,353 B)은 RAM 0x80107B8C 에 올라오고, 뱅크 표 슬롯이 **u16** 이라
블롭 시작에서 65,535 까지 가리킬 수 있다. 블롭 뒤 10,182 B 는 M_BANKB 파일이 아니라
**BATTLE 오버레이 이미지**(0x80106380 적재)의 일부다.

그 자리를 써도 되는지는 실기로 쟀다(`D:/srw4s_ko/readbp.lua`, 512 B x 43 조각에
읽기 브레이크포인트). 전투를 여러 번 치른 뒤 **읽힌 조각은 하나뿐**이었고, 그것도
M_BANKB 끝에 딱 붙은 첫 512 B 를 PS1 커널 코드(pc=0x000026F0)가 읽은 것 —
워드 정렬 넘침이다. 그래서 그 512 B 는 여백으로 비켜 두고 나머지만 쓴다.

  RAM   0x801153C5..0x801155C5   읽힘 — 손대지 않는다 (512 B 여백)
  RAM   0x801155C5..0x80117B8B   안 읽힘 — 여기에 레코드를 놓는다 (9,670 B)
  BATTLE 오프셋 0xF045..0x1180B

`build_mbankb_ko.py` 가 `build/MBANKB_EXT.bin` 으로 그 구간 바이트를 내놓는다.
여기서는 그것을 오버레이에 끼우고 다시 압축한다. 원본이 96섹터를 차지하므로
압축본이 그보다 작으면 원본 크기까지 0 으로 채워 섹터 수를 고정한다
(LZB 는 종단 표시로 끝나므로 뒤에 0 을 붙여도 무해하다).
"""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lzb, lzb_encode                              # noqa: E402

SRC = ROOT / "extract" / "BTT" / "BATTLE.LZB"
EXT = ROOT / "build" / "MBANKB_EXT.bin"
OUT = ROOT / "build" / "BATTLE_ko.LZB"
OFF = 0x801153C5 - 0x80106380                       # 0xF045
GUARD = 512                                         # 읽히는 앞 512 B
SECTORS = 96


def main() -> int:
    raw = SRC.read_bytes()
    dec, _ = lzb.decompress(raw)
    dec = bytearray(dec)
    orig = bytes(dec)

    if not EXT.exists():
        print(f"FAIL: {EXT.name} 이 없다 — build_mbankb_ko.py 를 먼저 돌린다")
        return 1
    ext = EXT.read_bytes()
    if OFF + len(ext) > len(dec):
        print(f"FAIL: 확장 구간이 오버레이 밖으로 나간다 ({OFF + len(ext)} > {len(dec)})")
        return 1

    # Expected Write — 여백 512 B 는 원본과 같아야 한다
    if ext[:GUARD] != orig[OFF:OFF + GUARD]:
        print("FAIL: 읽히는 앞 512 B 가 원본과 다르다 — 여백을 침범했다")
        return 1

    dec[OFF:OFF + len(ext)] = ext
    changed = sum(1 for a, b in zip(orig, dec) if a != b)
    if changed and min(i for i, (a, b) in enumerate(zip(orig, dec)) if a != b) < OFF + GUARD:
        print("FAIL: 확장 구간 앞쪽을 건드렸다")
        return 1
    dec = bytes(dec)

    comp = lzb_encode.compress(dec)
    back, _ = lzb.decompress(comp)
    if bytes(back) != dec:
        print("FAIL: 재압축 왕복 불일치")
        return 1
    if len(comp) < len(raw):
        comp = comp + bytes(len(raw) - len(comp))
    OUT.write_bytes(comp)

    budget = SECTORS * 2048
    print(f"BATTLE 해제물 {len(dec):,} B (원본과 동일) / 바뀐 바이트 {changed:,}")
    print(f"압축 {len(comp):,} B  (원본 {len(raw):,} / {SECTORS}섹터 예산 {budget:,})"
          f"  -> {'들어감' if len(comp) <= budget else '초과!'}")
    print(f"-> {OUT.relative_to(ROOT)}  sha {hashlib.sha256(comp).hexdigest()[:16]}")
    return 0 if len(comp) <= budget else 1


if __name__ == "__main__":
    raise SystemExit(main())
