#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a derived Japanese view of D_NAMES without replacing raw authority."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from analyze_structures import CONTROL_ARGUMENT_BYTES, dnames_sections, text_end


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "_work" / "extract" / "DAT" / "D_NAMES.BIN"
DEFAULT_MAP = (
    ROOT
    / "_work"
    / "reference"
    / "srwcb-korean-patch"
    / "font"
    / "srwcb_embedded_font_mapping_reviewed.json"
)
DEFAULT_OUTPUT = ROOT / "_work" / "analysis" / "dnames_decoded_candidate.tsv"

# Target-specific corrections supported by D_NAMES context.  In particular,
# section 4 contains the canonical robot name νガンダム; the donor review's
# U+221A interpretation of this visually similar low glyph is not portable.
TARGET_CHARACTER_OVERRIDES = {
    0x005: "ν",  # νガンダム
    0x100: "兜",  # 兜甲児
    0x348: "汎",  # 汎用性 / 汎用機
    0x3FF: "　",  # target-native bitmap is blank; numeric/UI spacer
    0x515: "桜",  # 桜野マリ
    0x562: "魂",  # 魂の安息 / 魂を浄化
    0x596: "遷",  # 左遷される
    0x5C2: "閥",  # 財閥
    0x5F7: "慕",  # 思慕 / 慕う
    0x646: "愾",  # 敵愾心
    0x649: "毅",  # 毅然
    0x652: "候",  # 立候補 / 候補生
    0x667: "惨",  # 大惨事
    0x698: "逐",  # 逐次投入
    0x6FE: "▲",  # target-native triangle symbol
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_mapping(path: Path) -> dict[int, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["glyph_index"]): row for row in payload["rows"] if int(row["glyph_index"]) < 0x700}


def decode(data: bytes, start: int, mapping: dict[int, dict]) -> tuple[str, Counter, list[int]]:
    cursor = start
    end = text_end(data, start)
    output = []
    confidence = Counter()
    unresolved = []
    while cursor < end:
        lead = data[cursor]
        if lead < 0xF0:
            glyph = lead
            cursor += 1
        elif lead < 0xF6:
            glyph = ((((lead + 1) << 8) & 0x0F00) | data[cursor + 1])
            cursor += 2
        else:
            argc = CONTROL_ARGUMENT_BYTES[lead]
            operands = data[cursor + 1 : cursor + 1 + argc]
            if lead == 0xF6:
                output.append("\n")
            elif argc:
                output.append(f"⟦{lead:02X}:{operands.hex().upper()}⟧")
            else:
                output.append(f"⟦{lead:02X}⟧")
            cursor += 1 + argc
            continue

        row = mapping.get(glyph)
        char = TARGET_CHARACTER_OVERRIDES.get(glyph)
        if char is None:
            char = row.get("character") if row else None
        if glyph == 0:
            output.append("　")
            confidence["exact-blank"] += 1
        elif char:
            output.append(char)
            confidence[
                "target-override" if glyph in TARGET_CHARACTER_OVERRIDES else str(row.get("confidence", "unknown"))
            ] += 1
        else:
            output.append(f"⟦G:{glyph:03X}⟧")
            unresolved.append(glyph)
            confidence["unresolved"] += 1
    return "".join(output), confidence, unresolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--glyph-map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = args.data.read_bytes()
    mapping_bytes = args.glyph_map.read_bytes()
    mapping = load_mapping(args.glyph_map)
    sections = dnames_sections(data)
    source_hash = sha256(data)
    mapping_hash = sha256(mapping_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    unresolved_total = Counter()
    count = 0
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "stable_id",
            "source_sha256",
            "pointer_hex",
            "japanese_derived",
            "mapping_confidence_counts",
            "unresolved_glyph_ids",
            "mapping_source_sha256",
            "authority",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, dialect="excel-tab")
        writer.writeheader()
        for section in sections:
            for string in section.get("strings", []):
                text, confidence, unresolved = decode(data, string["pointer"], mapping)
                unresolved_total.update(unresolved)
                writer.writerow(
                    {
                        "stable_id": f"D_NAMES:S{section['section']:02d}:E{string['entry']:04d}",
                        "source_sha256": source_hash,
                        "pointer_hex": f"0x{string['pointer']:04X}",
                        "japanese_derived": text.replace("\r", "").replace("\n", "\\n"),
                        "mapping_confidence_counts": json.dumps(confidence, ensure_ascii=False, sort_keys=True),
                        "unresolved_glyph_ids": ",".join(f"{value:03X}" for value in sorted(set(unresolved))),
                        "mapping_source_sha256": mapping_hash,
                        "authority": "derived-cross-version; raw manifest remains authoritative",
                    }
                )
                count += 1
    print(f"records={count} unresolved_occurrences={sum(unresolved_total.values())} output={args.output}")
    if unresolved_total:
        print("unresolved=" + ", ".join(f"{key:03X}:{value}" for key, value in unresolved_total.most_common()))


if __name__ == "__main__":
    main()
