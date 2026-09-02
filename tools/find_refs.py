#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIPS lui/addiu 쌍으로 만들어지는 32-bit 상수를 찾아 특정 주소 참조를 잡는다."""
from __future__ import annotations
import argparse, struct, sys
from pathlib import Path

def scan(code: bytes, base_addr: int, targets: set[int], tol: int = 0):
    """lui rX, imm ; ... ; addiu/ori rY, rX, imm 조합의 상수를 복원한다(간이 상수 전파)."""
    hits = []
    lui = {}          # reg -> (upper<<16, addr)
    for off in range(0, len(code) - 3, 4):
        w = struct.unpack_from('<I', code, off)[0]
        op = w >> 26
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        imm = w & 0xFFFF
        addr = base_addr + off
        if op == 0x0F:                      # lui rt, imm
            lui[rt] = (imm << 16, addr)
            val = imm << 16
            for t in targets:
                if (t & 0xFFFF0000) == val and (t & 0xFFFF) == 0:
                    hits.append((addr, 'lui', t, off))
        elif op in (0x09, 0x0D, 0x23, 0x21, 0x25, 0x20, 0x24, 0x2B, 0x29, 0x28):
            # addiu/ori/lw/lh/lhu/lb/lbu/sw/sh/sb : rs 가 lui 레지스터면 상수 완성
            if rs in lui:
                up, luiaddr = lui[rs]
                simm = imm - 0x10000 if imm & 0x8000 else imm
                val = (up + simm) & 0xFFFFFFFF
                for t in targets:
                    if abs(val - t) <= tol:
                        hits.append((addr, f'op{op:02X}', val, off))
            if op in (0x09, 0x0D):          # 결과가 다른 레지스터에 남는다
                if rs in lui:
                    up, _ = lui[rs]
                    simm = imm - 0x10000 if imm & 0x8000 else imm
                    lui[rt] = ((up + simm) & 0xFFFFFFFF, addr)
                elif rt in lui:
                    del lui[rt]
        elif op == 0:
            rd = (w >> 11) & 31
            if rd in lui:
                del lui[rd]
    return hits

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--base', required=True, help='이 파일 오프셋 0의 런타임 주소')
    ap.add_argument('--skip', type=lambda x:int(x,0), default=0, help='파일 헤더 스킵 바이트')
    ap.add_argument('--target', action='append', required=True)
    ap.add_argument('--tol', type=lambda x:int(x,0), default=0)
    a = ap.parse_args()
    data = Path(a.file).read_bytes()[a.skip:]
    targets = {int(t,0) for t in a.target}
    hits = scan(data, int(a.base,0), targets, a.tol)
    print(f"{a.file}: {len(hits)} hits")
    for addr, kind, val, off in hits[:80]:
        print(f"  RAM 0x{addr:08X} (file 0x{off+a.skip:06X}) {kind} -> 0x{val:08X}")

if __name__ == '__main__':
    raise SystemExit(main())
