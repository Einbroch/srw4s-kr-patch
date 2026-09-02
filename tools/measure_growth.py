#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 성장 수요 실측.

추정 대신, 같은 시리즈의 도너(컴플리트 박스) 한국어 번역을 우리 D_NAMES의 일본어
파생 보기에 매칭해 **실제 한국어 문자열**의 인코딩 크기를 잰다.

인코딩 비용
  * low bank(글리프 ID < 0xF0)에 있는 문자(ASCII·숫자·기호) = 1 byte
  * 그 밖(완성형 한글 포함)                                   = 2 bytes
  * 레코드마다 종단 FF                                        = 1 byte
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections            # noqa: E402
from decode_dnames import load_mapping, DEFAULT_MAP, TARGET_CHARACTER_OVERRIDES  # noqa: E402

DONOR = ROOT / "reference" / "srwcb-korean-patch" / "translation"
DN = ROOT / "extract" / "DAT" / "D_NAMES.BIN"
DEC = ROOT / "analysis" / "dnames_decoded_candidate.tsv"

TOKEN = re.compile(r"⟦[^⟧]*⟧")


def build_lowbank_chars() -> set[str]:
    mapping = load_mapping(DEFAULT_MAP)
    low = set()
    for gid, row in mapping.items():
        if gid < 0xF0:
            ch = TARGET_CHARACTER_OVERRIDES.get(gid, row.get("character") or "")
            if ch:
                low.add(ch)
    for gid, ch in TARGET_CHARACTER_OVERRIDES.items():
        if gid < 0xF0:
            low.add(ch)
    # 타깃 charmap 추가 확정: low bank 글리프 0x000은 실제 비트맵이 전부 0인 빈 8x16이다
    # (STAYDAT 0x36838 기준 확인). 도달 가능한 유일한 **반각 공백**이므로 공백을 1바이트로
    # 인코딩한다. 0x0F0-0x0FF도 비어 있지만 F0-FF는 lead/제어라 글리프 코드로 못 만든다.
    low.add(" ")
    return low


def donor_pairs() -> dict[str, str]:
    pairs: dict[str, str] = {}

    def put(jp, ko):
        if not jp or not ko:
            return
        jp = jp.strip()
        ko = ko.strip()
        if jp and ko and jp != ko:
            pairs.setdefault(jp, ko)

    for name in ("second_ui_names_overlay.json", "third_ui_translations.json"):
        p = DONOR / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for t in d.get("tables", []):
            for r in t.get("rows", []):
                put(r.get("japanese"), r.get("korean"))
    for name in ("second_ui_tables_overlay.json", "ex_ui_translations.json"):
        p = DONOR / name
        if not p.exists():
            p = DONOR.parent / "ex-ui" / "data" / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for t in d.get("tables", []):
            for r in t.get("entries", []):
                put(r.get("source_text"), r.get("korean_text"))
    for name in ("msgpool_translations.json", "third_ui_translations.json"):
        p = DONOR / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(k, str) and isinstance(v, str):
                    put(k, v)
    return pairs


def cost(text: str, low: set[str]) -> int:
    return sum(1 if ch in low else 2 for ch in text)


def main() -> int:
    low = build_lowbank_chars()
    pairs = donor_pairs()
    data = DN.read_bytes()
    sections = dnames_sections(data)
    dec = {r["stable_id"]: r["japanese_derived"]
           for r in csv.DictReader(DEC.open(encoding="utf-8"), delimiter="\t")}

    per_section = defaultdict(lambda: dict(records=0, matched=0, jp_bytes=0,
                                           ko_bytes=0, plain=0))
    seen: set[int] = set()
    total = dict(records=0, matched=0, jp_bytes=0, ko_bytes=0)
    samples = []
    for sec in sections:
        if sec["start"] is None:
            continue
        s = sec["section"]
        for st in sec["strings"]:
            p = st["pointer"]
            if p in seen:            # 공유 포인터는 한 번만 센다
                continue
            seen.add(p)
            sid = f"D_NAMES:S{s:02d}:E{st['entry']:04d}"
            jp = dec.get(sid, "")
            raw_len = len(st["raw"])
            bucket = per_section[s]
            bucket["records"] += 1
            bucket["jp_bytes"] += raw_len
            total["records"] += 1
            total["jp_bytes"] += raw_len
            plain = not TOKEN.search(jp) and jp.strip() != ""
            if plain:
                bucket["plain"] += 1
            ko = pairs.get(jp.strip()) if plain else None
            if ko:
                new = cost(ko, low) + 1
                bucket["matched"] += 1
                bucket["ko_bytes"] += new
                total["matched"] += 1
                total["ko_bytes"] += new
                if len(samples) < 25 and new != raw_len:
                    samples.append((sid, jp, ko, raw_len, new))
            else:
                bucket["ko_bytes"] += raw_len          # 미매칭은 원본 크기로 둔다

    print(f"고유 레코드 {total['records']}개, 도너 매칭 {total['matched']}개 "
          f"({total['matched']/total['records']*100:.1f}%)")
    print(f"{'sec':>4} {'rec':>5} {'plain':>6} {'match':>6} {'jp_B':>8} {'ko_B*':>8} {'증가':>8}")
    for s in sorted(per_section):
        b = per_section[s]
        d = b["ko_bytes"] - b["jp_bytes"]
        print(f"S{s:02d} {b['records']:>6} {b['plain']:>6} {b['matched']:>6} "
              f"{b['jp_bytes']:>8} {b['ko_bytes']:>8} {d:>+8}")
    # 매칭된 부분만으로 성장률을 낸다(미매칭을 원본으로 둔 총합은 과소평가라서)
    m_jp = m_ko = 0
    for sec in sections:
        if sec["start"] is None:
            continue
    matched_jp = matched_ko = 0
    seen2 = set()
    for sec in sections:
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            p = st["pointer"]
            if p in seen2:
                continue
            seen2.add(p)
            sid = f"D_NAMES:S{sec['section']:02d}:E{st['entry']:04d}"
            jp = dec.get(sid, "")
            if TOKEN.search(jp) or not jp.strip():
                continue
            ko = pairs.get(jp.strip())
            if ko:
                matched_jp += len(st["raw"])
                matched_ko += cost(ko, low) + 1
    ratio = matched_ko / matched_jp if matched_jp else 0
    print(f"\n매칭 구간 실측 성장률: {matched_jp} -> {matched_ko} bytes ({ratio:.3f}x, "
          f"{(ratio-1)*100:+.1f}%)")
    print(f"전체 문자열 바이트 {total['jp_bytes']}에 이 비율을 적용하면 "
          f"약 {int(total['jp_bytes']*ratio)} bytes (증가 {int(total['jp_bytes']*(ratio-1))})")
    print("\n표본(원본 크기 != 한국어 크기):")
    for sid, jp, ko, a, b in samples[:18]:
        print(f"  {sid} {jp[:16]!r} -> {ko[:16]!r}  {a}B -> {b}B")

    (ROOT / "analysis" / "dnames_growth_measured.json").write_text(json.dumps(dict(
        records=total["records"], matched=total["matched"],
        matched_jp_bytes=matched_jp, matched_ko_bytes=matched_ko,
        measured_ratio=ratio, all_string_bytes=total["jp_bytes"],
        projected_bytes=int(total["jp_bytes"] * ratio),
        per_section={f"S{k:02d}": v for k, v in sorted(per_section.items())},
    ), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
