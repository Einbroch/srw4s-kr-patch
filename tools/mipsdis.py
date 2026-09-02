#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""아주 작은 MIPS R3000 디스어셈블러 — 필요한 명령만 다룬다."""
import struct, sys

R = ["zero","at","v0","v1","a0","a1","a2","a3","t0","t1","t2","t3","t4","t5","t6","t7",
     "s0","s1","s2","s3","s4","s5","s6","s7","t8","t9","k0","k1","gp","sp","fp","ra"]
SPECIAL = {0x00:"sll",0x02:"srl",0x03:"sra",0x04:"sllv",0x06:"srlv",0x07:"srav",
           0x08:"jr",0x09:"jalr",0x0C:"syscall",0x10:"mfhi",0x12:"mflo",
           0x18:"mult",0x19:"multu",0x1A:"div",0x1B:"divu",
           0x20:"add",0x21:"addu",0x22:"sub",0x23:"subu",0x24:"and",0x25:"or",
           0x26:"xor",0x27:"nor",0x2A:"slt",0x2B:"sltu"}
OPS = {0x02:"j",0x03:"jal",0x04:"beq",0x05:"bne",0x06:"blez",0x07:"bgtz",
       0x08:"addi",0x09:"addiu",0x0A:"slti",0x0B:"sltiu",0x0C:"andi",0x0D:"ori",
       0x0E:"xori",0x0F:"lui",0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",
       0x28:"sb",0x29:"sh",0x2B:"sw"}


def dis(w: int, pc: int) -> str:
    op = w >> 26
    rs, rt, rd = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    sa, imm = (w >> 6) & 31, w & 0xFFFF
    simm = imm - 0x10000 if imm & 0x8000 else imm
    if op == 0:
        f = w & 0x3F
        n = SPECIAL.get(f, f"sp{f:02X}")
        if n in ("sll", "srl", "sra"):
            return f"{n} ${R[rd]},${R[rt]},{sa}"
        if n == "jr":
            return f"jr ${R[rs]}"
        if n == "jalr":
            return f"jalr ${R[rd]},${R[rs]}"
        if n in ("mfhi", "mflo"):
            return f"{n} ${R[rd]}"
        if n in ("mult", "multu", "div", "divu"):
            return f"{n} ${R[rs]},${R[rt]}"
        return f"{n} ${R[rd]},${R[rs]},${R[rt]}"
    n = OPS.get(op, f"op{op:02X}")
    if n in ("j", "jal"):
        return f"{n} 0x{((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2):08X}"
    if n in ("beq", "bne"):
        return f"{n} ${R[rs]},${R[rt]},0x{pc + 4 + simm * 4:08X}"
    if n in ("blez", "bgtz"):
        return f"{n} ${R[rs]},0x{pc + 4 + simm * 4:08X}"
    if n == "lui":
        return f"lui ${R[rt]},0x{imm:04X}"
    if n in ("lb", "lh", "lw", "lbu", "lhu", "sb", "sh", "sw"):
        return f"{n} ${R[rt]},{simm}(${R[rs]})"
    return f"{n} ${R[rt]},${R[rs]},0x{imm:04X}" if n in ("andi","ori","xori") \
        else f"{n} ${R[rt]},${R[rs]},{simm}"


def main() -> int:
    path, start, count = sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0)
    base = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0
    d = open(path, "rb").read()
    for i in range(count):
        off = start + i * 4
        w = struct.unpack_from("<I", d, off)[0]
        print(f"{off:#08x}  {base + off:#010x}  {w:08X}  {dis(w, base + off)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
