#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB 이름표를 **블롭 안에서** 늘린다.

전투 화면의 화자 이름은 M_BANKB 안 표 레코드(`{C:07}` + 색인 2B + 이름)에서 온다.
문제는 게임이 블롭을 **두 번** 푼다는 것이다.

    0x80107B8C   1차 해제본 — 무기 구호 등이 여기서 읽힌다
    0x801A6878   2차 해제본 — BATTLE 오버레이가 전투 시작 때 다시 푼다.
                 **이름표와 컷인 대사는 여기서 읽힌다** (실기 읽기 BP 로 확정)

2차 해제본은 블롭 55,353 B 만 담는다. 그래서 이름표를 **확장 구간(블롭 밖)으로
옮기면 2차 해제본에 그 자리가 없어** 화면이 글자 쓰레기가 된다 (2026-09-05 실측).
확장 구간은 1차 해제본만 읽는 레코드에만 쓸 수 있다.

그래서 여기서는 **블롭 안에서만** 자리를 만든다.

  1. 이름표에 붙은 이웃(안쪽 슬롯이 없어 옮길 수 있는 것)을 블롭 안 구멍으로 옮긴다
  2. 이름표를 그 자리로 늘린다 — 뒤로 늘리거나(시작 고정), 앞으로 밀거나(시작 이동)
  3. 안쪽 슬롯은 **자기 앞에서 늘어난 만큼** 더한다 (시작이 옮겨졌으면 그만큼도)

검증은 옮기기 **전/후 바이트열을 직접 대조**한다. 재매핑 로직으로 기대값을 만들면
틀린 계산을 정답으로 삼게 된다 (2026-09-05 교훈).
"""
from __future__ import annotations
import struct

ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0,
         0xFB: 2, 0xFC: 1, 0xFD: 2, 0xFE: 1}


def rec_end(d, p):
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


def _setslot(data, slots, old, new):
    n = 0
    for t, k, v in slots:
        if v == old:
            struct.pack_into("<H", data, t + 2 * k, new)
            n += 1
    return n


def run(data, slots, recs, plan, holes, encode, enc, log=print):
    """plan = [(이름표id, 이웃id, 방향, [(원문,역문)])]  방향: 'after' | 'before'.
    holes = [[시작, 길이], ...] (블롭 안). 반환 (성공수, 실패목록, 검사목록)."""
    before = bytes(data)
    done, fail, checks = 0, [], []
    for tid, nid, side, pairs in plan:
        t, nb = recs[tid], recs[nid]
        nlen = nb["end"] - nb["offset"]
        spot = next((h for h in holes if h[1] >= nlen), None)
        if spot is None:
            fail.append((tid, f"이웃 {nid} ({nlen}B) 를 받을 구멍이 없다"))
            continue
        # 1) 이웃을 구멍으로
        at = spot[0]
        data[at:at + nlen] = data[nb["offset"]:nb["end"]]
        if _setslot(data, slots, nb["offset"], at) != 1:
            fail.append((tid, f"이웃 {nid} 슬롯이 1개가 아니다"))
            continue
        checks.append((nb["offset"], at))
        spot[0] += nlen
        spot[1] -= nlen

        # 2) 이름표를 늘린다
        old = bytes(before[t["offset"]:t["end"]])
        new = bytearray(old)
        marks = []
        for jp, ko in pairs:
            pj, pk = encode(jp, enc)[:-1], encode(ko, enc)[:-1]
            i = 0
            while True:
                i = bytes(new).find(pj, i)
                if i < 0:
                    break
                marks.append((i, len(pk) - len(pj)))
                i += len(pj)
        marks.sort()
        for i, _ in reversed(marks):
            for jp, ko in pairs:
                pj, pk = encode(jp, enc)[:-1], encode(ko, enc)[:-1]
                if bytes(new[i:i + len(pj)]) == pj:
                    new[i:i + len(pj)] = pk
                    break
        grow = sum(g for _, g in marks)
        ns = t["offset"] if side == "after" else t["offset"] - grow
        if side == "before" and ns < nb["offset"]:
            fail.append((tid, "앞쪽 자리가 모자라다"))
            continue
        data[ns:ns + len(new)] = new
        if side == "before" and _setslot(data, slots, t["offset"], ns) < 1:
            fail.append((tid, "이름표 자기 슬롯을 못 찾았다"))
            continue
        for si, (tb, k, v) in enumerate(slots):
            if t["offset"] < v < t["end"]:
                rel = v - t["offset"]
                nv = ns + rel + sum(g for m, g in marks if m < rel)
                struct.pack_into("<H", data, tb + 2 * k, nv)
                checks.append((v, nv))
        log(f"  {tid} {side} {grow:+d}B  (이웃 {nid} -> 0x{at:05X})")
        done += 1
    return done, fail, checks


def verify(before, after, checks, subs_bytes):
    """옮기기 전/후 바이트열 직접 대조. 재매핑 로직을 다시 쓰지 않는다."""
    bad = []
    for ov, nv in checks:
        a = before[ov:rec_end(before, ov)]
        b = after[nv:rec_end(after, nv)]
        for pj, pk in subs_bytes:
            a = a.replace(pj, pk)
        if a != b:
            bad.append((hex(ov), hex(nv), a[:20].hex(" "), b[:20].hex(" ")))
    return bad
