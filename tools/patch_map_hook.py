#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAP 오버레이에 D_NAMES 별도 적재 훅을 넣고 베이스를 빈 RAM 대역으로 옮긴다.

왜
  * D_NAMES는 STAYDAT 안에 packed돼 있고 STAYDAT에는 빈틈이 없다. 뒤로 밀면 하드코딩
    상수 65곳이 깨진다(`SPACE_BUDGET.md` §4).
  * 독립 `DAT/D_NAMES.BIN`은 게임이 읽지 않는 죽은 중복본이다(실기 확인).
  * 그래서 그 파일을 **실제로 적재**하게 만들고 베이스 표를 그리로 돌린다.
    파일은 ISO에서 자유롭게 커질 수 있다(재배치 게이트 통과).

어디에
  * STAYDAT 로더 래퍼 `0x801547CC`(호출자 1곳, 9워드)가 훅 지점이다. 이 시점의 CD는
    방금 동기 전체 파일 읽기를 끝낸 상태라 같은 호출을 하나 더 얹는 것이 가장 위험이 작다.
  * 스텁은 MAP 해제물의 정적 참조 0건인 0-run(`0x8015FAB4`, 330 B)에 둔다.
  * 목적지 `0x80168000` — 오버레이(BATTLE 끝 `0x80165550`) 위이고, 4,800프레임 관측에서
    쓰기가 0건이던 대역 `0x80166000–0x80189FFF` 안이다(`RUNTIME_CHECKS.md` §2).

로더 규약: `0x800C3158(a0=파일 인덱스, a1=목적지)` — 전체 파일 동기 읽기.
D_NAMES는 파일 인덱스 **11**, STAYDAT은 **28**(EXE 경로 표 `0x800E0410`에서 확인).
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

import lzb                                                            # noqa: E402
import srw_lz_enc                                                      # noqa: E402
from mips_asm import (addiu, sw, lw, ori, lui, jal, jr, nop, j,        # noqa: E402
                      assemble_checked)

SRC = ROOT / "extract" / "MAP.LZB"
OUT_LZB = ROOT / "build" / "MAP_ko.LZB"  # --no-dnames면 MAP_stubonly.LZB
OUT_DEC = ROOT / "build" / "MAP_ko.dec"

BASE = 0x80106380
WRAPPER = 0x801547CC          # STAYDAT 로더 래퍼(9워드, 호출자 1곳)
STUB = 0x8015FAB4             # 정렬된 0-run, 정적 참조 0건
BASE_SLOT = 0x8015F310        # D_NAMES 베이스 표 슬롯
LOADER = 0x800C3158
IDX_STAYDAT, IDX_DNAMES = 0x1C, 0x0B
STAYDAT_DEST = 0x80020000
DNAMES_DEST = 0x80168000

WRAPPER_TEXT = [
    "addiu $sp, $sp, -0x18",
    "sw $ra, 0x10($sp)",
    "ori $a0, $zero, 0x1c",
    f"jal 0x{LOADER:x}",
    "lui $a1, 0x8002",
    "lw $ra, 0x10($sp)",
    "addiu $sp, $sp, 0x18",
    "jr $ra",
    "nop",
]


def build_stub(with_dnames: bool = True):
    words = [
        addiu("sp", "sp", -0x18),
        sw("ra", 0x10, "sp"),
        ori("a0", "zero", IDX_STAYDAT),
        jal(LOADER),
        lui("a1", STAYDAT_DEST >> 16),          # branch delay slot
    ] + ([
        ori("a0", "zero", IDX_DNAMES),
        lui("a1", DNAMES_DEST >> 16),
        jal(LOADER),
        ori("a1", "a1", DNAMES_DEST & 0xFFFF),  # branch delay slot
    ] if with_dnames else []) + [
        lw("ra", 0x10, "sp"),
        addiu("sp", "sp", 0x18),
        jr("ra"),
        nop(),
    ]
    text = [
        "addiu $sp, $sp, -0x18",
        "sw $ra, 0x10($sp)",
        "ori $a0, $zero, 0x1c",
        f"jal 0x{LOADER:x}",
        "lui $a1, 0x8002",
    ] + ([
        "ori $a0, $zero, 0xb",
        "lui $a1, 0x8016",
        f"jal 0x{LOADER:x}",
        "ori $a1, $a1, 0x8000",
    ] if with_dnames else []) + [
        "lw $ra, 0x10($sp)",
        "addiu $sp, $sp, 0x18",
        "jr $ra",
        "nop",
    ]
    return assemble_checked(words, STUB, text)


def check_hazards(text: list[str]) -> None:
    """R3000 load-delay: lw 다음 명령이 그 목적 레지스터를 쓰면 안 된다."""
    for i, t in enumerate(text[:-1]):
        if t.startswith("lw "):
            dst = t.split()[1].rstrip(",")
            if dst in text[i + 1]:
                raise AssertionError(f"load-delay 위반: '{t}' -> '{text[i+1]}'")


def main() -> int:
    src = SRC.read_bytes()
    dec, consumed = lzb.decompress(src, 0)
    if consumed != len(src):
        raise SystemExit("MAP.LZB 해제가 입력을 다 쓰지 않았다")
    data = bytearray(dec)

    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)

    # Expected Write 1: 래퍼가 정확히 그 9워드인가
    woff = WRAPPER - BASE
    got = [f"{i.mnemonic} {i.op_str}".strip()
           for i in md.disasm(bytes(data[woff:woff + 4 * len(WRAPPER_TEXT)]), WRAPPER)]
    if [g.replace(" ", "") for g in got] != [t.replace(" ", "") for t in WRAPPER_TEXT]:
        raise SystemExit(f"Expected Write 실패 — 래퍼가 다르다:\n{got}")

    # Expected Write 2: 스텁 자리가 0인가
    soff = STUB - BASE
    if any(data[soff:soff + 52]):
        raise SystemExit(f"Expected Write 실패 — 0x{STUB:08X}가 0이 아니다")

    # Expected Write 3: 베이스 표 슬롯이 현재 STAYDAT 안의 D_NAMES를 가리키는가
    boff = BASE_SLOT - BASE
    cur = struct.unpack_from("<I", data, boff)[0]
    if cur != 0x80069800:
        raise SystemExit(f"Expected Write 실패 — 베이스 슬롯이 0x{cur:08X}")

    with_dn = "--no-dnames" not in sys.argv
    stub, stub_text = build_stub(with_dn)
    check_hazards(stub_text)
    tramp, tramp_text = assemble_checked([j(STUB), nop()], WRAPPER,
                                         [f"j 0x{STUB:x}", "nop"])
    if (WRAPPER & 0xF0000000) != (STUB & 0xF0000000):
        raise SystemExit("j 대상이 같은 256MiB 영역이 아니다")

    data[soff:soff + len(stub)] = stub
    data[woff:woff + len(tramp)] = tramp
    if with_dn and "--no-repoint" not in sys.argv:
        struct.pack_into("<I", data, boff, DNAMES_DEST)

    re = srw_lz_enc.compress(bytes(data), level=16)
    back, _ = lzb.decompress(re, 0)
    if back != bytes(data):
        raise SystemExit("재압축 왕복 불일치")

    OUT_LZB.parent.mkdir(exist_ok=True)
    tag = "MAP_ko" if with_dn else "MAP_stubonly"
    if with_dn and "--no-repoint" in sys.argv: tag = "MAP_loadonly"
    out_lzb = ROOT / "build" / (tag + ".LZB")
    out_lzb.write_bytes(re)
    (ROOT / "build" / (tag + ".dec")).write_bytes(bytes(data))
    report = dict(
        original_lzb=len(src), patched_lzb=len(re), decompressed=len(data),
        sectors_needed=(len(re) + 2047) // 2048,
        wrapper=f"0x{WRAPPER:08X}", trampoline=tramp_text,
        stub=f"0x{STUB:08X}", stub_text=stub_text,
        base_slot=f"0x{BASE_SLOT:08X}", base_old="0x80069800",
        base_new=f"0x{DNAMES_DEST:08X}",
        lzb_sha256=hashlib.sha256(re).hexdigest(),
        dec_sha256=hashlib.sha256(bytes(data)).hexdigest(),
    )
    (ROOT / "analysis" / "map_hook_patch.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MAP.LZB {len(src)} -> {len(re)} B ({report['sectors_needed']}섹터 필요)")
    print(f"트램폴린 @0x{WRAPPER:08X}: {tramp_text}")
    print(f"스텁 @0x{STUB:08X}:")
    for k, t in enumerate(stub_text):
        print(f"   {STUB + 4*k:08X}  {t}")
    print(f"베이스 슬롯 0x{BASE_SLOT:08X}: 0x80069800 -> 0x{DNAMES_DEST:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
