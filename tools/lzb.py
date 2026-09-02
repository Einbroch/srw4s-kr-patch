#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LZB (LZSS) decompressor for Dai-4-Ji Super Robot Taisen S (SLPS-00196).

Faithful port of the routine at RAM 0x800C345C (file offset 0x3C5C) in
SLPS_001.96.  Bitstream: MSB-first flag bits.

  bit 1              -> literal byte
  bit 0, bit 1       -> long match: 2 bytes big-endian W
                        offset = sign_extend13(W >> 3)   (always negative)
                        len    = (W & 7) + 2
                        if (W & 7) == 0: L = next byte
                                         L == 0 -> end of stream
                                         len = L + 1
  bit 0, bit 0       -> short match: 2 more bits -> n (0..3)
                        offset = next_byte - 256          (-256..-1)
                        len    = n + 2
"""
import sys

class Bits:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos
        self.cur = 0
        self.left = 0

    def bit(self):
        if self.left == 0:
            self.cur = self.d[self.p]
            self.p += 1
            self.left = 8
        self.left -= 1
        return (self.cur >> self.left) & 1

    def byte(self):
        b = self.d[self.p]
        self.p += 1
        return b


def decompress(data, pos=0, limit=None):
    b = Bits(data, pos)
    out = bytearray()
    while True:
        if b.bit():
            out.append(b.byte())
            continue
        if b.bit():
            w = (b.byte() << 8) | b.byte()
            off = (w >> 3) - 0x2000          # sign-extended 13-bit, always negative
            n = w & 7
            if n == 0:
                L = b.byte()
                if L == 0:
                    break
                ln = L + 1
            else:
                ln = n + 2
        else:
            n = (b.bit() << 1) | b.bit()
            off = b.byte() - 0x100           # -256 .. -1
            ln = n + 2
        src = len(out) + off
        if src < 0:
            raise ValueError(f"back-reference before start at out={len(out)} off={off}")
        for _ in range(ln):
            out.append(out[src])
            src += 1
        if limit and len(out) > limit:
            raise ValueError("limit exceeded")
    return bytes(out), b.p


if __name__ == '__main__':
    src = sys.argv[1]
    start = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
    data = open(src, 'rb').read()
    out, end = decompress(data, start)
    sys.stderr.write(f"{src}@0x{start:X}: {end-start} -> {len(out)} bytes (ratio {len(out)/(end-start):.2f})\n")
    if len(sys.argv) > 3:
        open(sys.argv[3], 'wb').write(out)
