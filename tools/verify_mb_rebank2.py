#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""재뱅킹 v2 검증 — 레코드뿐 아니라 **이어읽는 바이트까지** 원본과 같은지 본다.

v1 검증은 레코드 종단까지만 봤고 그래서 통과했지만 실기는 깨졌다.
여기서는 각 슬롯에서 `reach` 바이트를 통째로 원본과 대조한다.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"


def main() -> int:
    new = Path(sys.argv[1])
    reach = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x400
    o, n = SRC.read_bytes(), new.read_bytes()
    fo = struct.unpack_from("<I", o, 0)[0]
    ho = list(struct.unpack_from(f"<{fo // 4}I", o, 0))
    hn = list(struct.unpack_from(f"<{fo // 4}I", n, 0))
    if [bool(x) for x in ho] != [bool(x) for x in hn]:
        print("FAIL: 헤더 null 위치가 다르다")
        return 1
    slots = same = diff = dead = short = 0
    ex = []
    for i, (oa, nb) in enumerate(zip(ho, hn)):
        if not oa or oa + 0x200 > len(o):
            continue
        ob, nbase = oa & 0xFFFF0000, nb & 0xFFFF0000
        ot = struct.unpack_from("<256H", o, oa)
        nt = struct.unpack_from("<256H", n, nb)
        for k in range(256):
            slots += 1
            osrc, nsrc = ob + ot[k], nbase + nt[k]
            if osrc >= len(o):
                dead += 1                      # 원본부터 파일 밖
                continue
            a = o[osrc:osrc + reach]
            b = n[nsrc:nsrc + reach]
            if len(b) < len(a):
                short += 1
                ex.append((i, k, "새 파일이 짧다", len(a), len(b)))
                continue
            if a == b[:len(a)]:
                same += 1
            else:
                diff += 1
                if len(ex) < 5:
                    j = next(t for t in range(len(a)) if a[t] != b[t])
                    ex.append((i, k, f"+{j}에서 갈림", a[j:j + 8].hex(" "), b[j:j + 8].hex(" ")))
    print(f"{new.name}  이어읽기 {reach:#06x} 까지 대조")
    print(f"  슬롯 {slots:,} / 일치 {same:,} / 불일치 {diff:,} / 짧음 {short} / 원본부터 죽음 {dead}")
    for e in ex[:5]:
        print("   ", e)
    ok = diff == 0 and short == 0
    print("PASS: 이어읽기까지 보존" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
