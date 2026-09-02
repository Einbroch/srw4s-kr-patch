#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""재뱅킹 v4 검증 — **훅 적용 후의 주소 계산**으로 원본과 대조한다.

    base   = header[bank]        (마스크 없음)
    offset = base + rel
레코드는 종단까지 대조한다(엔진이 쓰는 것은 레코드 자체이고, 최대 1024 B 다).
"""
from __future__ import annotations
import struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 2, 0xFD: 2, 0xFE: 1}


def tok_end(d, s, lim):
    p = s
    while p < lim:
        b = d[p]
        if b == 0xFF:
            return p + 1
        if b < 0xF0:
            p += 1
        elif b <= 0xF5:
            p += 2
        else:
            a = ARITY.get(b)
            if a is None:
                return None
            p += 1 + a
    return None


def main() -> int:
    new = Path(sys.argv[1])
    o, n = SRC.read_bytes(), new.read_bytes()
    fo = struct.unpack_from("<I", o, 0)[0]
    ho = list(struct.unpack_from(f"<{fo // 4}I", o, 0))
    hn = list(struct.unpack_from(f"<{fo // 4}I", n, 0))
    if [bool(x) for x in ho] != [bool(x) for x in hn]:
        print("FAIL: 헤더 null 위치가 다르다")
        return 1
    slots = same = diff = dead = over = 0
    ex = []
    for i, (oa, nb) in enumerate(zip(ho, hn)):
        if not oa or oa + 0x200 > len(o):
            continue
        ob = oa & 0xFFFF0000
        ot = struct.unpack_from("<256H", o, oa)
        nt = struct.unpack_from("<256H", n, nb)       # 새 표는 블록 맨 앞
        for k in range(256):
            slots += 1
            osrc = ob + ot[k]
            nsrc = nb + nt[k]                          # 마스크 없음
            if osrc >= len(o):
                dead += 1
                continue
            if nsrc >= len(n):
                over += 1
                continue
            oe = tok_end(o, osrc, min(osrc + 0x400, len(o)))
            ne = tok_end(n, nsrc, min(nsrc + 0x400, len(n)))
            a = o[osrc:oe] if oe else o[osrc:osrc + 0x400]
            b = n[nsrc:ne] if ne else n[nsrc:nsrc + 0x400]
            if a == b:
                same += 1
            else:
                diff += 1
                if len(ex) < 5:
                    ex.append((i, k, a[:12].hex(" "), b[:12].hex(" ")))
    print(f"{new.name}  훅 모델(base=header[bank], offset=base+rel) 로 대조")
    print(f"  슬롯 {slots:,} / 일치 {same:,} / 불일치 {diff:,} / 범위밖 {over} / 원본부터 죽음 {dead}")
    for e in ex:
        print("   ", e)
    ok = diff == 0 and over == 0
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
