#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""표 밖 대사의 **자기 위치 상대 오프셋 표** — 찾기와 다시 가리키기.

구조 (실기 추적 + 역어셈블로 확정, 2026-09-06)

    fc 01 fa NN  <u16> x NN        ; {C:01}{A} 개수 + 값들
    대상 = (그 u16 이 놓인 오프셋) + u16값        ; **자기 위치 기준, 부호 없음**

즉 대상은 언제나 참조보다 **뒤**에 있다. 블롭에 표 1,567개 / 참조 4,521개가 있고,
표 밖 대사 1,686개 중 **1,437개(85%)** 가 이 표로만 닿는다.

왜 이걸 못 찾았나
  슬롯(헤더 61 x 색인 256)·상대 점프(`{C:06}/{C:07}`)·`{B:}`/`{D:}` 인수를 전수로 뒤져도
  없었고, 블롭 전체에 대상 오프셋이 **2바이트 값으로 아예 없었다** — 절대값이 아니라
  상대값이라서다. 이걸 모른 채 `BH:02F97` 경계를 2 B 옮겼다가 실기에서 깨졌다
  (화면에 `가라리아「I어져!」`, 옛 자리에서 읽음). [[exhaustive-is-not-complete]]

쓰는 법
  레코드를 **옮기고 참조를 다시 가리키면** 기존 바이트를 하나도 안 밀리고 길이를 늘릴 수
  있다. 대상이 참조보다 뒤여야 하므로 새 자리는 **블롭 끝** 쪽이면 언제나 안전하다.
"""
from __future__ import annotations
import struct


def tables(d: bytes):
    """[(표 시작, [(u16 오프셋, 값, 대상), ...]), ...]"""
    out, p = [], 0
    n_max = len(d)
    while p < n_max - 4:
        if d[p] == 0xFC and d[p + 1] == 0x01 and d[p + 2] == 0xFA:
            n = d[p + 3]
            if 1 <= n <= 16 and p + 4 + 2 * n <= n_max:
                vals, ok = [], True
                for k in range(n):
                    a = p + 4 + 2 * k
                    v = struct.unpack_from("<H", d, a)[0]
                    t = a + v
                    if not (0 <= t < n_max):
                        ok = False
                        break
                    vals.append((a, v, t))
                if ok:
                    out.append((p, vals))
                    p = p + 4 + 2 * n
                    continue
        p += 1
    return out


def refs_to(d: bytes, target: int) -> list[int]:
    """target 을 가리키는 u16 들의 오프셋."""
    return [a for _s, vals in tables(d) for a, _v, t in vals if t == target]


def repoint(data: bytearray, old: int, new: int) -> int:
    """old 를 가리키던 참조를 전부 new 로 돌린다. 고친 개수 반환.

    u16 은 **부호 없음**이라 new 는 모든 참조보다 뒤여야 한다. 아니면 예외.
    """
    hits = refs_to(bytes(data), old)
    for a in hits:
        delta = new - a
        if not (0 <= delta <= 0xFFFF):
            raise ValueError(f"0x{a:05X} 에서 0x{new:05X} 까지 {delta} — u16 범위 밖")
    for a in hits:
        struct.pack_into("<H", data, a, new - a)
    return len(hits)
