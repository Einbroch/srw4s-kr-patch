#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""스크립트 스트림 보존 검사 (순서보존 섹션 S00/S01/S02).

왜 필요한가
  이 섹션들의 풀에는 **포인터표가 가리키지 않는 스크립트 조각**이 1,201 B 들어 있고,
  VM 이 레코드 종단을 넘어 그것까지 이어 읽는다. 재삽입기가 포인터로 도달 가능한
  레코드만 모아 풀을 다시 쌓으면 조각이 사라지고, 실기에서 panic 트랩에 걸린다
  (2026-08-23 정신 메뉴 프리징).

무엇을 보는가
  역문을 전부 끄고(SRW4S_SKIP_TR=all) 빌드했을 때 순서보존 섹션의 풀이 원본과
  **바이트 단위로 같은지** 본다. 같으면 순회기가 레코드도 조각도 하나도 잃지 않았다는 뜻이다.
  (역문이 들어가면 길이가 달라져 직접 비교가 안 되므로 항등 조건에서 검사한다.)
"""
from __future__ import annotations
import os, subprocess, sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections   # noqa: E402

ORDERED = (0, 1, 2)
SRC = ROOT / "extract" / "DAT" / "D_NAMES.BIN"
OUT = ROOT / "build" / "D_NAMES_ko.BIN"


def pool_range(secs, i):
    s = [x for x in secs if x.get("section") == i][0]
    te = s["table_end"]
    later = [t["start"] for t in secs if t.get("start") and t["start"] > te]
    return te, (min(later) if later else None)


def main() -> int:
    keep = OUT.read_bytes() if OUT.exists() else None
    env = dict(os.environ, SRW4S_SKIP_TR="all", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "reinsert_build.py")],
                       env=env, capture_output=True, text=True, encoding="utf-8")
    if r.returncode not in (0, 1):
        print("FAIL: 항등 빌드 실패\n" + (r.stdout or "") + (r.stderr or ""))
        return 1
    o = SRC.read_bytes()
    n = OUT.read_bytes()
    so, sn = dnames_sections(o), dnames_sections(n)
    bad = 0
    for i in ORDERED:
        ots, oe = pool_range(so, i)
        nts, _ = pool_range(sn, i)
        span = (oe - ots) if oe else (len(o) - ots)
        a, b = o[ots:ots + span], n[nts:nts + span]
        ok = a == b
        print(f"S{i:02d} 풀 {span:6,}B  원본 {ots:#07x} / 새 {nts:#07x}  바이트 동일={ok}")
        if not ok:
            d = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), None)
            print(f"    첫 불일치 원본 {ots + d:#07x}" if d is not None else "    길이 불일치")
            bad += 1
    if keep is not None:
        OUT.write_bytes(keep)      # 실제 빌드 산출물을 되돌린다
    print("PASS: 조각 포함 스트림 보존" if not bad else f"FAIL: {bad}개 섹션")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
