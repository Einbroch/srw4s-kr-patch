#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB 레코드 재배치 — 칸이 좁아 줄여 쓴 이름을 온전히 넣는다.

블롭이 64 KB 미만이라 뱅크 표의 u16 슬롯 하나로 **블롭 어디든** 가리킬 수 있다.
그래서 레코드를 옮기고 슬롯만 고치면 원래 칸 길이에 매이지 않는다.

자리 계산에서 두 가지를 반드시 지킨다.

  1. **슬롯이 가리키는 곳은 원장에 없어도 산 자리다.** 종단까지 덮어 두지 않으면
     옮긴 레코드 중간을 다른 슬롯이 가리켜 화면에 반토막 난 줄이 나온다(실측).
  2. 옮길 레코드가 **지금 차지한 자리도 빈자리 풀에 넣는다.** 새 내용은 원장에서
     새로 만들므로 옛 바이트를 참조하지 않는다. 이걸 넣어야 자리가 충분해진다.

옮길 수 있는 레코드의 조건: 슬롯이 그 레코드 **시작**만 가리키고, 안쪽을 가리키는
슬롯이 하나도 없어야 한다.
"""
from __future__ import annotations
import struct

ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0,
         0xFB: 2, 0xFC: 1, 0xFD: 2, 0xFE: 1}


def _rec_end(d, p):
    while p < len(d):
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
                return p + 1
            p += 1 + a
    return len(d)


def _nslots(d, off):
    n, mn = 0, 1 << 30
    while off + 2 * (n + 1) <= len(d):
        v = struct.unpack_from("<H", d, off + 2 * n)[0]
        m = min(mn, v)
        if m < off + 2 * (n + 1) or v >= len(d):
            break
        mn = m
        n += 1
    return n


def _merge(holes):
    holes = sorted([h for h in holes if h[1] > 0], key=lambda h: h[0])
    out = []
    for h in holes:
        if out and out[-1][0] + out[-1][1] == h[0]:
            out[-1][1] += h[1]
        else:
            out.append([h[0], h[1]])
    return out


def quote(s):
    a, b = s.rfind("「"), s.rfind("」")
    return (a, b, s[a + 1:b]) if 0 <= a < b else None


def relocate(data, records, allrecords, FULL, enc, encode, WHOLE=None):
    """data(bytearray)를 제자리에서 고친다. (옮긴 개수, 못 옮긴 id들) 반환."""
    d = bytes(data)
    cover = bytearray(len(d))
    for i in range(244):
        cover[i] = 1
    hdr = list(struct.unpack_from("<61I", d, 0))
    slotpos = []
    for off in [o for o in hdr if o and o + 0x200 <= len(d)]:
        for k in range(_nslots(d, off)):
            slotpos.append((off, k, struct.unpack_from("<H", d, off + 2 * k)[0]))
            cover[off + 2 * k] = cover[off + 2 * k + 1] = 1
    for r in allrecords:
        for j in range(r["offset"], min(r["end"], len(d))):
            cover[j] = 1
    for _t, _k, v in slotpos:                      # 규칙 1
        if v < len(d):
            for j in range(v, _rec_end(d, v)):
                cover[j] = 1

    # 표 길이는 "슬롯이 표 자신보다 앞을 가리키면 거기서 끝"으로 정해진다.
    # 그래서 옮긴 자리가 **그 표의 끝보다 앞**이면 표가 짧아진 것으로 읽혀
    # 뒤쪽 대사가 통째로 사라진다(2026-09-01 실측: 도달 49줄 -> 3줄).
    tbl_end = {}
    for off in [o for o in hdr if o and o + 0x200 <= len(d)]:
        tbl_end[off] = off + 2 * _nslots(d, off)

    WHOLE = WHOLE or {}
    targets = []
    for r in records:
        if not r["ko"]:
            continue
        qj = quote(r["jp"])
        whole = WHOLE.get(r["id"])
        if not whole and (not qj or qj[2] not in FULL):
            continue
        own = [(t, k) for t, k, v in slotpos if v == r["offset"]]
        inner = [1 for t, k, v in slotpos if r["offset"] < v < r["end"]]
        if not own or inner:
            continue
        if whole:                                  # 레코드 전체를 바꾼다(화자 이름 복원 등)
            nb = encode(whole, enc)
        else:
            a, b, _ = quote(r["ko"])
            nb = encode(r["ko"][:a + 1] + FULL[qj[2]] + r["ko"][b:], enc)
        floor = max(tbl_end[t] for t, _k in own)
        targets.append((r, own, nb, floor))

    base_holes = []
    i = 0
    while i < len(cover):
        if not cover[i]:
            k = i
            while k < len(cover) and not cover[k]:
                k += 1
            base_holes.append([i, k - i])
            i = k
        else:
            i += 1

    # **이미 새 집을 얻은 레코드의 자리만** 빈자리로 내놓는다.
    # 미리 다 내놓고 일부가 실패하면 실패한 레코드의 원래 내용이 다른 레코드에
    # 덮여 사라진다(실측: 마징고·파일더가 블롭에서 통째로 없어졌다).
    # 실패분을 하나씩 빼는 방식은 뺄수록 자리가 줄어 수렴하지 않는다 —
    # 반대로 **놓을 수 있는 것부터 놓고, 그때마다 자리를 내놓는다.**
    # 자리가 모자라므로 **적은 순서대로** 준다: 화자 이름을 되살리는 것(WHOLE)이 먼저,
    # 그다음 FULL 에 적은 순서, 같은 등급 안에서는 큰 것부터.
    order = {q: i for i, q in enumerate(FULL)}

    def _rank(t):
        r, _o, nb, _f = t
        if r["id"] in WHOLE:
            return (0, 0, -len(nb))
        qj = quote(r["jp"])
        return (1, order.get(qj[2] if qj else "", 1 << 20), -len(nb))

    holes = _merge(base_holes)
    plan, remaining = [], list(targets)
    progress = True
    while progress:
        progress = False
        for t in sorted(remaining, key=_rank):
            r, own, nb, floor = t
            # **자기 자리는 언제나 자기 것**이다. 새 내용은 원장에서 새로 만들므로
            # 옛 바이트를 참조하지 않는다. 그래서 자기 자리를 빈자리에 합쳐 놓고 찾는다
            # (이웃이 이미 비었으면 그 둘이 붙어 큰 조각이 된다).
            mine = [r["offset"], r["end"] - r["offset"]]
            cand = _merge(holes + [mine])
            cand.sort(key=lambda h: h[1])
            spot = None
            for h in cand:
                if h[1] > 0 and h[0] + h[1] - max(h[0], floor) >= len(nb):
                    spot = h
                    break
            if spot is None:
                continue
            holes = [h for h in cand if h is not spot]
            at = max(spot[0], floor)
            rest = [[spot[0], at - spot[0]]] if at > spot[0] else []
            tail = spot[0] + spot[1] - (at + len(nb))
            holes += rest + ([[at + len(nb), tail]] if tail > 0 else [])
            plan.append((r, own, nb, at))
            remaining.remove(t)
            holes = _merge(holes)
            progress = True
            break

    for r, own, nb, at in plan:
        data[at:at + len(nb)] = nb
        for t, k in own:
            struct.pack_into("<H", data, t + 2 * k, at)
    moved = len(plan)
    nofit = [r["id"] for r, _o, _n, _f in remaining]
    return moved, nofit
