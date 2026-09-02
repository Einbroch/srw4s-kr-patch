#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 재뱅킹 v3 — ASM 훅(`rel*2`) 전용, 뱅크 한도 128KiB.

전제: `tools/patch_mbanks_hook.py` 로 주소 계산을 바꿔 둔 상태.
    base   = header[bank]        (마스크 없음 -> 표가 어디 있든 그 자리가 베이스)
    offset = base + rel * 2      (레코드는 짝수 오프셋에 정렬)

v2 와 같은 점
    이동 단위는 레코드가 아니라 **구간(run)** 이다. 표가 읽을 수 있는 `[포인터, 포인터+reach)`
    를 모아 합친 원본 연속 구간을 통째로 옮긴다. 그래야 이어읽기가 원본과 같다.

v2 와 다른 점
    창이 128KiB 까지 커질 수 있어 표가 한 창에 더 많이 모이고, 구간이 공유돼 전체가 줄어든다
    (0x400 보존 기준 752KB -> 622KB).
"""
from __future__ import annotations
import hashlib, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
ALIGN = 0x10000          # 창 시작은 64KiB 경계
SPAN = 0x20000           # rel 이 u16 이고 *2 이므로 창 하나가 128KiB 까지


def slots(d, off):
    return list(struct.unpack_from("<256H", d, off))


def runs_for(d, offs, tables, reach):
    rs = []
    for bi in tables:
        off = offs[bi]
        base = off & 0xFFFF0000
        for rel in slots(d, off):
            t = base + rel
            if t >= len(d):
                continue
            rs.append((t, min(t + reach, len(d))))
    rs.sort()
    out = []
    for a, b in rs:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def win_size(d, offs, tables, reach, lead):
    # 구간마다 짝수 정렬 패딩이 최대 1바이트
    return lead + len(tables) * 0x200 + sum(b - a + 1 for a, b in runs_for(d, offs, tables, reach))


def pack(d, offs, live, reach, first):
    rest = sorted(live, key=lambda bi: (offs[bi] & 0xFFFF0000, offs[bi]))
    wins = []
    while rest:
        lead = first if not wins else 0
        cur, left = [], []
        for bi in rest:
            if win_size(d, offs, cur + [bi], reach, lead) <= SPAN:
                cur = cur + [bi]
            else:
                left.append(bi)
        if not cur:
            return None
        wins.append(cur)
        rest = left
    return wins


def main() -> int:
    reach = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x400
    d = SRC.read_bytes()
    first = struct.unpack_from("<I", d, 0)[0]
    offs = list(struct.unpack_from(f"<{first // 4}I", d, 0))
    live = [i for i, o in enumerate(offs) if o and o + 0x200 <= len(d)]

    wins = pack(d, offs, live, reach, first)
    if wins is None:
        print(f"FAIL: 표 하나가 창을 넘는다 (reach={reach:#x})")
        return 1

    out = bytearray(d[0:first])
    header = list(offs)
    for wi, tables in enumerate(wins):
        if wi:
            while len(out) % ALIGN:
                out.append(0)
        wstart = len(out)
        tbl_at = {}
        for bi in sorted(tables):
            if len(out) % 2:
                out.append(0)
            tbl_at[bi] = len(out)
            out += bytes(0x200)
            header[bi] = tbl_at[bi]
        place = {}
        for a, b in runs_for(d, offs, tables, reach):
            if len(out) % 2:
                out.append(0)          # 레코드는 짝수 오프셋이어야 rel*2 로 닿는다
            place[(a, b)] = len(out)
            out += d[a:b]
        for bi in sorted(tables):
            obase = offs[bi] & 0xFFFF0000
            base = tbl_at[bi]
            new = [0] * 256
            for k, rel in enumerate(slots(d, offs[bi])):
                t = obase + rel
                for (a, b), at in place.items():
                    if a <= t < b:
                        pos = at + (t - a)
                        delta = pos - base
                        if delta < 0 or delta % 2 or delta // 2 > 0xFFFF:
                            print(f"FAIL: 표{bi} 슬롯{k} 오프셋 {delta} 을 rel*2 로 못 담는다")
                            return 1
                        new[k] = delta // 2
                        break
                else:
                    new[k] = 0
            struct.pack_into("<256H", out, tbl_at[bi], *new)
        if len(out) - wstart > SPAN:
            print(f"FAIL: 창 {wi} 가 {len(out)-wstart:,}B 로 {SPAN:,} 를 넘는다")
            return 1
    struct.pack_into(f"<{len(header)}I", out, 0, *header)

    dst = ROOT / "build" / f"M_BANKS_r3_{reach:04x}.BIN"
    dst.write_bytes(bytes(out))
    print(f"이어읽기 보존 {reach:#06x}  표 {len(live)}개 -> 창 {len(wins)}개 (한도 {SPAN//1024}KiB)")
    print(f"크기 {len(d):,} -> {len(out):,} B ({(len(out)+2047)//2048}섹터)")
    print(f"-> {dst.name}  sha {hashlib.sha256(bytes(out)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
