#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a derived Japanese view of M_BANKS runtime-window candidates.

The raw bytes (including the structural FF terminator) remain authoritative.
Every slot in the 56 non-null fixed pointer tables is inventoried.  A Unicode
view is emitted only when a token-aware FF occurs inside the consumer's 0x400
byte read window.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

from analyze_structures import analyze_mbanks, text_end
from decode_dnames import decode, load_mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "_work" / "extract" / "DAT" / "M_BANKS.BIN"
DEFAULT_MAP = (
    ROOT
    / "_work"
    / "reference"
    / "srwcb-korean-patch"
    / "font"
    / "srwcb_embedded_font_mapping_reviewed.json"
)
DEFAULT_OUTPUT = ROOT / "_work" / "analysis" / "mbanks_candidate_manifest.tsv"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--glyph-map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = args.data.read_bytes()
    mapping_bytes = args.glyph_map.read_bytes()
    mapping = load_mapping(args.glyph_map)
    report = analyze_mbanks()
    source_hash = sha256(data)
    mapping_hash = sha256(mapping_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "stable_id",
        "header_index",
        "entry",
        "selector_hex",
        "pointer_hex",
        "bank_base_hex",
        "crosses_64k_bank",
        "shared_pointer_uses",
        "decode_status",
        "source_sha256",
        "runtime_window_sha256",
        "raw_record_sha256",
        "raw_hex_including_ff",
        "japanese_derived",
        "mapping_confidence_counts",
        "unresolved_glyph_ids",
        "mapping_source_sha256",
        "authority",
    ]
    unresolved_total: Counter[int] = Counter()
    record_count = 0
    terminated_count = 0
    out_of_file_count = 0
    cross_bank_count = 0

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, dialect="excel-tab")
        writer.writeheader()
        for row in report["entries"]:
            if row.get("status") != "fixed-pointer-table" or not row.get("pointer_table_safe"):
                continue
            header_index = int(row["index"])
            table_offset = int(row["offset"], 16)
            bank_base = int(row["bank_base"], 16)
            pointer_count = 256
            relatives = struct.unpack_from(f"<{pointer_count}H", data, table_offset)
            pointers = [bank_base + relative for relative in relatives]
            pointer_uses = Counter(pointers)

            for entry, pointer in enumerate(pointers):
                if pointer >= len(data):
                    runtime_window = b""
                    end = None
                    decode_status = "pointer-target-out-of-file-unused-candidate"
                    out_of_file_count += 1
                else:
                    runtime_window = data[pointer : min(len(data), pointer + 0x400)]
                    try:
                        end = text_end(data, pointer, pointer + 0x400)
                    except ValueError:
                        end = None
                    decode_status = "no-structural-ff-within-0x400-runtime-window"
                if end is None:
                    raw = b""
                    text = ""
                    confidence = Counter()
                    unresolved = []
                    crosses_bank = None
                else:
                    raw = data[pointer : end + 1]
                    text, confidence, unresolved = decode(data, pointer, mapping)
                    crosses_bank = end >= bank_base + 0x10000
                    cross_bank_count += int(crosses_bank)
                    terminated_count += 1
                    unresolved_total.update(unresolved)
                    decode_status = "derived-candidate-token-terminated"
                writer.writerow(
                    {
                        "stable_id": f"M_BANKS:H{header_index:02d}:E{entry:04d}",
                        "header_index": header_index,
                        "entry": entry,
                        "selector_hex": f"0x{0x9000 + header_index * 0x100 + entry:04X}",
                        "pointer_hex": f"0x{pointer:X}",
                        "bank_base_hex": f"0x{bank_base:X}",
                        "crosses_64k_bank": (
                            "" if crosses_bank is None else ("true" if crosses_bank else "false")
                        ),
                        "shared_pointer_uses": pointer_uses[pointer],
                        "decode_status": decode_status,
                        "source_sha256": source_hash,
                        "runtime_window_sha256": sha256(runtime_window) if runtime_window else "",
                        "raw_record_sha256": sha256(raw) if raw else "",
                        "raw_hex_including_ff": raw.hex().upper(),
                        "japanese_derived": text.replace("\r", "").replace("\n", "\\n"),
                        "mapping_confidence_counts": json.dumps(
                            confidence, ensure_ascii=False, sort_keys=True
                        ),
                        "unresolved_glyph_ids": ",".join(
                            f"{value:03X}" for value in sorted(set(unresolved))
                        ),
                        "mapping_source_sha256": mapping_hash,
                        "authority": (
                            "derived-cross-version-runtime-candidate; "
                            "raw bytes including structural FF remain authoritative"
                        ),
                    }
                )
                record_count += 1

    print(
        f"slots={record_count} token_terminated={terminated_count} "
        f"out_of_file_targets={out_of_file_count} "
        f"cross_bank_records={cross_bank_count} "
        f"unresolved_occurrences={sum(unresolved_total.values())} output={args.output}"
    )
    if unresolved_total:
        print("unresolved=" + ", ".join(f"{key:03X}:{value}" for key, value in unresolved_total.most_common()))


if __name__ == "__main__":
    main()
