#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""글리프 수요·공급 실측.

공급 = 16x16 슬롯 `0x100`–`0x6FF` 1,536칸에서, **번역 후에도 살아 있어야 할 원문 글리프**를 뺀 나머지.
수요 = 확정 역문이 쓰는 고유 한글 음절 수.

'살아 있어야 할' 판정
  - D_NAMES: 역문이 들어간 span은 사라지고, 나머지 바이트(미번역 span·span 밖)는 남는다.
  - 그 외 텍스트 blob(M_BANKS 대사 등): 아직 일본어이므로 **전부 남는다**.
    구조를 다 풀지 않은 blob은 원시 토큰 스캔으로 과대 집계한다(안전한 방향 — 공급을 줄인다).
"""
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections      # noqa: E402
from text_codec import parse_record                  # noqa: E402

EX = ROOT / "extract" / "DAT"
LOW_MAX = 0x100          # 이 미만은 8x16 반각 — 한글 슬롯이 아니다
SLOT_LO, SLOT_HI = 0x100, 0x700


def raw_glyph_scan(data: bytes) -> Counter:
    """F0–F5 + trail 쌍만 센다. **그래픽 blob에 쓰면 포화된다** — 텍스트 blob 전용."""
    c = Counter()
    i, n = 0, len(data)
    while i < n - 1:
        b = data[i]
        if 0xF0 <= b <= 0xF5:
            c[(((b + 1) << 8) & 0x0F00) | data[i + 1]] += 1
            i += 2
        else:
            i += 1
    return c


def mbanks_glyphs() -> tuple[Counter, int, int]:
    """M_BANKS를 구조대로 걷는다: 61엔트리 헤더 -> 뱅크당 256개 u16 -> 0x400 창 안 종단."""
    import struct
    data = (EX / "M_BANKS.BIN").read_bytes()
    first = struct.unpack_from("<I", data, 0)[0]
    offsets = struct.unpack_from(f"<{first // 4}I", data, 0)
    c = Counter(); ok = 0; total = 0
    seen = set()
    for off in offsets:
        if not off or off + 0x200 > len(data):
            continue
        base = off & ~0xFFFF
        for rel in struct.unpack_from("<256H", data, off):
            t = base + rel
            total += 1
            if t >= len(data) or t in seen:
                continue
            seen.add(t)
            end = data.find(bytes([0xFF]), t, min(t + 0x400, len(data)))
            if end < 0:
                continue
            try:
                toks = parse_record(data[t:end + 1])
            except Exception:
                continue
            ok += 1
            for tk in toks:
                if tk.kind == "glyph":
                    c[tk.glyph_id] += 1
    return c, ok, total


def dnames_survivors() -> tuple[Counter, Counter]:
    """(번역 후 남는 글리프, 번역으로 비는 글리프)"""
    data = (EX / "D_NAMES.BIN").read_bytes()
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    tr = {}
    for rec in L["records"]:
        for s in rec["spans"]:
            if s["ko"]:
                tr.setdefault(rec["id"], []).append((s["start"], s["end"]))
    keep, drop = Counter(), Counter()
    seen = set()
    for sec in dnames_sections(data):
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            p = st["pointer"]
            if p in seen:
                continue
            seen.add(p)
            raw = st["raw"] + bytes([0xFF])
            cut = tr.get(f"DN:{p:04X}", [])
            pos = 0
            for tok in parse_record(raw):
                if tok.kind == "glyph":
                    inside = any(a <= pos < b for a, b in cut)
                    (drop if inside else keep)[tok.glyph_id] += 1
                pos += len(tok.raw)
    return keep, drop


def main() -> int:
    keep, drop = dnames_survivors()
    others = Counter()
    per_file = {}
    for p in sorted(EX.glob("*.BIN")):
        if p.name in ("D_NAMES.BIN", "STAYDAT.BIN"):
            continue
        c = raw_glyph_scan(p.read_bytes())
        hi = {g for g in c if SLOT_LO <= g < SLOT_HI}
        per_file[p.name] = len(hi)
        others.update(c)

    live = {g for g in (set(keep) | set(others)) if SLOT_LO <= g < SLOT_HI}
    freed_only = {g for g in drop if SLOT_LO <= g < SLOT_HI} - live
    free = set(range(SLOT_LO, SLOT_HI)) - live

    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    syl = {ch for r in L["records"] for s in r["spans"] if s["ko"]
           for ch in s["ko"] if "\uac00" <= ch <= "\ud7a3"}

    print("== 원시 토큰 스캔: 파일별 16x16 글리프 종수 (과대 집계) ==")
    for k, v in sorted(per_file.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<16}{v:>5}")
    print(f"\n16x16 슬롯 총량      {SLOT_HI - SLOT_LO:>6}")
    print(f"번역 후 살아야 할 글리프 {len(live):>6}")
    print(f"  D_NAMES 잔존만        {len({g for g in keep if SLOT_LO<=g<SLOT_HI}):>6}")
    print(f"  타 blob(과대)         {len({g for g in others if SLOT_LO<=g<SLOT_HI}):>6}")
    print(f"번역으로 완전히 비는 슬롯 {len(freed_only):>6}")
    print(f"가용 슬롯            {len(free):>6}")
    print(f"한글 수요            {len(syl):>6}")
    print(f"수지                 {len(free) - len(syl):>+6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
