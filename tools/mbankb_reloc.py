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


# 확장 구간에 **놓아도 되는** 뱅크 표.
#   M_BANKB 는 RAM 에 두 벌 올라오고 레코드 id 의 비트 15 가 어느 벌을 읽을지 고른다.
#   확장 구간(BATTLE 오버레이 뒤)은 비트15=1 사본에만 있다. 이 두 표의 레코드는
#   v0.99c 부터 확장 구간에서 정상 출력됐다(무기 이름). 나머지 표는 근거가 없으므로
#   블롭 안 빈자리에만 놓는다 — 표 0x09FB8 을 확장에 놓았다가 게임이 멈췄다.
# 2026-09-06 **비웠다.** 확장 구간(BATTLE 오버레이 뒤)은 결국 어느 표에서도
# 안전하지 않다. 표 0x077B8 의 `BB:07D71`(브레스트 파이어 ゃ 사본)을 거기 놓았더니
# 실기에서 자막이 `モむズ` — **초기화 안 된 RAM** 을 글자로 읽었다. 그 경로는 확장이
# 없는 LZB 2차 해제본을 본다([[mbankb-two-copies]]). 표가 아니라 **호출 경로**가
# 사본을 고르므로 "이 표는 안전하다"는 판정 자체가 성립하지 않는다.
# 앞서 표 0x09FB8 은 멈춤, 오버레이 스프라이트는 소실로 같은 대가를 치렀다.
# => 재배치는 **블롭 안**만 쓴다. 자리가 모자라면 블롭을 키운다(실기 검증된 길).
EXT_OK_TABLES: set = set()


def relocate(data, records, allrecords, FULL, enc, encode, WHOLE=None, ext=None,
             COPY=None):
    """data(bytearray)를 제자리에서 고친다. (옮긴 개수, 못 옮긴 id들) 반환.

    `ext=(lo, hi, blob_len)` 를 주면 블롭 **밖** 구간까지 쓸 수 있다. 뱅크 표 슬롯이
    u16 이라 블롭 시작에서 65,535 까지 가리킬 수 있고, M_BANKB 해제물(55,353 B) 뒤는
    BATTLE 오버레이 이미지다. 실기 읽기 브레이크포인트(512 B x 43 조각, `readbp.lua`)로
    **0x801155C5 이후는 전투 중 한 번도 안 읽힌다**고 확인했다 — 읽힌 조각은 M_BANKB
    끝에 붙은 첫 512 B 뿐이고, 그것도 커널 적재 루틴의 워드 정렬 넘침이었다.
    그래서 그 512 B 는 여백으로 비켜 두고 `[lo, hi)` 만 빈자리로 쓴다.
    `data` 는 blob_len 보다 긴 버퍼여야 하며, blob_len 뒤쪽은 호출자가
    BATTLE 오버레이에 따로 써 넣는다.
    """
    d = bytes(data)
    cover = bytearray(len(d))
    if ext:
        _lo, _hi, _blob = ext
        for j in range(_blob, len(d)):          # 확장 구간 밖은 전부 산 자리로 본다
            if not (_lo <= j < _hi):
                cover[j] = 1
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

    # 규칙 3: **키 레코드 런 안은 못 옮긴다.**
    # `fc 0f <키>` 접두 레코드가 끊김 없이 이어진 구간은 슬롯도 점프도 안 닿고
    # 게임이 **키를 앞으로 훑어** 찾는다. 하나라도 빼내면 그 지점에서 훑기가 끊겨
    # 뒤쪽이 통째로 사라지고, 텍스트 VM 이 쓰레기를 파싱하면 게임이 멈춘다
    # (2026-09-06 실측: 점보트3 합체 후 피격). tools/verify_mb_keyrun.py 가 게이트다.
    from verify_mb_keyrun import keyruns as _keyruns
    RUNS = [(a, rec[-1][0]) for a, rec in _keyruns(d).items()]
    RUNS = [(a, d.find(bytes([0xFF]), e) + 1) for a, e in RUNS]

    WHOLE = WHOLE or {}
    # **사본 모드.** 원본 바이트를 자리에 그대로 두고 긴 사본을 따로 놓은 뒤
    # 슬롯만 사본으로 돌린다. 키 훑기와 슬롯이 **둘 다** 닿는 레코드용이다
    # (`BB:0D0A7`: 런 0x0D096 의 42개 중 슬롯이 있는 유일한 하나).
    # 옮기면 런에 구멍이 나 나머지 41개의 훑기가 끊기지만, 사본은 런을 한 바이트도
    # 안 건드린다. 훑기로 오는 쪽은 짧은 원문 그대로, 슬롯으로 오는 쪽만 온전해진다.
    COPY = set(COPY or ())
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
        # 규칙 3: 런과 **겹치기만 해도** 안 된다. 런의 첫 `fc 0f` 이 레코드 중간에
        # 있을 수 있어(BB:07C20 은 런 0x07C22 보다 2 B 앞에서 시작한다) 시작점만
        # 보면 놓친다.
        # 규칙 3: 런과 **겹치면** 못 옮긴다. 그리고 런 **끝 경계에 딱 붙은** 것도 안 된다 —
        # 겹침 판정은 배타(offset < b)라 경계는 통과하는데, 실기에서는 훑기가 런 끝을
        # 한 칸 넘어 읽어 그 자리가 바뀌면 멈춘다(BB:0CDCB 점보트3, BB:0CE63 반 반격).
        # 경계에 붙은 것은 COPY 로만 처리한다 — 원본 바이트를 자리에 남긴다.
        _ends = {b for _a, b in RUNS}
        if r["id"] not in COPY and (
                any(r["offset"] < b and r["end"] > a for a, b in RUNS)
                or r["offset"] in _ends):
            continue
        if whole:                                  # 레코드 전체를 바꾼다(화자 이름 복원 등)
            nb = encode(whole, enc)
        else:
            a, b, _ = quote(r["ko"])
            nb = encode(r["ko"][:a + 1] + FULL[qj[2]] + r["ko"][b:], enc)
        floor = max(tbl_end[t] for t, _k in own)
        # 근거 있는 표만 확장 구간까지 쓸 수 있다. 나머지는 블롭 안으로 한정한다.
        ceil = len(d) if all(t in EXT_OK_TABLES for t, _k in own) else (ext[2] if ext else len(d))
        targets.append((r, own, nb, floor, ceil))

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
        r, _o, nb, _f, _c = t
        # 사본이 **가장 먼저**다. 사본은 블롭 안에 놓여야 하는데(확장 구간은
        # 오버레이 사본에만 있다) 블롭 빈자리는 몇십 바이트뿐이라, 뒤로 밀리면
        # 큰 WHOLE 레코드가 다 가져가고 확장 구간으로 떨어진다.
        if r["id"] in COPY:
            return (-1, 0, -len(nb))
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
            r, own, nb, floor, ceil = t
            # **자기 자리는 언제나 자기 것**이다. 새 내용은 원장에서 새로 만들므로
            # 옛 바이트를 참조하지 않는다. 그래서 자기 자리를 빈자리에 합쳐 놓고 찾는다
            # (이웃이 이미 비었으면 그 둘이 붙어 큰 조각이 된다).
            # 사본은 자기 자리를 내놓지 않는다 — 원본이 거기 그대로 살아 있어야
            # 훑기가 이어진다. 내놓으면 다른 레코드가 덮어써 런이 깨진다.
            mine = [] if r["id"] in COPY else [[r["offset"], r["end"] - r["offset"]]]
            cand = _merge(holes + mine)
            cand.sort(key=lambda h: h[1])
            spot = None
            for h in cand:
                if h[1] > 0 and h[0] + h[1] - max(h[0], floor) >= len(nb)                         and max(h[0], floor) + len(nb) <= ceil:
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
    nofit = [r["id"] for r, _o, _n, _f, _c in remaining]
    return moved, nofit
