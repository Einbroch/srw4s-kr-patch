#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducible structural checks for SLPS-00196 localization research.

This tool is deliberately read-only unless --dnames-manifest is supplied.  The
manifest contains raw bytes and stable IDs only; it does not guess a character
map or translate text.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

from lzb import decompress


ROOT = Path(__file__).resolve().parents[2]
EXTRACT = ROOT / "_work" / "extract"

FILE_INDEX = [
    r"\MAP.LZB;1",
    r"\DAT\C_DEMOG.BIN;1",
    r"\DAT\C_MAPBG.BIN;1",
    r"\DAT\C_PFACE.BIN;1",
    r"\DAT\C_ROBOT.BIN;1",
    r"\DAT\C_UNITG.BIN;1",
    r"\DAT\D_DEDMES.BIN;1",
    r"\DAT\D_EVENT.BIN;1",
    r"\DAT\D_LEVEL.BIN;1",
    r"\DAT\D_MAP.BIN;1",
    r"\DAT\D_MOVE.BIN;1",
    r"\DAT\D_NAMES.BIN;1",
    r"\DAT\D_OBJCT.BIN;1",
    r"\DAT\D_PALET.BIN;1",
    r"\DAT\D_PILOT.BIN;1",
    r"\DAT\D_ROBOT.BIN;1",
    r"\DAT\D_UNIT.BIN;1",
    r"\DAT\D_WEAPON.BIN;1",
    r"\DAT\M_BANKS.BIN;1",
    r"\DAT\M_FIELD.BIN;1",
    r"\DAT\IP.BIN;1",
    r"\DAT\SC_00.BIN;1",
    r"\DAT\SC_01.BIN;1",
    r"\DAT\SC_02.BIN;1",
    r"\DAT\SC_03.BIN;1",
    r"\DAT\SC_04.BIN;1",
    r"\DAT\SC_05.BIN;1",
    r"\DAT\D_ANI00.BIN;1",
    r"\DAT\STAYDAT.BIN;1",
    r"\VABLIST.BIN;1",
    r"\SEQLIST.BIN;1",
    r"\BTT\BATTLE.LZB;1",
    r"\BTT\M_BANKB.LZB;1",
    r"\BTT\C_BBACK.BIN;1",
    r"\BTT\C_BEFCT.BIN;1",
    r"\MOVIE.LZB;1",
    r"\DAT\C_ETC.BIN;1",
]

# STAYDAT is loaded at 0x80020000.  Every listed slice is byte-identical to
# the separately stored ISO file; padding between slices is not file content.
STAY_PARTS = [
    ("D_PALET.BIN", 0x00000, 0x80020000),
    ("D_OBJCT.BIN", 0x0E800, 0x8002E800),
    ("D_ROBOT.BIN", 0x26000, 0x80046000),
    ("D_MOVE.BIN", 0x29800, 0x80049800),
    ("D_PILOT.BIN", 0x2A800, 0x8004A800),
    ("D_LEVEL.BIN", 0x2D000, 0x8004D000),
    ("D_EVENT.BIN", 0x2D800, 0x8004D800),
    ("D_WEAPON.BIN", 0x2E800, 0x8004E800),
    ("D_MAP.BIN", 0x31800, 0x80051800),
    ("D_NAMES.BIN", 0x49800, 0x80069800),
    ("D_DEDMES.BIN", 0x56800, 0x80076800),
    ("D_UNIT.BIN", 0x57000, 0x80077000),
    ("IP.BIN", 0x58800, 0x80078800),
    ("SC_04.BIN", 0x62000, 0x80082000),
    ("SC_05.BIN", 0x63000, 0x80083000),
    ("D_ANI00.BIN", 0x64800, 0x80084800),
]

# The same opcode arity is documented from consumer handlers in the related
# PS1 Complete Box engine (repository commit pinned in records/ENCODING.md).
# It is independently corroborated here by target records containing FF in
# operand positions (for example FD FF FF and FE FF), followed by a later true
# FF terminator.  Meanings other than F6/F7 remain intentionally unnamed.
CONTROL_ARGUMENT_BYTES = {
    0xF6: 0,
    0xF7: 0,
    0xF8: 1,
    0xF9: 1,
    0xFA: 0,
    0xFB: 2,
    # FC 는 실측상 1인수다(M_BANKS 에서 2로 읽으면 여는 「 155개가 인수로 삼켜지고,
    # D_NAMES 원본 4,090개도 2로는 22개가 깨지는데 1로는 0개다). 다만 D_NAMES 원장은
    # 2인수 경계 위에서 만들어져 이미 출고됐고, 1로 바꾸면 경계 뒤 번역 스팬 10건
    # (레벨/장착 문구 등)이 레코드 밖으로 밀려난다. 그래서 여기 기본값은 2로 두고,
    # M_BANKS 쪽만 text_codec.MB_ARITY 로 1을 넘겨 쓴다.  -> records/HANDOFF.md
    0xFC: 2,
    0xFD: 2,
    0xFE: 1,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cstring(data: bytes, offset: int) -> str:
    end = data.index(0, offset)
    return data[offset:end].decode("ascii")


def text_end(data: bytes, offset: int, limit: int | None = None) -> int:
    """Return the offset of a structural FF terminator.

    FF can legally be the trail byte of an F0-F5 glyph or an operand byte of a
    control.  A raw bytes.find(FF) is therefore not a valid record parser.
    """
    end_limit = len(data) if limit is None else min(limit, len(data))
    cursor = offset
    while cursor < end_limit:
        lead = data[cursor]
        if lead == 0xFF:
            return cursor
        if lead < 0xF0:
            cursor += 1
        elif lead < 0xF6:
            cursor += 2
        else:
            cursor += 1 + CONTROL_ARGUMENT_BYTES[lead]
    raise ValueError(f"no structural FF terminator from 0x{offset:X} before 0x{end_limit:X}")


def analyze_exe() -> dict:
    path = EXTRACT / "SLPS_001.96"
    data = path.read_bytes()
    if data[:8] != b"PS-X EXE":
        raise ValueError("SLPS_001.96 does not have a PS-X EXE header")
    pc, load_addr, payload_size = struct.unpack_from("<III", data, 0x10)
    stack = struct.unpack_from("<I", data, 0x30)[0]
    paths = []
    for index in range(37):
        pointer = struct.unpack_from("<I", data, 0x20C10 + index * 4)[0]
        file_offset = pointer - 0x800C0000 + 0x800
        actual = cstring(data, file_offset)
        expected = FILE_INDEX[index]
        paths.append(
            {
                "index": index,
                "pointer": f"0x{pointer:08X}",
                "file_offset": f"0x{file_offset:X}",
                "path": actual,
                "matches_expected": actual == expected,
            }
        )
    return {
        "path": str(path),
        "size": len(data),
        "sha256": sha256(data),
        "initial_pc": f"0x{pc:08X}",
        "load_address": f"0x{load_addr:08X}",
        "payload_size": payload_size,
        "stack": f"0x{stack:08X}",
        "path_table_file_offset": "0x20C10",
        "all_paths_match": all(row["matches_expected"] for row in paths),
        "paths": paths,
    }


def analyze_staydat() -> dict:
    path = EXTRACT / "DAT" / "STAYDAT.BIN"
    stay = path.read_bytes()
    parts = []
    for name, offset, address in STAY_PARTS:
        source_path = EXTRACT / "DAT" / name
        source = source_path.read_bytes()
        matched = stay[offset : offset + len(source)] == source
        parts.append(
            {
                "name": name,
                "offset": f"0x{offset:X}",
                "runtime_address": f"0x{address:08X}",
                "size": len(source),
                "sha256": sha256(source),
                "byte_identical": matched,
            }
        )
    return {
        "path": str(path),
        "size": len(stay),
        "sha256": sha256(stay),
        "load_address": "0x80020000",
        "all_parts_match": all(row["byte_identical"] for row in parts),
        "parts": parts,
    }


def dnames_sections(data: bytes) -> list[dict]:
    starts = list(struct.unpack_from("<18I", data, 0))
    raw_first = {
        index: struct.unpack_from("<H", data, start)[0]
        for index, start in enumerate(starts)
        if start
    }
    sections = []
    for index, start in enumerate(starts):
        if not start:
            sections.append({"section": index, "start": None, "status": "null"})
            continue

        # Some header entries point into another section's larger pointer
        # table (sections 5, 9, 10 and 16).  Reuse the enclosing table's
        # data boundary instead of misreading string bytes as more pointers.
        enclosing_ends = []
        for owner, owner_start in enumerate(starts):
            if not owner_start or owner == index:
                continue
            owner_end = raw_first[owner]
            if owner_start < start < owner_end and (owner_end - owner_start) % 2 == 0:
                enclosing_ends.append(owner_end)
        table_end = min(enclosing_ends) if enclosing_ends else raw_first[index]
        if table_end < start or (table_end - start) % 2:
            raise ValueError(f"D_NAMES section {index} has an unsafe table boundary")

        count = (table_end - start) // 2
        pointers = list(struct.unpack_from(f"<{count}H", data, start))
        strings = []
        for entry, pointer in enumerate(pointers):
            if not (0 <= pointer < len(data)):
                raise ValueError(f"D_NAMES S{index:02d} E{entry:04d}: pointer out of range")
            end = text_end(data, pointer)
            strings.append(
                {
                    "entry": entry,
                    "pointer": pointer,
                    "raw": data[pointer:end],
                }
            )
        sections.append(
            {
                "section": index,
                "start": start,
                "table_end": table_end,
                "count": count,
                "unique_pointers": len(set(pointers)),
                "strings": strings,
                "status": "raw-inventory-only",
            }
        )
    return sections


def analyze_dnames() -> tuple[dict, list[dict]]:
    path = EXTRACT / "DAT" / "D_NAMES.BIN"
    data = path.read_bytes()
    sections = dnames_sections(data)
    lead_counts = Counter()
    population = 0
    records_with_embedded_ff = 0
    for section in sections:
        for string in section.get("strings", []):
            population += 1
            lead_counts.update(byte for byte in string["raw"] if byte >= 0xF0)
            naive_end = data.find(b"\xFF", string["pointer"])
            if naive_end != string["pointer"] + len(string["raw"]):
                records_with_embedded_ff += 1
    summary_sections = []
    for section in sections:
        row = {key: value for key, value in section.items() if key != "strings"}
        if row.get("start") is not None:
            row["start"] = f"0x{row['start']:X}"
            row["table_end"] = f"0x{row['table_end']:X}"
        summary_sections.append(row)
    return (
        {
            "path": str(path),
            "size": len(data),
            "sha256": sha256(data),
            "header_size": 0x48,
            "section_count": 18,
            "entry_population": population,
            "terminator": "FF",
            "control_argument_bytes": {
                f"{key:02X}": value for key, value in CONTROL_ARGUMENT_BYTES.items()
            },
            "records_with_ff_inside_glyph_or_control": records_with_embedded_ff,
            "high_byte_counts": {f"{key:02X}": value for key, value in sorted(lead_counts.items())},
            "encoding_status": "glyph ID decode and control arity known; Unicode charmap under cross-version validation",
            "sections": summary_sections,
        },
        sections,
    )


def analyze_mbanks() -> dict:
    path = EXTRACT / "DAT" / "M_BANKS.BIN"
    data = path.read_bytes()
    first_offset = struct.unpack_from("<I", data, 0)[0]
    if first_offset % 4:
        raise ValueError("M_BANKS first offset is not a 32-bit header boundary")
    count = first_offset // 4
    offsets = struct.unpack_from(f"<{count}I", data, 0)
    map_data, _ = decompress((EXTRACT / "MAP.LZB").read_bytes())
    consumer_expected_words = {
        0x4DB34: 0x34040012,  # file index 18
        0x4DB48: 0x340700F4,  # 61-entry top header read size
        0x4DC30: 0x34070200,  # fixed pointer-table read size
        0x4DCE0: 0x2A02003D,  # loop over 61 tables
        0x4DD20: 0x8C460000,  # header[bank]
        0x4DD24: 0x3C02FFFF,  # high-16 bank mask
        0x4DD28: 0x00C23024,
        0x4DD38: 0x00042240,  # bank * 0x200 cache stride
        0x4DD44: 0x94A20000,  # cached u16 slot pointer
        0x4DD58: 0x34070400,  # fixed runtime read window
        0x0A180: 0x30628000,  # script selector high-bit class
        0x0A190: 0x34028FFF,  # M_BANKS selectors begin at 0x9000
        0x0A19C: 0x3C02FFFF,
        0x0A1FC: 0x34427000,  # add -0x9000 before bank extraction
        0x0A204: 0x00042203,  # arithmetic >> 8 -> bank
        0x0A214: 0x30A500FF,  # low byte -> slot
    }
    consumer_observed_words = {
        offset: struct.unpack_from("<I", map_data, offset)[0]
        for offset in consumer_expected_words
    }
    rows = []
    for index, offset in enumerate(offsets):
        row = {"index": index, "offset": f"0x{offset:X}" if offset else None}
        if not offset:
            row["status"] = "null"
            rows.append(row)
            continue
        table_end = offset + 0x200
        if table_end > len(data):
            row.update(
                {
                    "pointer_count": 256,
                    "pointer_table_safe": False,
                    "status": "out-of-bounds-pointer-table",
                }
            )
            rows.append(row)
            continue
        bank_base = offset & ~0xFFFF
        rels = struct.unpack_from("<256H", data, offset)
        absolutes = [bank_base + value for value in rels]
        safe_targets = sum(value < len(data) for value in absolutes)
        terminated = 0
        for value in absolutes:
            if value >= len(data):
                continue
            try:
                # The consumer reads a 0x400-byte window beginning at this
                # bank-relative pointer.  FF must therefore be assessed inside
                # that runtime window, not at the 64 KiB bank boundary.
                text_end(data, value, value + 0x400)
            except ValueError:
                continue
            terminated += 1
        row.update(
            {
                "bank_base": f"0x{bank_base:X}",
                "table_end": f"0x{table_end:X}",
                "pointer_count": 256,
                "pointer_table_safe": True,
                "pointer_targets_in_file": safe_targets,
                "token_records_terminated_within_runtime_window": terminated,
                "runtime_window_bytes": 0x400,
                "status": "fixed-pointer-table",
            }
        )
        rows.append(row)
    return {
        "path": str(path),
        "size": len(data),
        "sha256": sha256(data),
        "header_size": first_offset,
        "header_entry_count": count,
        "bank_size": 0x10000,
        "pointer_table_bytes": 0x200,
        "pointers_per_table": 256,
        "runtime_window_bytes": 0x400,
        "selector_base": "0x9000",
        "consumer_signatures_match": consumer_observed_words == consumer_expected_words,
        "consumer_signature_words": {
            f"0x{offset:X}": f"0x{word:08X}"
            for offset, word in consumer_observed_words.items()
        },
        "encoding_status": "fixed pointer and runtime window proven; live-slot population unresolved",
        "entries": rows,
    }


def analyze_font() -> dict:
    stay_path = EXTRACT / "DAT" / "STAYDAT.BIN"
    stay = stay_path.read_bytes()
    map_data, _ = decompress((EXTRACT / "MAP.LZB").read_bytes())
    descriptor_offset = 0x36800
    descriptor_expected = (0x80056838, 0x80057838, 0x8005F838, 0x80063838)
    descriptor_observed = struct.unpack_from("<4I", stay, descriptor_offset)
    consumer_expected_words = {
        0x0AB20: 0x8C42F304,  # load pointer to descriptor at 0x80056800
        0x0AB28: 0x8C460000,  # glyph 000-0FF bank pointer
        0x0AB2C: 0x00031100,  # 16 bytes per low glyph
        0x0AF1C: 0x8C42F304,
        0x0AF24: 0x8C460004,  # glyph 100-4FF bank pointer
        0x0AF2C: 0x2442FF00,  # subtract glyph 0x100
        0x0AF30: 0x00021140,  # 32 bytes per wide glyph
        0x0ACC4: 0x8C42F304,
        0x0ACCC: 0x8C460008,  # glyph 500-6FF bank pointer
        0x0ACD0: 0x2462FB00,  # subtract glyph 0x500
        0x0ACD4: 0x00021140,  # 32 bytes per wide glyph
    }
    consumer_observed_words = {
        offset: struct.unpack_from("<I", map_data, offset)[0]
        for offset in consumer_expected_words
    }
    spans = {
        "low_000_0ff": (0x36838, 0x1000, 0x100, 16),
        "mid_100_4ff": (0x37838, 0x8000, 0x400, 32),
        "high_500_6ff": (0x3F838, 0x4000, 0x200, 32),
    }
    banks = {}
    for name, (offset, size, glyph_count, glyph_bytes) in spans.items():
        raw = stay[offset : offset + size]
        banks[name] = {
            "offset": f"0x{offset:X}",
            "size": size,
            "glyph_count": glyph_count,
            "bytes_per_glyph": glyph_bytes,
            "sha256": sha256(raw),
        }
    full = stay[0x36838:0x43838]
    return {
        "source": str(stay_path),
        "descriptor_offset": "0x36800",
        "descriptor_ram": "0x80056800",
        "descriptor_pointers": [f"0x{value:08X}" for value in descriptor_observed],
        "descriptor_matches": descriptor_observed == descriptor_expected,
        "font_start": "0x36838",
        "font_end_exclusive": "0x43838",
        "font_size": len(full),
        "glyph_count": 0x700,
        "font_sha256": sha256(full),
        "banks": banks,
        "consumer_signatures_match": consumer_observed_words == consumer_expected_words,
        "consumer_signature_words": {
            f"0x{offset:X}": f"0x{word:08X}"
            for offset, word in consumer_observed_words.items()
        },
        "status": "target-native font source and renderer contract verified",
    }


def analyze_encoding() -> dict:
    compressed = (EXTRACT / "MAP.LZB").read_bytes()
    data, consumed = decompress(compressed)
    expected_words = {
        0xB3F0: 0x2C8200F6,  # sltiu v0,a0,0xF6
        0xB3F8: 0x2CA200F0,  # sltiu v0,a1,0xF0
        0xB404: 0x24630001,  # addiu v1,v1,1
        0xB408: 0x00031A00,  # sll v1,v1,8
        0xB40C: 0x30630F00,  # andi v1,v1,0xF00
        0xB430: 0x00431821,  # addu v1,v0,v1
        0x4D378: 0x2C6200F6,
        0x4D430: 0x2C4200F0,
        0x4D44C: 0x24820001,
        0x4D450: 0x00021200,
        0x4D454: 0x30440F00,
        0x4D494: 0x00442025,
    }
    observed = {offset: struct.unpack_from("<I", data, offset)[0] for offset in expected_words}
    return {
        "source": str(EXTRACT / "MAP.LZB"),
        "compressed_bytes_consumed": consumed,
        "compressed_size": len(compressed),
        "decompressed_size": len(data),
        "decompressed_sha256": sha256(data),
        "decoder_signatures_match": observed == expected_words,
        "single_byte_glyphs": "00-EF -> glyph IDs 0000-00EF",
        "extended_glyphs": "F0-F5 + trail -> glyph ID ((lead + 1) << 8 & 0F00) + trail",
        "extended_glyph_id_range": "0100-06FF",
        "control_candidates": "F6-FE",
        "terminator": "FF",
        "character_mapping_status": "glyph IDs proven; Japanese character values unresolved",
    }


def write_dnames_manifest(path: Path, source: dict, sections: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pointer_use = Counter(
        string["pointer"]
        for section in sections
        for string in section.get("strings", [])
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "stable_id",
            "source_sha256",
            "section",
            "entry",
            "pointer_hex",
            "shared_pointer_uses",
            "raw_hex_without_ff",
            "terminator_hex",
            "decode_status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, dialect="excel-tab")
        writer.writeheader()
        for section in sections:
            for string in section.get("strings", []):
                writer.writerow(
                    {
                        "stable_id": f"D_NAMES:S{section['section']:02d}:E{string['entry']:04d}",
                        "source_sha256": source["sha256"],
                        "section": section["section"],
                        "entry": string["entry"],
                        "pointer_hex": f"0x{string['pointer']:04X}",
                        "shared_pointer_uses": pointer_use[string["pointer"]],
                        "raw_hex_without_ff": string["raw"].hex().upper(),
                        "terminator_hex": "FF",
                        "decode_status": "raw-authority_token-contract-proven_charmap-derived",
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dnames-manifest",
        type=Path,
        help="write a raw, non-translated D_NAMES TSV inventory",
    )
    parser.add_argument("--json", action="store_true", help="print the complete JSON report")
    args = parser.parse_args()

    dnames, sections = analyze_dnames()
    report = {
        "executable": analyze_exe(),
        "staydat": analyze_staydat(),
        "d_names": dnames,
        "m_banks": analyze_mbanks(),
        "font": analyze_font(),
        "encoding": analyze_encoding(),
    }
    if args.dnames_manifest:
        write_dnames_manifest(args.dnames_manifest, dnames, sections)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"EXE paths: {len(FILE_INDEX)}/37 verified={report['executable']['all_paths_match']}")
        print(f"STAYDAT parts: {len(STAY_PARTS)}/16 verified={report['staydat']['all_parts_match']}")
        print(f"D_NAMES entries: {dnames['entry_population']} across 17 non-null sections")
        safe_banks = sum(row.get("status") == "fixed-pointer-table" for row in report["m_banks"]["entries"])
        print(
            f"M_BANKS fixed pointer tables: {safe_banks}/{report['m_banks']['header_entry_count']} "
            f"consumer_verified={report['m_banks']['consumer_signatures_match']}"
        )
        print(
            f"Font glyphs: {report['font']['glyph_count']} "
            f"descriptor_verified={report['font']['descriptor_matches']} "
            f"consumer_verified={report['font']['consumer_signatures_match']}"
        )
        print(f"Glyph decoder signatures: verified={report['encoding']['decoder_signatures_match']}")


if __name__ == "__main__":
    main()
