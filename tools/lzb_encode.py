#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LZB (LZSS) 압축기 — `tools/lzb.py` 디코더와 짝이다.

비트스트림 (MSB first)
  1            리터럴 바이트
  0 1          긴 매치: 빅엔디언 W 2바이트
                 off = (W >> 3) - 0x2000   (-8192 .. -1)
                 n   = W & 7
                 n>0 -> len = n + 2                    (3..9)
                 n=0 -> 다음 바이트 L, L==0 이면 종료, 아니면 len = L + 1  (2..256)
  0 0          짧은 매치: 2비트 n, 다음 바이트 off = b - 0x100 (-256..-1), len = n + 2 (2..5)

비용(비트): 리터럴 9 / 짧은 매치 12 / 긴 매치 18 / 긴 매치+L 26

**이 프로젝트는 지금까지 LZB 재삽입을 금지해 왔다**(인코더가 없었다).
그래서 이 압축기는 반드시 `verify_lzb_roundtrip.py` 로 원본 4개를 왕복 검증한 뒤에만 쓴다.
"""
from __future__ import annotations
import sys
from pathlib import Path

WIN_SHORT, WIN_LONG = 256, 8192
MIN_MATCH, MAX_MATCH = 2, 256


class BitWriter:
    """플래그 비트와 데이터 바이트가 **같은 스트림에 섞인다**.

    디코더는 비트 버퍼가 비는 순간 그 자리의 바이트를 플래그 바이트로 집어간다.
    그래서 작성기도 비트가 필요할 때 **현재 위치에 한 바이트를 예약**하고 채워 넣는다.
    (플래그를 따로 모아 두면 디코더와 어긋난다 — 처음에 그렇게 짰다가 깨졌다.)
    """

    def __init__(self) -> None:
        self.out = bytearray()
        self.flag = -1
        self.left = 0

    def bit(self, v: int) -> None:
        if self.left == 0:
            self.flag = len(self.out)
            self.out.append(0)
            self.left = 8
        self.left -= 1
        if v & 1:
            self.out[self.flag] |= 1 << self.left

    def bits(self, v: int, k: int) -> None:
        for i in range(k - 1, -1, -1):
            self.bit((v >> i) & 1)

    def byte(self, v: int) -> None:
        self.out.append(v & 0xFF)

    def flush(self) -> bytes:
        return bytes(self.out)


def cost(ln: int, off: int) -> int | None:
    """이 (길이, 오프셋)을 인코딩하는 최소 비트 수. 불가능하면 None."""
    if ln < MIN_MATCH or off >= 0 or off < -WIN_LONG:
        return None
    best = None
    if 2 <= ln <= 5 and off >= -WIN_SHORT:
        best = 12
    if 3 <= ln <= 9:
        best = 18 if best is None else min(best, 18)
    if 2 <= ln <= 256:
        best = 26 if best is None else min(best, 26)
    return best


def emit(w: BitWriter, ln: int, off: int) -> None:
    if 2 <= ln <= 5 and off >= -WIN_SHORT:
        w.bit(0); w.bit(0)
        w.bits(ln - 2, 2)
        w.byte(off + 0x100)
        return
    if 3 <= ln <= 9:
        v = (((off + 0x2000) & 0x1FFF) << 3) | (ln - 2)
        w.bit(0); w.bit(1)
        w.byte(v >> 8); w.byte(v & 0xFF)
        return
    v = ((off + 0x2000) & 0x1FFF) << 3
    w.bit(0); w.bit(1)
    w.byte(v >> 8); w.byte(v & 0xFF)
    w.byte(ln - 1)


def compress(src: bytes, chain: int = 256, span: int = 256) -> bytes:
    """최적 파싱(DP). 탐욕 파싱보다 4% 작고 **게임 자체 압축기보다도 작다.**

    2026-09-01: 탐욕 파싱은 원본보다 3.5% 컸다(46,934 -> 48,582). 그 손해의 정체는
    매칭 탐색 폭이 아니라 두 가지였다.

      1. **길이 2 매치를 아예 못 봤다.** 후보를 3바이트 해시로만 찾았기 때문이다.
         길이 2는 12비트, 리터럴 둘은 18비트 — 하나당 6비트씩 버리고 있었다.
      2. 탐욕이라 지금 긴 매치를 잡느라 다음의 더 싼 조합을 놓쳤다.

    비용(비트): 리터럴 9 / 짧은 매치 12 / 긴 매치 18 / 긴 매치+L 26.
    이 표가 정확하므로 뒤에서부터 DP 로 최소 비용 경로를 그대로 구한다.
    """
    n = len(src)
    if n == 0:
        return b""
    head: dict[int, int] = {}
    prev = [-1] * n
    for i in range(n - 2):
        h = src[i] | (src[i + 1] << 8) | (src[i + 2] << 16)
        prev[i] = head.get(h, -1)
        head[h] = i

    # 길이 2 매치용 — 가장 가까운 2바이트 재출현까지의 거리
    near2 = [0] * n
    last: dict[int, int] = {}
    for i in range(n - 1):
        k = src[i] | (src[i + 1] << 8)
        p = last.get(k)
        near2[i] = (i - p) if p is not None else 0
        last[k] = i

    INF = float("inf")
    cost_to = [INF] * (n + 1)
    cost_to[n] = 0
    pick: list[tuple[int, int]] = [(1, 0)] * (n + 1)

    for i in range(n - 1, -1, -1):
        best = 9 + cost_to[i + 1]
        bl, bo = 1, 0
        m = min(MAX_MATCH, n - i)
        maxlen = maxoff = 0
        offs: dict[int, int] = {}
        if i + 2 < n:
            h = src[i] | (src[i + 1] << 8) | (src[i + 2] << 16)
            j = head.get(h, -1)
            t = 0
            while j >= 0 and i - j <= WIN_LONG and t < chain:
                if j < i:
                    t += 1
                    ln = 0
                    while ln < m and src[j + ln] == src[i + ln]:
                        ln += 1
                    if ln >= MIN_MATCH:
                        if ln > maxlen:
                            maxlen, maxoff = ln, j - i
                        for g in range(2, (ln if ln < 5 else 5) + 1):
                            if g not in offs:
                                offs[g] = j - i
                j = prev[j]
        d = near2[i]
        if 0 < d <= WIN_SHORT and i + 1 < n:
            ln = 0
            while ln < m and src[i - d + ln] == src[i + ln]:
                ln += 1
            for g in range(2, (ln if ln < 5 else 5) + 1):
                if g not in offs or offs[g] < -d:
                    offs[g] = -d
            if ln > maxlen:
                maxlen, maxoff = ln, -d
        if maxlen >= MIN_MATCH or offs:
            hi = min(max(maxlen, max(offs) if offs else 0), span)
            for g in range(2, hi + 1):
                nxt = cost_to[i + g]
                if nxt is INF:
                    continue
                c, off = None, maxoff
                if 2 <= g <= 5:
                    o = offs.get(g)
                    if o is not None and o >= -WIN_SHORT:
                        c, off = 12, o
                    elif maxlen >= g and maxoff >= -WIN_SHORT:
                        c, off = 12, maxoff
                if 3 <= g <= 9 and maxlen >= g and (c is None or c > 18):
                    c, off = 18, maxoff
                if c is None and maxlen >= g:
                    c, off = 26, maxoff
                if c is None:
                    continue
                v = c + nxt
                if v < best:
                    best, bl, bo = v, g, off
        cost_to[i] = best
        pick[i] = (bl, bo)

    w = BitWriter()
    i = 0
    while i < n:
        ln, off = pick[i]
        if ln >= MIN_MATCH:
            emit(w, ln, off)
            i += ln
        else:
            w.bit(1)
            w.byte(src[i])
            i += 1
    # 종료 표시: 긴 매치 n=0, L=0
    w.bit(0); w.bit(1); w.byte(0); w.byte(0); w.byte(0)
    return w.flush()


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    d = src.read_bytes()
    out = compress(d)
    dst.write_bytes(out)
    print(f"{src.name}: {len(d):,} -> {len(out):,} B (비 {len(out)/len(d):.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
