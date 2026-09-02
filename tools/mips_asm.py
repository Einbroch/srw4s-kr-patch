#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""손으로 쓰는 MIPS R3000 인코더(이 프로젝트에 필요한 명령만).

생성한 워드는 반드시 capstone으로 되읽어 원했던 명령과 일치하는지 검산한다
(`assemble_checked`). 부분집합 인코더를 신뢰하지 않기 위한 장치다.
"""
from __future__ import annotations

import struct

R = {"zero": 0, "at": 1, "v0": 2, "v1": 3, "a0": 4, "a1": 5, "a2": 6, "a3": 7,
     "t0": 8, "t1": 9, "t2": 10, "t3": 11, "t4": 12, "t5": 13, "t6": 14, "t7": 15,
     "s0": 16, "s1": 17, "s2": 18, "s3": 19, "s4": 20, "s5": 21, "s6": 22, "s7": 23,
     "t8": 24, "t9": 25, "k0": 26, "k1": 27, "gp": 28, "sp": 29, "fp": 30, "ra": 31}


def _i(op, rs, rt, imm):
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)


def _r(rs, rt, rd, sa, funct):
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | ((sa & 31) << 6) | funct


def lui(rt, imm):            return _i(0x0F, "zero", rt, imm)
def lw(rt, off, rs):         return _i(0x23, rs, rt, off)
def lhu(rt, off, rs):        return _i(0x25, rs, rt, off)
def andi(rt, rs, imm):       return _i(0x0C, rs, rt, imm)
def sll(rd, rt, sa):         return _r("zero", rt, rd, sa, 0x00)
def addu(rd, rs, rt):        return _r(rs, rt, rd, 0, 0x21)
def subu(rd, rs, rt):        return _r(rs, rt, rd, 0, 0x23)
def jr(rs):                  return (R[rs] << 21) | 0x08
def nop():                   return 0
def j(target):
    if target & 3:
        raise ValueError("j target must be word aligned")
    return (0x02 << 26) | ((target >> 2) & 0x03FFFFFF)


def ori(rt, rs, imm):        return _i(0x0D, rs, rt, imm)
def addiu(rt, rs, imm):      return _i(0x09, rs, rt, imm)
def sw(rt, off, rs):         return _i(0x2B, rs, rt, off)
def jal(target):
    if target & 3:
        raise ValueError("jal target must be word aligned")
    return (0x03 << 26) | ((target >> 2) & 0x03FFFFFF)


def words_to_bytes(words) -> bytes:
    return b"".join(struct.pack("<I", w & 0xFFFFFFFF) for w in words)


def assemble_checked(words, base_addr, expected_text):
    """capstone으로 되읽어 기대한 어셈블리와 일치하는지 검산한다."""
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    blob = words_to_bytes(words)
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    got = [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(blob, base_addr)]
    if len(got) != len(words):
        raise AssertionError(f"디코드 개수 불일치 {len(got)} != {len(words)}")
    for k, (g, e) in enumerate(zip(got, expected_text)):
        if g.replace(" ", "") != e.replace(" ", ""):
            raise AssertionError(f"word {k}: 디코드 '{g}' != 기대 '{e}'")
    return blob, got
