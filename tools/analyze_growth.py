#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""성장 재삽입 게이트 — D_NAMES 참조·공간 분석.

번역문이 길어질 때 무엇이 깨질 수 있는지 판정하기 위한 정적 조사.
  * 포인터 공유(같은 문자열을 여러 엔트리가 가리킴)
  * 레코드 **안쪽**을 겨누는 앵커(도너 프로젝트가 실제로 당한 사고)
  * 사용되지 않는 빈 공간(=성장 예산)
  * 16-bit 포인터 천장과 파일 크기의 관계
원본은 읽기만 한다.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections, text_end   # noqa: E402

DN = ROOT / "extract" / "DAT" / "D_NAMES.BIN"


def main() -> int:
    data = DN.read_bytes()
    n = len(data)
    sections = dnames_sections(data)

    tables = []          # (start, end, section)
    ptr_owners = defaultdict(list)   # pointer -> [(section, entry)]
    records = {}         # start -> end (exclusive, FF 포함)
    for sec in sections:
        if sec["start"] is None:
            continue
        tables.append((sec["start"], sec["table_end"], sec["section"]))
        for s in sec["strings"]:
            p = s["pointer"]
            ptr_owners[p].append((sec["section"], s["entry"]))
            records[p] = p + len(s["raw"])

    starts = sorted(records)
    # 1) 공유 포인터
    shared = {p: v for p, v in ptr_owners.items() if len(v) > 1}
    # 2) 레코드 안쪽 앵커: 어떤 포인터가 다른 레코드의 [start+1, end) 안에 있나
    anchors = []
    for p in starts:
        for q in starts:
            if q < p < records[q]:
                anchors.append({"anchor": p, "inside_record": q,
                                "inside_end": records[q],
                                "offset_into": p - q,
                                "anchor_owners": ptr_owners[p][:4],
                                "host_owners": ptr_owners[q][:4]})
                break

    # 3) 커버리지: 표 + 레코드가 덮는 바이트
    covered = bytearray(n)
    covered[0:0x48] = b"\x01" * 0x48          # 18 x u32 헤더
    for a, b, _ in tables:
        for i in range(a, b):
            covered[i] = 1
    for p in starts:
        for i in range(p, min(records[p], n)):
            covered[i] = 1
    gaps = []
    i = 0
    while i < n:
        if covered[i]:
            i += 1
            continue
        j = i
        while j < n and not covered[j]:
            j += 1
        gaps.append((i, j - i, data[i:j]))
        i = j
    free_total = sum(g[1] for g in gaps)

    print(f"D_NAMES {n} bytes (0x{n:X})")
    print(f"  섹션 {len([s for s in sections if s['start'] is not None])}개, "
          f"포인터 엔트리 {sum(len(v) for v in ptr_owners.values())}개, "
          f"고유 대상 {len(ptr_owners)}개")
    print(f"  공유 포인터 대상: {len(shared)}개 "
          f"(최다 {max((len(v) for v in shared.values()), default=0)}회)")
    print(f"  레코드 안쪽 앵커: {len(anchors)}개")
    print(f"  16-bit 포인터 천장 0xFFFF=65535, 최대 사용 포인터 0x{max(starts):X}={max(starts)}")
    print(f"  미사용 바이트 총 {free_total} ({free_total/n*100:.2f}%), 구간 {len(gaps)}개")
    big = sorted(gaps, key=lambda g: -g[1])[:10]
    for off, ln, blob in big:
        kind = "zero" if not any(blob) else ("FF" if all(b == 0xFF for b in blob) else "data")
        print(f"    gap @0x{off:04X} len={ln} ({kind}) head={blob[:12].hex().upper()}")

    if anchors:
        print("\n  앵커 예시:")
        for a in anchors[:10]:
            print(f"    0x{a['anchor']:04X} <- 레코드 0x{a['inside_record']:04X}"
                  f"..0x{a['inside_end']:04X} 안쪽 +{a['offset_into']} "
                  f"{a['anchor_owners']} / host {a['host_owners']}")

    out = dict(
        size=n, sections=len(tables),
        pointer_entries=sum(len(v) for v in ptr_owners.values()),
        unique_targets=len(ptr_owners),
        shared_targets=len(shared),
        interior_anchors=len(anchors),
        anchors=anchors[:200],
        max_pointer=max(starts), pointer_ceiling=0xFFFF,
        free_bytes=free_total,
        gaps=[{"offset": o, "len": l,
               "kind": "zero" if not any(b) else ("FF" if all(x == 0xFF for x in b) else "data")}
              for o, l, b in gaps],
    )
    (ROOT / "analysis" / "dnames_growth_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n->", ROOT / "analysis" / "dnames_growth_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
