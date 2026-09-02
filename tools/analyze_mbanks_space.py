#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 공간 정책 분석.

D_NAMES는 STAYDAT 안의 상주 슬라이스라 53,248 B에 갇혀 있었다. M_BANKS는 493 KB라 통째로
올라갈 수 없다 — 소비자 시그니처(records/ARCHITECTURE·analyze_structures.analyze_mbanks)가
**디스크 스트리밍**을 가리킨다:
    파일 인덱스 18 / 상단 헤더 0xF4(61*4) 읽기 / 뱅크당 포인터표 0x200 읽기
    메시지당 런타임 창 0x400 읽기
따라서 제약은 "파일 전체 크기"가 아니라 **뱅크(64 KiB) 단위**다:
  1. 뱅크 상대 u16 포인터 -> 한 레코드는 자기 뱅크 64 KiB 안에 있어야 한다
  2. 레코드는 포인터에서 시작하는 0x400 창 안에서 종단돼야 한다
  3. 뱅크 경계(0x10000 배수)는 유지해야 한다
"""
from __future__ import annotations
import struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from text_codec import parse_record   # noqa: E402

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
BANK = 0x10000
WINDOW = 0x400


def main() -> int:
    data = SRC.read_bytes()
    first = struct.unpack_from("<I", data, 0)[0]
    offsets = list(struct.unpack_from(f"<{first // 4}I", data, 0))
    print(f"파일 {len(data):,} B = 64KiB 창 {len(data)/BANK:.2f}개")
    print(f"헤더 {first} B / 엔트리 {len(offsets)}개 (non-null {sum(1 for o in offsets if o)})\n")

    banks: dict[int, dict] = {}
    for i, off in enumerate(offsets):
        if not off or off + 0x200 > len(data):
            continue
        base = off & ~0xFFFF
        b = banks.setdefault(base, {"tables": [], "targets": set()})
        b["tables"].append((i, off))
        for rel in struct.unpack_from("<256H", data, off):
            t = base + rel
            if t < len(data):
                b["targets"].add(t)

    print(f"{'뱅크':>8}{'표':>4}{'대상':>7}{'끝':>9}{'뱅크끝':>9}{'여유':>8}{'창초과':>7}")
    tot_free = 0
    tot_over = 0
    for base in sorted(banks):
        b = banks[base]
        ends = []
        over = 0
        for t in b["targets"]:
            lim = min(t + WINDOW, len(data))
            e = data.find(bytes([0xFF]), t, lim)
            if e < 0:
                over += 1
                continue
            ends.append(e + 1)
        last = max(ends) if ends else base
        bank_end = min(base + BANK, len(data))
        free = bank_end - last
        tot_free += max(free, 0)
        tot_over += over
        print(f"0x{base:06X}{len(b['tables']):>4}{len(b['targets']):>7}"
              f"{last-base:>9}{bank_end-base:>9}{free:>8}{over:>7}")
    print(f"\n뱅크 끝 잔여 합계 {tot_free:,} B / 창 안 종단 실패 {tot_over}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
