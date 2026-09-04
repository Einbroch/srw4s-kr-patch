#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB 이름표 레코드를 옮기면서 **안쪽 슬롯까지 다시 잇는다**.

전투 화면의 화자 이름은 `{C:0F}` + 색인 2바이트로 불려 오고, 그 실체는 M_BANKB 안의
표 레코드다 (`{C:07}` + 색인 + 이름). 이 레코드들은 **항목마다 슬롯이 따로 가리켜**
(`BB:0AA2D` 19개, `BB:0ABC1` 6개) 일반 재배치 도구가 손대지 못한다.

이름을 늘리면(`一矢` 4 B -> `카즈야` 6 B) 그 뒤 항목이 전부 밀리므로, 슬롯마다
**자기 앞에서 늘어난 만큼**을 더해 준다. 레코드는 확장 구간으로 통째로 옮긴다.

**독립 검증**(2026-09-05 교훈): 옮긴 뒤 슬롯이 가리키는 바이트열을, 옮기기 **전**
같은 슬롯이 가리키던 바이트열과 직접 대조한다. 재매핑 로직으로 기대값을 만들지 않는다 —
그렇게 하면 틀린 계산을 정답으로 삼아 자기 자신과 대조하게 된다.
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


def apply(data, slots, recs, subs, lo, hi, encode, enc):
    """data(bytearray) 를 고친다. subs = {rec_id: [(원문, 역문), ...]}.
    slots = [(표오프셋, 칸번호, 값)]. 반환: (옮긴 레코드 수, 실패 목록, 다음 빈자리)."""
    at = lo
    moved, fail, checks = 0, [], []
    for rid, pairs in subs.items():
        r = recs[rid]
        old = bytes(data[r["offset"]:r["end"]])
        new = bytearray(old)
        # 뒤에서부터 바꿔야 앞쪽 오프셋이 안 흔들린다
        marks = []          # (원본오프셋, 늘어난바이트)
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
        if at + len(new) > hi:
            fail.append((rid, "확장 구간 부족"))
            continue
        # 안쪽 슬롯: 자기 앞에서 늘어난 만큼 더한다
        def newoff(rel):
            return at + rel + sum(g for m, g in marks if m < rel)
        data[at:at + len(new)] = new
        for si, (t, k, v) in enumerate(slots):
            if r["offset"] <= v < r["end"]:
                nv = newoff(v - r["offset"])
                struct.pack_into("<H", data, t + 2 * k, nv)
                checks.append((v, nv, r["offset"], at))
        moved += 1
        at += len(new)
    return moved, fail, at, checks


def verify(before, after, checks, subs_bytes):
    """옮기기 전/후를 **직접 대조**한다. 재매핑 로직을 다시 쓰지 않는다."""
    bad = []
    for ov, nv, _ro, _at in checks:
        a = before[ov:rec_end(before, ov)]
        b = after[nv:rec_end(after, nv)]
        for pj, pk in subs_bytes:
            a = a.replace(pj, pk)
        if a != b:
            bad.append((ov, nv, a[:24].hex(" "), b[:24].hex(" ")))
    return bad
