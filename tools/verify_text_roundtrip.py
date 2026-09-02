#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify byte-identical token round trips across proven text inventories."""
from __future__ import annotations

import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

from analyze_structures import analyze_mbanks, dnames_sections, text_end
from text_codec import encode_tokens, glyph_bytes, parse_record


ROOT = Path(__file__).resolve().parents[2]
EXTRACT = ROOT / "_work" / "extract" / "DAT"
OUTPUT = ROOT / "_work" / "analysis" / "text_roundtrip_report.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_record(raw: bytes, controls: Counter[int]) -> None:
    tokens = parse_record(raw)
    rebuilt = encode_tokens(tokens)
    if rebuilt != raw:
        raise ValueError("record round trip mismatch")
    controls.update(token.opcode for token in tokens if token.kind == "control" and token.opcode is not None)


def main() -> None:
    # Exhaustive glyph-ID encode/decode sanity: 240 low + 6*256 extended.
    representable = list(range(0xF0)) + list(range(0x100, 0x700))
    for glyph_id in representable:
        encoded = glyph_bytes(glyph_id)
        tokens = parse_record(encoded + b"\xFF")
        if tokens[0].glyph_id != glyph_id or encode_tokens(tokens) != encoded + b"\xFF":
            raise ValueError(f"glyph round trip failed at 0x{glyph_id:X}")

    dnames_path = EXTRACT / "D_NAMES.BIN"
    dnames = dnames_path.read_bytes()
    d_controls: Counter[int] = Counter()
    d_records = []
    for section in dnames_sections(dnames):
        for string in section.get("strings", []):
            start = string["pointer"]
            end = text_end(dnames, start)
            raw = dnames[start : end + 1]
            verify_record(raw, d_controls)
            d_records.append(raw)

    mbanks_path = EXTRACT / "M_BANKS.BIN"
    mbanks = mbanks_path.read_bytes()
    m_controls: Counter[int] = Counter()
    m_records = []
    m_slots = 0
    m_out_of_file = 0
    m_no_terminator = 0
    for row in analyze_mbanks()["entries"]:
        if row.get("status") != "fixed-pointer-table":
            continue
        table_offset = int(row["offset"], 16)
        bank_base = int(row["bank_base"], 16)
        for relative in struct.unpack_from("<256H", mbanks, table_offset):
            m_slots += 1
            start = bank_base + relative
            if start >= len(mbanks):
                m_out_of_file += 1
                continue
            try:
                end = text_end(mbanks, start, start + 0x400)
            except ValueError:
                m_no_terminator += 1
                continue
            raw = mbanks[start : end + 1]
            verify_record(raw, m_controls)
            m_records.append(raw)

    report = {
        "status": "pass",
        "representable_glyph_ids": len(representable),
        "d_names": {
            "source_sha256": sha256(dnames),
            "record_occurrences": len(d_records),
            "unique_raw_records": len({sha256(raw) for raw in d_records}),
            "roundtrip_mismatches": 0,
            "control_occurrences": {f"{key:02X}": value for key, value in sorted(d_controls.items())},
        },
        "m_banks": {
            "source_sha256": sha256(mbanks),
            "runtime_slots": m_slots,
            "token_terminated_records": len(m_records),
            "unique_raw_records": len({sha256(raw) for raw in m_records}),
            "out_of_file_targets": m_out_of_file,
            "no_terminator_in_runtime_window": m_no_terminator,
            "roundtrip_mismatches": 0,
            "control_occurrences": {f"{key:02X}": value for key, value in sorted(m_controls.items())},
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
