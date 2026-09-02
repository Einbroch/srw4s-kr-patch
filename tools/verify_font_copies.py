#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""글꼴 사본 누락 검사 — **폰트가 몇 벌 있는지 먼저 세고, 전부 주입됐는지 본다.**

왜 필요한가
  이 디스크는 같은 글꼴을 STAYDAT 와 C_DEMOG 두 파일에 각각 갖고 있다(뱅크 순서만 다름).
  STAYDAT 만 주입했더니 C_DEMOG 를 쓰는 화면에서 mid 뱅크 한글이 전부 원본 한자로 나왔다.
  "한쪽을 고쳤으니 됐다"는 판단이 통하지 않는 구조라, 사본 수를 세는 검사가 필요하다.

무엇을 보는가
  1. 추출본 전체에서 원본 뱅크(각 1KB 표본)가 나타나는 모든 위치를 찾는다.
  2. 그 위치가 font_inject.COPIES 에 등록돼 있는가.
  3. 등록된 사본의 산출물이 실제로 한글 비트맵을 갖고 있는가(할당표 전량 대조).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from font_inject import COPIES, BANK_LEN, glyph_offset, load_alloc   # noqa: E402
from hangul_font import HangulFont                                    # noqa: E402

PROBE = 1024


def main() -> int:
    ref_name, ref_src, _, ref_offs = [c for c in COPIES if c[0] == "STAYDAT"][0]
    ref = (ROOT / "extract" / ref_src).read_bytes()
    sigs = {b: ref[ref_offs[b]:ref_offs[b] + PROBE] for b in BANK_LEN}

    known = {}
    for name, src, dst, offs in COPIES:
        for b in BANK_LEN:
            known[(src, b, offs[b])] = name

    bad = 0
    found = {}
    for p in sorted(ROOT.joinpath("extract").rglob("*")):
        if not p.is_file():
            continue
        d = p.read_bytes()
        rel = p.relative_to(ROOT / "extract").as_posix()
        for b, sig in sigs.items():
            i = d.find(sig)
            while i >= 0:
                found.setdefault(rel, []).append((b, i))
                if (rel, b, i) not in known:
                    print(f"FAIL: 등록되지 않은 글꼴 사본 {rel} {b} @{i:#x}")
                    bad += 1
                i = d.find(sig, i + 1)
    print(f"추출본에서 발견한 글꼴 사본: {len(found)}개 파일")
    for rel, hits in found.items():
        print(f"  {rel:22s} " + " ".join(f"{b}@{o:#x}" for b, o in sorted(hits)))

    alloc = load_alloc()
    font = HangulFont()
    for name, src, dst, offs in COPIES:
        out = ROOT / "build" / dst
        if not out.exists():
            print(f"FAIL: {dst} 없음 — 이 사본은 주입되지 않았다")
            bad += 1
            continue
        d = out.read_bytes()
        miss = [ch for ch, hx in alloc["hangul"].items()
                if d[glyph_offset(offs, int(hx, 16)):
                     glyph_offset(offs, int(hx, 16)) + 32] != font.glyph(ch)]
        print(f"  {name:8s} -> {dst:16s} 한글 {len(alloc['hangul'])}자 중 불일치 {len(miss)}")
        if miss:
            print("      " + "".join(miss[:20]))
            bad += 1
    print("PASS: 모든 글꼴 사본에 주입됨" if not bad else f"FAIL: {bad}건")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
