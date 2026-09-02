#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""재뱅킹 산출물 항등 검증.

원본의 **모든 런타임 슬롯**(61표 x 256)을 원본과 새 파일에서 각각 읽어 바이트를 대조한다.
역문이 없으면 전부 일치해야 하고, 역문이 있으면 그 레코드만 달라야 한다.

같이 보는 것
  * 헤더 엔트리 수와 null 위치가 보존되는가
  * 뱅크 상대 u16 이 범위 안인가 (테이블과 레코드가 같은 창에 있는가)
  * 레코드가 0x400 런타임 창 안에서 종단하는가
"""
from __future__ import annotations
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
NEW = ROOT / "build" / "M_BANKS_ko.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 2, 0xFD: 2, 0xFE: 1}


def tok_end(buf, start, limit):
    p = start
    while p < limit:
        b = buf[p]
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
    o = SRC.read_bytes()
    n = NEW.read_bytes()
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    tr = {r["offset"] for r in L["records"] if r["ko"]}

    fo = struct.unpack_from("<I", o, 0)[0]
    ho = list(struct.unpack_from(f"<{fo // 4}I", o, 0))
    hn = list(struct.unpack_from(f"<{fo // 4}I", n, 0))
    errs = []
    if len(ho) != len(hn):
        errs.append("헤더 엔트리 수 불일치")
    for i, (a, b) in enumerate(zip(ho, hn)):
        if (a == 0) != (b == 0):
            errs.append(f"헤더[{i}] null 여부 불일치")

    slots = same = diff = nowin = noterm = deadslot = 0
    difftr = 0
    for i, (oa, nb) in enumerate(zip(ho, hn)):
        if not oa or oa + 0x200 > len(o):
            continue
        ob, nbase = oa & ~0xFFFF, nb & ~0xFFFF
        ot = struct.unpack_from("<256H", o, oa)
        nt = struct.unpack_from("<256H", n, nb)
        for k in range(256):
            slots += 1
            osrc, nsrc = ob + ot[k], nbase + nt[k]
            if nsrc >= len(n):
                nowin += 1
                continue
            oe = tok_end(o, osrc, min(osrc + 0x400, len(o)))
            ne = tok_end(n, nsrc, min(nsrc + 0x400, len(n)))
            if oe is None:
                deadslot += 1          # 원본부터 종단 안 되는 슬롯 — 회귀가 아니다
                continue
            if ne is None:
                noterm += 1            # **내가 깨뜨린 것만** 실패로 센다
                continue
            if o[osrc:oe] == n[nsrc:ne]:
                same += 1
            else:
                diff += 1
                if osrc in tr:
                    difftr += 1
    print(f"원본 {len(o):,}B -> 새 {len(n):,}B")
    print(f"슬롯 {slots:,}")
    print(f"  바이트 일치 {same:,}")
    print(f"  불일치 {diff:,} (그중 역문 레코드 {difftr:,})")
    print(f"  새 파일 범위 밖 {nowin:,} / 새로 생긴 종단 실패 {noterm:,}")
    print(f"  원본부터 죽은 슬롯 {deadslot:,} (회귀 아님)")
    bad = diff - difftr + nowin + noterm + len(errs)
    for e in errs[:5]:
        print("  " + e)
    print("PASS" if bad == 0 else f"FAIL: {bad}건")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
