#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 번역 원장 생성기 (재실행 가능).

구조: **span 단위**다. 레코드 전체를 역문으로 바꾸지 않고, 레코드 안의 번역 대상 구간만
교체하고 나머지 바이트(창 그리기 타일, 제어 토큰, 이름입력 격자)는 그대로 둔다.
도너(`second_ui_scripts_overlay.json`)가 같은 모델을 쓴다.

보호 필드(추출기 소유, 번역 단계에서 수정 금지)
    source.*, record.pointer, record.raw_hex, record.owners, span.start/end/jp
수정 가능 필드(번역 단계 소유)
    span.ko, span.status, span.note

재실행 시 기존 원장의 ko/status/note는 보존하고 보호 필드만 다시 채운다.
보호 필드가 달라지면 그 레코드를 `stale`로 표시해 차단한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_structures import dnames_sections          # noqa: E402
from span_classify import translatable_strict as translatable  # noqa: E402
from span_classify import charmap as _charmap                    # noqa: E402
from text_codec import parse_record                              # noqa: E402


def _overrides():
    """휴리스틱이 잘못 버린 스팬을 강제로 포함시킨다 (translation/span_overrides.json)."""
    p = ROOT / "translation" / "span_overrides.json"
    if not p.exists():
        return {}
    out = {}
    for rid, a, b, _why in json.loads(p.read_text(encoding="utf-8"))["force_include"]:
        out.setdefault(rid, []).append((a, b))
    return out


def _decode(raw_with_ff, a, b):
    m = _charmap(); pos = 0; chars = []
    for t in parse_record(raw_with_ff):
        if t.kind == "glyph" and a <= pos < b:
            chars.append(m.get(t.glyph_id, ""))
        pos += len(t.raw)
    return "".join(chars)
from measure_growth import build_lowbank_chars, donor_pairs  # noqa: E402

DN = ROOT / "extract" / "DAT" / "D_NAMES.BIN"
LEDGER = ROOT / "translation" / "dnames_ledger.json"
TOKEN = re.compile(r"⟦[^⟧]*⟧")


def cost(text: str, low: set[str]) -> int:
    """타깃 인코딩 바이트 수. low bank 문자는 1바이트, 나머지는 2바이트."""
    return sum(1 if ch in low else 2 for ch in text)


def main() -> int:
    data = DN.read_bytes()
    src_sha = hashlib.sha256(data).hexdigest()
    low = build_lowbank_chars()
    pairs = donor_pairs()

    old = {}
    if LEDGER.exists():
        prev = json.loads(LEDGER.read_text(encoding="utf-8"))
        for rec in prev["records"]:
            old[rec["id"]] = rec

    sections = dnames_sections(data)
    owners = defaultdict(list)
    for sec in sections:
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            owners[st["pointer"]].append(f"S{sec['section']:02d}:E{st['entry']:04d}")

    records = []
    seen = set()
    parse_fail = 0
    for sec in sections:
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            p = st["pointer"]
            if p in seen:
                continue
            seen.add(p)
            raw = st["raw"] + bytes([0xFF])
            rid = f"DN:{p:04X}"
            try:
                spans = translatable(st["raw"])
            except Exception:
                parse_fail += 1
                spans = []
            for a, b in _overrides().get(rid, []):
                if not any(x[0] == a and x[1] == b for x in spans):
                    spans.append((a, b, _decode(raw, a, b)))
            spans.sort(key=lambda x: x[0])

            prev = old.get(rid, {})
            prev_spans = {(s["start"], s["end"]): s for s in prev.get("spans", [])}

            span_out = []
            for a, b, jp in spans:
                keep = prev_spans.get((a, b), {})
                if keep and keep.get("jp") != jp:
                    keep = {}                    # 보호 필드가 바뀌었으면 역문을 재검증 대상으로
                ko = keep.get("ko", "")
                status = keep.get("status", "untranslated")
                note = keep.get("note")
                if not ko:
                    seed = pairs.get(jp.strip())
                    if seed:
                        ko, status = seed, "needs_review"
                        note = "donor-seeded (srwcb); 검토 필요"
                span_out.append(dict(start=a, end=b, jp=jp, ko=ko,
                                     status=status, note=note))

            stale = bool(prev) and prev.get("raw_hex") != raw.hex().upper()
            records.append(dict(
                id=rid, pointer=f"0x{p:04X}", owners=owners[p],
                raw_hex=raw.hex().upper(), raw_len=len(raw),
                spans=span_out,
                status="stale" if stale else None,
            ))

    # 집계
    n_span = sum(len(r["spans"]) for r in records)
    n_seed = sum(1 for r in records for s in r["spans"] if s["status"] == "needs_review")
    n_todo = sum(1 for r in records for s in r["spans"] if s["status"] == "untranslated")
    span_bytes = sum(s["end"] - s["start"] for r in records for s in r["spans"])
    total_bytes = sum(r["raw_len"] for r in records)
    # 현재 원장 기준 투영 크기(역문 있으면 그 비용, 없으면 원문 유지)
    proj = 0
    for r in records:
        n = r["raw_len"]
        for s in r["spans"]:
            if s["ko"]:
                n += cost(s["ko"], low) - (s["end"] - s["start"])
        proj += n

    tables = sum(sec["table_end"] - sec["start"] for sec in sections if sec["start"] is not None)
    ledger = dict(
        schema="srw4s-dnames-ledger-v1",
        model="span-replacement; 보호 필드 밖 바이트는 그대로 보존한다",
        source=dict(file="extract/DAT/D_NAMES.BIN", sha256=src_sha, size=len(data),
                    sections=len([s for s in sections if s["start"] is not None]),
                    pointer_table_bytes=tables),
        protected_fields=["source", "id", "pointer", "owners", "raw_hex", "raw_len",
                          "spans[].start", "spans[].end", "spans[].jp"],
        editable_fields=["spans[].ko", "spans[].status", "spans[].note"],
        statuses=["untranslated", "in_progress", "needs_review",
                  "needs_human_review", "complete"],
        statistics=dict(records=len(records), spans=n_span,
                        donor_seeded=n_seed, untranslated=n_todo,
                        parse_failures=parse_fail,
                        record_bytes=total_bytes, span_bytes=span_bytes,
                        projected_record_bytes=proj,
                        projected_total=72 + tables + proj,
                        slot_budget=53248, window_ceiling=65536),
        records=records,
    )
    LEDGER.parent.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")

    st = ledger["statistics"]
    print(f"레코드 {st['records']}개, span {st['spans']}개 (파싱 실패 {parse_fail})")
    print(f"  도너 seed {st['donor_seeded']}개 / 미번역 {st['untranslated']}개")
    print(f"  레코드 바이트 {st['record_bytes']}, 그중 번역 span {st['span_bytes']} "
          f"({st['span_bytes']/st['record_bytes']*100:.1f}%)")
    print(f"  현재 원장 기준 투영: 레코드 {st['projected_record_bytes']} + 표 {tables} + 72 "
          f"= {st['projected_total']}")
    print(f"    슬롯 {st['slot_budget']} 대비 {st['projected_total']-st['slot_budget']:+d}, "
          f"창 한계 {st['window_ceiling']} 대비 {st['projected_total']-st['window_ceiling']:+d}")
    print("->", LEDGER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
