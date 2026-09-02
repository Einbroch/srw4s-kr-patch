#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BATTLE 오버레이의 D_NAMES 접근자를 MAP과 같은 64KiB 뱅킹으로 바꾼다.

원본 BATTLE(RAM 0x80146EC0, 11워드)은 문자열을 `base + u16`으로 평탄하게 푼다.
MAP(RAM 0x80154828)은 `base + (header[sec] & 0xFFFF0000) + u16`으로 섹션별 64KiB
뱅킹을 한다. 두 오버레이가 같은 D_NAMES를 다른 규약으로 읽으면 뱅킹을 쓸 수 없으므로
BATTLE 쪽을 MAP에 맞춘다.

뱅킹 계약을 지키는 최소 구현은 13워드인데 원본 자리는 11워드뿐이라 트램폴린을 쓴다.
  * 0x80146EC0 : `j NEW` + `nop`   (2워드. $ra 보존이므로 NEW의 `jr $ra`가 원 호출자로 돌아간다)
  * NEW        : 13워드 본체

모든 헤더 값이 `< 0x10000`인 동안에는 `header & 0xFFFF0000== 0`이라 **동작이 원본과 완전히
동일**하다. 즉 이 패치 단독 빌드는 순수 회귀 시험이 된다.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "reference" / "srwcb-korean-patch" / "tools" / "graphics"))

import lzb                                      # noqa: E402
import srw_lz_enc                                # noqa: E402
from mips_asm import (lui, lw, lhu, andi, sll, addu, subu, jr, nop, j,   # noqa: E402
                      words_to_bytes, assemble_checked)

SRC_LZB = ROOT / "extract" / "BTT" / "BATTLE.LZB"
OUT_LZB = ROOT / "build" / "BATTLE_ko.LZB"
OUT_DEC = ROOT / "build" / "BATTLE_ko.dec"

BASE = 0x80106380                 # BATTLE 해제물의 런타임 적재 주소(런타임 확정)
ACCESSOR_RAM = 0x80146EC0         # 원본 접근자 진입점
FREE_RAM = 0x80164FB8             # 4바이트 정렬된 0 padding(97바이트, 정적 참조 0건)
FREE_LEN = 52                     # 13워드
BASE_SLOT_RAM = 0x80163B74        # BATTLE 안의 D_NAMES 베이스 표 사본
DNAMES_DEST = 0x80168000          # MAP 훅이 적재하는 새 위치(patch_map_hook.py와 일치)

# 원본 11워드 — Expected Write 기준
ORIGINAL_TEXT = [
    "lui $v1, 0x8016",
    "lw $v1, 0x3b74($v1)",
    "sll $a0, $a0, 2",
    "addu $a0, $a0, $v1",
    "lw $v0, ($a0)",
    "sll $a1, $a1, 1",
    "addu $v0, $v1, $v0",
    "addu $a1, $a1, $v0",
    "lhu $v0, ($a1)",
    "jr $ra",
    "addu $v0, $v0, $v1",
]


def build_new_body(base_addr: int):
    words = [
        lui("v0", 0x8016),          # v0 = 0x80160000
        lw("v0", 0x3B74, "v0"),     # v0 = D_NAMES base
        sll("a0", "a0", 2),         # (load delay slot) a0 = section*4
        addu("a0", "a0", "v0"),     # a0 = &header[section]
        lw("v1", 0x0000, "a0"),     # v1 = header[section]
        sll("a1", "a1", 1),         # (load delay slot) a1 = entry*2
        addu("v0", "v0", "v1"),     # v0 = table = base + header
        andi("v1", "v1", 0xFFFF),   # v1 = header & 0xFFFF
        addu("a1", "a1", "v0"),     # a1 = &table[entry]
        subu("v0", "v0", "v1"),     # v0 = table - low = base + (header & 0xFFFF0000)
        lhu("v1", 0x0000, "a1"),    # v1 = u16 pointer
        jr("ra"),
        addu("v0", "v0", "v1"),     # (branch delay slot) return string_base + pointer
    ]
    text = [
        "lui $v0, 0x8016",
        "lw $v0, 0x3b74($v0)",
        "sll $a0, $a0, 2",
        "addu $a0, $a0, $v0",
        "lw $v1, ($a0)",
        "sll $a1, $a1, 1",
        "addu $v0, $v0, $v1",
        "andi $v1, $v1, 0xffff",
        "addu $a1, $a1, $v0",
        "subu $v0, $v0, $v1",
        "lhu $v1, ($a1)",
        "jr $ra",
        "addu $v0, $v0, $v1",
    ]
    return assemble_checked(words, base_addr, text)


def check_hazards(words_text: list[str]) -> None:
    """R3000 load-delay: lw/lhu 다음 명령이 그 목적 레지스터를 쓰면 안 된다."""
    def dest(t):
        if t.startswith(("lw ", "lhu ", "lbu ", "lb ", "lh ")):
            return t.split()[1].rstrip(",")
        return None
    for i, t in enumerate(words_text[:-1]):
        d = dest(t)
        if d and d in words_text[i + 1]:
            raise AssertionError(f"load-delay 위반: '{t}' 다음 '{words_text[i+1]}'")


def main() -> int:
    src = SRC_LZB.read_bytes()
    dec, consumed = lzb.decompress(src, 0)
    if consumed != len(src):
        raise SystemExit("BATTLE.LZB 해제가 입력을 다 쓰지 않았다")
    data = bytearray(dec)

    acc_off = ACCESSOR_RAM - BASE
    free_off = FREE_RAM - BASE

    # Expected Write 1: 원본 접근자 11워드가 정확히 그 명령인가
    orig_blob = bytes(data[acc_off:acc_off + 4 * len(ORIGINAL_TEXT)])
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    got = [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(orig_blob, ACCESSOR_RAM)]
    if [g.replace(" ", "") for g in got] != [t.replace(" ", "") for t in ORIGINAL_TEXT]:
        raise SystemExit(f"Expected Write 실패 — 원본 접근자가 다르다:\n{got}")

    # Expected Write 2: 자유 공간이 정말 0인가
    if any(data[free_off:free_off + FREE_LEN]):
        raise SystemExit(f"Expected Write 실패 — 0x{FREE_RAM:08X}가 0이 아니다")

    body, body_text = build_new_body(FREE_RAM)
    check_hazards(body_text)

    tramp, tramp_text = assemble_checked(
        [j(FREE_RAM), nop()], ACCESSOR_RAM,
        [f"j 0x{FREE_RAM:x}", "nop"])
    if (ACCESSOR_RAM & 0xF0000000) != (FREE_RAM & 0xF0000000):
        raise SystemExit("j 대상이 같은 256MiB 영역이 아니다")

    data[acc_off:acc_off + len(tramp)] = tramp
    data[free_off:free_off + len(body)] = body

    # 베이스 표 사본도 MAP과 같은 새 위치로 돌린다. 두 오버레이가 다른 베이스를 보면
    # 전투 화면만 엉뚱한 곳을 읽는다.
    bslot = BASE_SLOT_RAM - BASE
    cur = struct.unpack_from("<I", data, bslot)[0]
    if cur != 0x80069800:
        raise SystemExit(f"Expected Write 실패 — BATTLE 베이스 슬롯이 0x{cur:08X}")
    struct.pack_into("<I", data, bslot, DNAMES_DEST)

    # 재압축 + 왕복
    re = srw_lz_enc.compress(bytes(data), level=9)
    back, _ = lzb.decompress(re, 0)
    if back != bytes(data):
        raise SystemExit("재압축 왕복 불일치")

    sectors = (len(src) + 2047) // 2048
    budget = sectors * 2048
    OUT_LZB.parent.mkdir(exist_ok=True)
    OUT_LZB.write_bytes(re)
    OUT_DEC.write_bytes(bytes(data))

    report = dict(
        original_lzb=len(src), original_sectors=sectors, sector_budget=budget,
        patched_lzb=len(re), fits_same_sectors=len(re) <= budget,
        slack=budget - len(re),
        decompressed=len(data),
        accessor_ram=f"0x{ACCESSOR_RAM:08X}", trampoline=tramp_text,
        body_ram=f"0x{FREE_RAM:08X}", body=body_text,
        base_slot=f"0x{BASE_SLOT_RAM:08X}", base_new=f"0x{DNAMES_DEST:08X}",
        dec_sha256=hashlib.sha256(bytes(data)).hexdigest(),
        lzb_sha256=hashlib.sha256(re).hexdigest(),
    )
    (ROOT / "analysis" / "battle_accessor_patch.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"원본 LZB {len(src)}B ({sectors}섹터, 예산 {budget}B)")
    print(f"패치 LZB {len(re)}B  같은 섹터 수용={len(re) <= budget} 여유 {budget-len(re)}B")
    print(f"트램폴린 @0x{ACCESSOR_RAM:08X}: {tramp_text}")
    print(f"베이스 슬롯 0x{BASE_SLOT_RAM:08X}: 0x80069800 -> 0x{DNAMES_DEST:08X}")
    print(f"본체 @0x{FREE_RAM:08X} ({len(body)}B):")
    for k, t in enumerate(body_text):
        print(f"   {FREE_RAM + 4*k:08X}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
