#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""표 밖 대사의 **자기 위치 상대 오프셋 표** — 찾기와 다시 가리키기.

구조 (실기 추적 + 역어셈블로 확정, 2026-09-06)

    fc 01 fa NN  <u16> x NN        ; {C:01}{A} 개수 + 값들
    대상 = (그 u16 이 놓인 오프셋) + s16값        ; **자기 위치 기준, 부호 있음(s16)**

원본은 대상이 언제나 참조보다 뒤라 값이 전부 32,767 이하다. 그래서 오랫동안
무부호로 착각했는데 **실기는 s16 으로 읽는다.**

  실측 (2026-09-10, 스테이지 14 닥터 헬 공격 시 멈춤)
    표 blob+10178 의 u16@10184 = 0xBB47
      무부호로 보면 10184+47943 = 58127   (옮겨 놓은 자리)
      s16 으로 보면 10184-17593 = -7409
    실기가 실제로 점프한 곳: base-7409 = 0x801A4B87  <- **s16 해석과 정확히 일치**

  => 32,767 을 넘기면 게임이 음수로 읽어 블롭 **앞쪽**으로 튕겨 나간다.
     그 자리는 블롭 밖이라 쓰레기를 파싱하고 멈추거나 빈칸이 된다. 블롭에 표 1,567개 / 참조 4,521개가 있고,
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


def slot_spans(d: bytes) -> list[tuple[int, int]]:
    """뱅크 슬롯표가 차지한 구간 [(시작, 끝), ...].

    **왜 필요한가.** 슬롯표는 u16 값이 늘어서 있어서 우연히 `fc 01 fa NN` 으로
    읽히는 자리가 생긴다. 그걸 `{C:01}{A}` 표로 오인하면 있지도 않은 참조가
    잡히고, 재배치가 슬롯을 고친 것을 「참조가 깨졌다」고 잘못 신고한다
    (2026-09-10 실측: blob+1264 는 슬롯표인데 표 항목으로 잡혔다).
    헤더 61 u32 가 뱅크 시작을 주므로 구간을 정확히 계산할 수 있다.
    """
    out = [(0, 61 * 4)]
    for i in range(61):
        off = struct.unpack_from("<I", d, i * 4)[0]
        if not off or off + 2 > len(d):
            continue
        n, mn = 0, 1 << 30
        while off + 2 * (n + 1) <= len(d):
            v = struct.unpack_from("<H", d, off + 2 * n)[0]
            m = min(mn, v)
            if m < off + 2 * (n + 1) or v >= len(d):
                break
            mn = m
            n += 1
        if n:
            out.append((off, off + 2 * n))
    return sorted(out)


def tables(d: bytes):
    """[(표 시작, [(u16 오프셋, 값, 대상), ...]), ...]"""
    out, p = [], 0
    n_max = len(d)
    skip = slot_spans(d)          # 슬롯표 안은 표가 아니다 (오인 방지)

    def in_slots(x):
        for a, b in skip:
            if a <= x < b:
                return True
        return False

    while p < n_max - 4:
        if d[p] == 0xFC and d[p + 1] == 0x01 and d[p + 2] == 0xFA and not in_slots(p):
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


S16MAX = 32767      # 실기가 s16 으로 읽는다. 넘기면 음수가 되어 블롭 앞으로 튕긴다.


def reach(refs: list[int]) -> tuple[int, int]:
    """이 참조들이 모두 닿을 수 있는 새 자리의 범위 (하한 초과, 상한 이하)."""
    return max(refs), min(refs) + S16MAX


def overflows(d: bytes) -> list[tuple[int, int]]:
    """s16 범위를 넘긴 참조 [(u16 오프셋, 값), ...]. 원본은 0개여야 한다."""
    return [(a, v) for _s, vals in tables(d) for a, v, _t in vals if v > S16MAX]


def repoint(data: bytearray, old: int, new: int) -> int:
    """old 를 가리키던 참조를 전부 new 로 돌린다. 고친 개수 반환.

    **s16 이다.** new 는 모든 참조보다 뒤에 있으면서, 가장 앞선 참조에서
    32,767 이내여야 한다. 아니면 예외.
    """
    hits = refs_to(bytes(data), old)
    for a in hits:
        delta = new - a
        if not (0 <= delta <= S16MAX):
            raise ValueError(
                f"0x{a:05X} 에서 0x{new:05X} 까지 {delta} — s16 범위 밖"
                f" (한계 {S16MAX}). 더 가까운 자리에 놓아야 한다")
    for a in hits:
        struct.pack_into("<H", data, a, new - a)
    return len(hits)
