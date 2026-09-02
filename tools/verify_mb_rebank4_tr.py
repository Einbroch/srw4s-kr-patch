#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""재뱅킹 v4 **번역 빌드** 검증.

항등 검증기(verify_mb_rebank4.py)는 불일치 0 을 요구하므로 번역 빌드에는 못 쓴다.
여기서는 모든 슬롯이 둘 중 하나임을 확인한다.

  (a) 원본과 바이트 동일 — 손대지 않은 레코드, 그리고 **별칭 포인터의 원문 접미사 사본**
  (b) 원본 대상이 역문 레코드이고, 새 바이트가 그 역문을 인코딩한 것과 정확히 일치

(b) 가 아닌 불일치가 하나라도 있으면 실패다.
"""
from __future__ import annotations
import bisect, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
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


def read_through(o, osrc, oe, heads, want):
    """osrc 부터 읽다가 역문 레코드로 흘러드는 경우의 기대 바이트."""
    lim = oe if oe else min(osrc + 0x400, len(o))
    i = bisect.bisect_right(heads, osrc)
    if i >= len(heads):
        return None
    p = heads[i]
    if not (osrc < p < lim):
        return None
    return o[osrc:p] + want[p]


def main() -> int:
    from mb_codec import build_encoder, encode
    from mb_alias import ko_alias_offsets
    new = Path(sys.argv[1])
    o, n = SRC.read_bytes(), new.read_bytes()
    enc = build_encoder()
    want = {}
    for r in json.loads(LEDGER.read_text(encoding="utf-8"))["records"]:
        if not r["ko"]:
            continue
        try:
            nb = encode(r["ko"], enc)
        except KeyError:
            continue
        want[r["offset"]] = nb
        # 레코드 안쪽을 가리키는 별칭: **앞부분이 그대로면** 그 상대 위치의 역문을 읽는다.
        raw = bytes.fromhex(r["raw_hex"])
        cpl = 0
        while cpl < min(len(raw), len(nb)) and raw[cpl] == nb[cpl]:
            cpl += 1
        kmap = ko_alias_offsets(r["jp"], r["ko"], enc)
        for a in r["alias_starts"]:
            rel = int(a, 16) - r["offset"]
            if 0 < rel <= cpl:
                want[int(a, 16)] = nb[rel:]
            elif rel in kmap:
                # 구조 경계에 붙은 별칭은 역문의 같은 자리를 읽어야 한다
                want[int(a, 16)] = nb[kmap[rel]:]

    # 포인터가 레코드 **직전**을 가리켜 그대로 읽어 들어가는 경우가 있다.
    # 그때 새 내용은 `원본 앞머리 + 그 레코드의 역문` 이어야 한다.
    heads = sorted(want)

    fo = struct.unpack_from("<I", o, 0)[0]
    ho = list(struct.unpack_from(f"<{fo // 4}I", o, 0))
    hn = list(struct.unpack_from(f"<{fo // 4}I", n, 0))
    slots = same = ko = bad = dead = over = 0
    ex = []
    for i, (oa, nb) in enumerate(zip(ho, hn)):
        if not oa or oa + 0x200 > len(o):
            continue
        ob = oa & 0xFFFF0000
        ot = struct.unpack_from("<256H", o, oa)
        nt = struct.unpack_from("<256H", n, nb)
        for k in range(256):
            slots += 1
            osrc, nsrc = ob + ot[k], nb + nt[k]
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
            elif osrc in want and b == want[osrc]:
                ko += 1
            elif (rt := read_through(o, osrc, oe, heads, want)) and (
                    b == rt if oe else rt[:len(b)] == b[:len(rt)]):
                # 종단(FF)이 0x400 창 밖이라 양쪽 다 잘려 있다 — 겹치는 구간만 대조한다
                ko += 1
            else:
                bad += 1
                if len(ex) < 6:
                    tag = "역문인데 바이트 불일치" if osrc in want else "설명되지 않는 변경"
                    ex.append((i, k, hex(osrc), tag, a[:10].hex(" "), b[:10].hex(" ")))
    print(f"{new.name}  번역 빌드 대조")
    print(f"  슬롯 {slots:,} / 원본 그대로 {same:,} / 역문으로 교체 {ko:,}"
          f" / 설명 안 됨 {bad:,} / 범위밖 {over} / 원본부터 죽음 {dead}")
    for e in ex:
        print("   ", e)
    okay = bad == 0 and over == 0
    print("PASS" if okay else "FAIL")
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
