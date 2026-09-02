#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 재뱅킹 v2 — **이어읽기 보존**.

v1 은 왜 깨졌나
  레코드를 하나씩 떼어 다시 담았다. 정적으로는 14,105 슬롯 전부 바이트 일치였는데도
  실기에서 대사가 엉뚱하게 나오고 멈췄다(번역 0개인 항등 빌드로도 재현).
  런타임은 포인터가 가리키는 레코드만 읽는 게 아니라 **그 뒤에 오는 바이트까지 이어 읽는다**
  (읽기 단위가 0x400 이다). 그래서 레코드를 떼어내면 뒤따르는 내용이 달라진다.

v2 의 이동 단위
  레코드가 아니라 **구간(run)** 이다. 표 하나가 읽을 수 있는 범위
  `[포인터, 포인터+WIN)` 을 전부 모아 겹치는 것끼리 합치면 원본의 연속 구간 몇 개가 된다.
  그 구간을 **통째로, 내부 순서를 그대로** 새 창에 옮긴다. 그러면 어떤 레코드에서 이어 읽어도
  원본과 같은 바이트가 나온다.

레이아웃
  [61개 u32 헤더][창0][창1]...   각 창 = [이 창에 든 표들(0x200씩)][구간들]
  창0 만 헤더 뒤에서 시작한다(베이스는 0). 표와 그 표의 구간은 반드시 같은 64KiB 창에 있다.
"""
from __future__ import annotations
import hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
WIN = 0x10000


def slots(d: bytes, off: int) -> list[int]:
    return list(struct.unpack_from("<256H", d, off))


def runs_for(d: bytes, offs: list[int], tables: list[int], reach: int) -> list[tuple[int, int]]:
    """이 표들이 읽을 수 있는 원본 구간을 합쳐서 돌려준다."""
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
    out: list[list[int]] = []
    for a, b in rs:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def win_size(d, offs, tables, reach, lead) -> int:
    return lead + len(tables) * 0x200 + sum(b - a for a, b in runs_for(d, offs, tables, reach))


def pack(d, offs, live, reach, first) -> list[list[int]] | None:
    """표를 창에 담는다.

    **원래 뱅크 순서**로 채운다. 같은 뱅크에 있던 표끼리 구간이 겹치므로 그게 가장 촘촘하다.
    (한계 비용이 작은 것부터 붙이는 방식도 시험했으나 구간이 파편화돼 오히려 커졌다:
     0x400 기준 752,417 -> 821,132 B.)
    """
    rest = sorted(live, key=lambda bi: (offs[bi] & 0xFFFF0000, offs[bi]))
    wins: list[list[int]] = []
    while rest:
        lead = first if not wins else 0
        cur: list[int] = []
        left: list[int] = []
        for bi in rest:
            trial = cur + [bi]
            if win_size(d, offs, trial, reach, lead) <= WIN:
                cur = trial
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
            while len(out) % WIN:
                out.append(0)
        base = len(out) & ~0xFFFF
        # 표 자리
        tbl_at = {}
        for bi in sorted(tables):
            tbl_at[bi] = len(out)
            out += bytes(0x200)
            header[bi] = tbl_at[bi]
        # 구간 배치 (원본 순서 그대로)
        place = {}
        for a, b in runs_for(d, offs, tables, reach):
            at = len(out)
            out += d[a:b]
            place[(a, b)] = at
        # 포인터 갱신
        for bi in sorted(tables):
            obase = offs[bi] & 0xFFFF0000
            new = [0] * 256
            for k, rel in enumerate(slots(d, offs[bi])):
                t = obase + rel
                for (a, b), at in place.items():
                    if a <= t < b:
                        new[k] = at - base + (t - a)
                        break
                else:
                    new[k] = 0        # 원본 파일 밖 — 원래도 죽은 슬롯
            struct.pack_into("<256H", out, tbl_at[bi], *[x & 0xFFFF for x in new])
    struct.pack_into(f"<{len(header)}I", out, 0, *header)

    dst = ROOT / "build" / f"M_BANKS_r2_{reach:04x}.BIN"
    dst.write_bytes(bytes(out))
    print(f"이어읽기 보존 {reach:#06x}  표 {len(live)}개 -> 창 {len(wins)}개")
    print(f"크기 {len(d):,} -> {len(out):,} B ({len(out)/WIN:.1f}창, {(len(out)+2047)//2048}섹터)")
    print(f"-> {dst.name}  sha {hashlib.sha256(bytes(out)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
