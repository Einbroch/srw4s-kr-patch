#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 재삽입 (1단계: 재뱅킹 없음).

정책
  * 원본 바이트에서 출발한다 — 원장에 없는 레코드/빈틈은 손대지 않는다.
  * 뱅크 안에서 **원본 순서**를 지켜 재배치한다(D_NAMES에서 순서를 뒤집었다가
    스크립트 VM이 인접 레코드를 이어 읽는 계약을 깨 실기 프리즈를 만들었다).
  * 뱅크가 넘치면 **역문을 포기하고 원문으로 되돌린다**(긴 것부터). 재뱅킹은 2단계.
  * 포인터표는 전부 remap 값으로 다시 쓴다. 별칭(접미사 공유) 시작점도 같이 옮긴다.
"""
from __future__ import annotations
import hashlib, json, struct, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode        # noqa: E402

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
OUT = ROOT / "build" / "M_BANKS_ko.BIN"
BANK = 0x10000
WINDOW = 0x400


def main() -> int:
    d = bytearray(SRC.read_bytes())
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()

    first = struct.unpack_from("<I", d, 0)[0]
    offsets = list(struct.unpack_from(f"<{first // 4}I", d, 0))

    # 뱅크별 고정 구간(헤더 + 포인터표)과 가용 구간
    fixed = [(0, first)]
    for off in offsets:
        if off and off + 0x200 <= len(d):
            fixed.append((off, off + 0x200))
    fixed.sort()

    recs = sorted(L["records"], key=lambda r: r["offset"])
    by_bank = defaultdict(list)
    for r in recs:
        by_bank[r["offset"] // BANK].append(r)

    # 레코드 새 바이트
    newbytes = {}
    for r in recs:
        if r["ko"]:
            try:
                newbytes[r["id"]] = encode(r["ko"], enc)
            except KeyError as e:
                print(f"FAIL: {r['id']} 인코딩 불가 문자 {e.args[0]!r}")
                return 1
        else:
            newbytes[r["id"]] = bytes.fromhex(r["raw_hex"])

    remap: dict[int, int] = {}
    dropped = 0
    for b in sorted(by_bank):
        lo, hi = b * BANK, min((b + 1) * BANK, len(d))
        free = []
        cur = lo
        for a, z in fixed:
            if z <= lo or a >= hi:
                continue
            if a > cur:
                free.append((cur, min(a, hi)))
            cur = max(cur, z)
        if cur < hi:
            free.append((cur, hi))
        cap = sum(z - a for a, z in free)

        items = by_bank[b]
        while True:
            need = sum(len(newbytes[r["id"]]) for r in items)
            if need <= cap:
                break
            # 가장 크게 늘어난 역문부터 포기
            cand = [r for r in items
                    if r["ko"] and len(newbytes[r["id"]]) > len(bytes.fromhex(r["raw_hex"]))]
            if not cand:
                print(f"FAIL: 뱅크 {b} 원문만으로도 넘친다 ({need} > {cap})")
                return 1
            worst = max(cand, key=lambda r: len(newbytes[r["id"]]) - len(bytes.fromhex(r["raw_hex"])))
            newbytes[worst["id"]] = bytes.fromhex(worst["raw_hex"])
            dropped += 1

        fi, fpos = 0, free[0][0] if free else lo
        for r in items:
            blob = newbytes[r["id"]]
            while fi < len(free) and fpos + len(blob) > free[fi][1]:
                fi += 1
                if fi < len(free):
                    fpos = free[fi][0]
            if fi >= len(free):
                print(f"FAIL: 뱅크 {b} 배치 실패")
                return 1
            d[fpos:fpos + len(blob)] = blob
            delta = fpos - r["offset"]
            remap[r["offset"]] = fpos
            for a in r["alias_starts"]:
                remap[int(a, 16)] = int(a, 16) + delta
            fpos += len(blob)

    # 포인터표 갱신
    miss = 0
    for off in offsets:
        if not off or off + 0x200 > len(d):
            continue
        base = off & ~0xFFFF
        tbl = list(struct.unpack_from("<256H", d, off))
        for k, rel in enumerate(tbl):
            t = base + rel
            if t in remap:
                nt = remap[t] - base
                if not (0 <= nt <= 0xFFFF):
                    print(f"FAIL: 뱅크 상대 u16 범위 초과 ({nt})")
                    return 1
                tbl[k] = nt
            elif t < len(d):
                miss += 1
        struct.pack_into("<256H", d, off, *tbl)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(bytes(d))
    tr = sum(1 for r in recs if r["ko"])
    print(f"레코드 {len(recs):,} / 역문 {tr:,} / 공간부족으로 되돌림 {dropped:,}")
    print(f"remap 미등록 포인터 {miss:,}건 (원장 밖 레코드 — 원위치 유지)")
    print(f"크기 {len(d):,}B (원본과 동일)  sha {hashlib.sha256(bytes(d)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
