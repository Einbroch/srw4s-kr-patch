#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect consumer-bounded M_BANKS references and their nested FB closure.

The script VM uses an 8-byte opcode table in the decompressed MAP overlay:
the argument length is at 0x274 + opcode*8 and the handler pointer is at
0x278 + opcode*8.  Opcodes C4-CC write a packed bank/slot value into the
16-byte message-display records consumed by MAP 0x4D0A0.  Bit 15 is a state
flag cleared by MAP 0xDCB8 before the packed value is split into bank/slot.

This tool deliberately reports the entry-point/fallthrough population as a
consumer-bounded static catalog.  It does not claim CFG completeness: handler
directed jumps and dynamically selected roots remain a separate review item.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from analyze_structures import text_end
from lzb import decompress
from text_codec import parse_record


ROOT = Path(__file__).resolve().parents[2]
EXTRACT = ROOT / "_work" / "extract" / "DAT"
ANALYSIS = ROOT / "_work" / "analysis"
MAP_PATH = ROOT / "_work" / "extract" / "MAP.LZB"
MBANKS_PATH = EXTRACT / "M_BANKS.BIN"

VM_LENGTH_BASE = 0x274
VM_HANDLER_BASE = 0x278
VM_ENTRY_SIZE = 8


@dataclass(frozen=True)
class ScriptSpec:
    name: str
    path: Path
    pointer_count: int
    runtime_base: int
    runtime_window_bytes: int | None
    runtime_route: str


SCRIPT_SPECS = (
    ScriptSpec(
        "SC_00",
        EXTRACT / "SC_00.BIN",
        168,
        0x801B0000,
        None,
        "file-index-21 -> RAM 0x801B0000 -> MAP global 0x8015F340",
    ),
    ScriptSpec(
        "SC_04",
        EXTRACT / "SC_04.BIN",
        128,
        0x80082000,
        None,
        "STAYDAT+0x62000 -> RAM 0x80082000 -> MAP global 0x8015F350",
    ),
    ScriptSpec(
        "SC_05",
        EXTRACT / "SC_05.BIN",
        224,
        0x80083000,
        None,
        "STAYDAT+0x63000 -> RAM 0x80083000 -> MAP global 0x8015F354",
    ),
)

# Operand offset, relative to the first byte after the opcode, containing the
# little-endian u16 field later consumed as record+6.
MESSAGE_FIELD_BY_OPCODE = {
    0xC4: 2,
    0xC5: 2,
    0xC6: 2,
    0xC7: 2,
    0xC8: 0,
    0xC9: 2,
    0xCA: 2,
    0xCB: 2,
    0xCC: 2,
}

CONTROL_FLOW_OPCODES = {
    0x01: "relative-jump",
    0x02: "absolute-jump",
    0x03: "relative-call",
    0x04: "return",
    0x60: "dynamic-source-switch",
}

EXPECTED_VM_HANDLERS = {
    0x01: (2, 0x801136A4),
    0x02: (4, 0x801136FC),
    0x03: (2, 0x80113768),
    0x04: (0, 0x80113810),
    0x60: (2, 0x8011A510),
    0xC3: (3, 0x8014F2F8),
    0xC4: (4, 0x8014F48C),
    0xC5: (4, 0x8014F580),
    0xC6: (4, 0x8014F660),
    0xC7: (4, 0x8014F738),
    0xC8: (2, 0x8014F810),
    0xC9: (5, 0x8014F858),
    0xCA: (6, 0x8014F94C),
    0xCB: (4, 0x8014FA68),
    0xCC: (4, 0x8014FB00),
}

EXPECTED_MAP_WORDS = {
    0x0A190: 0x34028FFF,  # >= 0x9000 selects M_BANKS in text FB handler
    0x0A210: 0x0C055020,  # jal 0x80154080
    0x0DC94: 0x94820006,  # lhu record+6
    0x0DCB8: 0x30427FFF,  # clear record-field state flag bit 15
    0x0DD54: 0x0C054D08,  # jal 0x80153420 record consumer
    0x4D164: 0x0C055020,  # record consumer -> M_BANKS
    0x59040: 0x8011046C,  # text control FB dispatch handler
}

EXPECTED_SELECTOR_STORES = {
    0x49150: 0xA423F3DA,
    0x49244: 0xA423F3DA,
    0x49324: 0xA423F3DA,
    0x493FC: 0xA423F3EA,
    0x494BC: 0xA423F3DA,
    0x4951C: 0xA423F3DA,
    0x49630: 0xA424F3DA,
    0x49724: 0xA423F3DA,
    0x497BC: 0xA423F3EA,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_vm_table(map_data: bytes) -> tuple[list[int], list[int]]:
    lengths = [
        struct.unpack_from("<I", map_data, VM_LENGTH_BASE + opcode * VM_ENTRY_SIZE)[0]
        for opcode in range(256)
    ]
    handlers = [
        struct.unpack_from("<I", map_data, VM_HANDLER_BASE + opcode * VM_ENTRY_SIZE)[0]
        for opcode in range(256)
    ]
    for opcode, expected in EXPECTED_VM_HANDLERS.items():
        observed = (lengths[opcode], handlers[opcode])
        if observed != expected:
            raise ValueError(
                f"VM opcode 0x{opcode:02X} changed: observed {observed}, expected {expected}"
            )
    for offset, expected in {**EXPECTED_MAP_WORDS, **EXPECTED_SELECTOR_STORES}.items():
        observed = struct.unpack_from("<I", map_data, offset)[0]
        if observed != expected:
            raise ValueError(
                f"MAP signature 0x{offset:X} changed: 0x{observed:08X} != 0x{expected:08X}"
            )
    return lengths, handlers


def script_roots(spec: ScriptSpec, data: bytes) -> tuple[int, ...]:
    table_bytes = spec.pointer_count * 2
    if table_bytes > len(data):
        raise ValueError(f"{spec.name}: pointer table exceeds file")
    roots = struct.unpack_from(f"<{spec.pointer_count}H", data, 0)
    nonzero = [value for value in roots if value]
    if not nonzero or min(nonzero) < table_bytes:
        raise ValueError(f"{spec.name}: pointer targets overlap the declared table")
    # A target exactly at EOF is an explicit empty/sentinel entry (SC_05 uses
    # it for the unused tail of its fixed table).
    if any(value > len(data) for value in nonzero):
        raise ValueError(f"{spec.name}: pointer target outside file")
    return roots


def collect_script_references(
    lengths: list[int], handlers: list[int]
) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    source_reports: list[dict] = []
    for spec in SCRIPT_SPECS:
        data = spec.path.read_bytes()
        roots = script_roots(spec, data)
        sites: dict[int, dict] = {}
        command_sites: set[int] = set()
        terminal_opcodes: Counter[int] = Counter()
        c3_sites: set[int] = set()
        root_walks = 0
        for root_index, root in enumerate(roots):
            if not root or root == len(data):
                continue
            root_walks += 1
            cursor = root
            walk_end = (
                len(data)
                if spec.runtime_window_bytes is None
                else min(len(data), root + spec.runtime_window_bytes)
            )
            seen: set[int] = set()
            while cursor < walk_end and cursor not in seen:
                seen.add(cursor)
                opcode = data[cursor]
                arg_length = lengths[opcode]
                if handlers[opcode] == 0:
                    terminal_opcodes[opcode] += 1
                    break
                command_end = cursor + 1 + arg_length
                if command_end > walk_end:
                    terminal_opcodes[-1] += 1
                    break
                command_sites.add(cursor)
                if opcode == 0xC3:
                    c3_sites.add(cursor)
                field_delta = MESSAGE_FIELD_BY_OPCODE.get(opcode)
                if field_delta is not None:
                    field_offset = cursor + 1 + field_delta
                    if field_offset + 2 > command_end:
                        raise ValueError(
                            f"{spec.name}: opcode 0x{opcode:02X} field exceeds command"
                        )
                    raw_value = struct.unpack_from("<H", data, field_offset)[0]
                    normalized = raw_value & 0x7FFF
                    site = sites.setdefault(
                        field_offset,
                        {
                            "source": spec.name,
                            "source_path": str(spec.path),
                            "source_sha256": sha256(data),
                            "runtime_route": spec.runtime_route,
                            "command_offset": cursor,
                            "operand_offset": field_offset,
                            "opcode": opcode,
                            "raw_value": raw_value,
                            "normalized": normalized,
                            "bank": normalized >> 8,
                            "slot": normalized & 0xFF,
                            "root_indices": set(),
                            "root_offsets": set(),
                        },
                    )
                    if site["raw_value"] != raw_value or site["opcode"] != opcode:
                        raise ValueError(f"{spec.name}: conflicting parse at 0x{field_offset:X}")
                    site["root_indices"].add(root_index)
                    site["root_offsets"].add(root)
                cursor = command_end

        for site in sites.values():
            rows.append(
                {
                    **{k: v for k, v in site.items() if k not in {"root_indices", "root_offsets"}},
                    "root_indices": ",".join(str(value) for value in sorted(site["root_indices"])),
                    "root_offsets": ",".join(f"0x{value:X}" for value in sorted(site["root_offsets"])),
                    "root_reference_count": len(site["root_indices"]),
                    "state_flag_bit15": bool(site["raw_value"] & 0x8000),
                }
            )
        control_flow_sites: Counter[str] = Counter()
        control_flow_target_classes: Counter[str] = Counter()
        control_flow_examples: list[dict] = []
        for command_offset in sorted(command_sites):
            opcode = data[command_offset]
            kind = CONTROL_FLOW_OPCODES.get(opcode)
            if kind is None:
                continue
            control_flow_sites[kind] += 1
            target: int | None = None
            target_runtime: int | None = None
            target_class = "runtime-dependent"
            if opcode in (0x01, 0x03):
                delta = struct.unpack_from("<h", data, command_offset + 1)[0]
                target = command_offset + 1 + delta
                target_runtime = spec.runtime_base + target
                target_class = (
                    "relative-in-source"
                    if 0 <= target < len(data)
                    else "relative-outside-source"
                )
            elif opcode == 0x02:
                absolute = struct.unpack_from("<I", data, command_offset + 1)[0]
                target = absolute - spec.runtime_base
                target_runtime = absolute
                target_class = (
                    "absolute-in-source"
                    if 0 <= target < len(data)
                    else "absolute-outside-source"
                )
            control_flow_target_classes[target_class] += 1
            if len(control_flow_examples) < 24:
                control_flow_examples.append(
                    {
                        "command_offset": f"0x{command_offset:X}",
                        "opcode": f"0x{opcode:02X}",
                        "kind": kind,
                        "target_class": target_class,
                        "target_offset": (
                            None
                            if target is None
                            else (
                                f"-0x{-target:X}" if target < 0 else f"0x{target:X}"
                            )
                        ),
                        "target_runtime_address": (
                            None
                            if target_runtime is None
                            else f"0x{target_runtime & 0xFFFFFFFF:08X}"
                        ),
                    }
                )
        source_reports.append(
            {
                "source": spec.name,
                "path": str(spec.path),
                "sha256": sha256(data),
                "size": len(data),
                "pointer_count": spec.pointer_count,
                "nonzero_root_count": sum(bool(value) for value in roots),
                "eof_sentinel_root_count": sum(value == len(data) for value in roots),
                "walkable_root_count": sum(0 < value < len(data) for value in roots),
                "unique_root_count": len(
                    set(value for value in roots if 0 < value < len(data))
                ),
                "root_walk_count": root_walks,
                "unique_command_sites_on_linear_walks": len(command_sites),
                "message_field_sites": len(sites),
                "c3_dynamic_message_sites": len(c3_sites),
                "control_flow_observed_on_linear_walks": {
                    "site_counts": dict(sorted(control_flow_sites.items())),
                    "target_classes": dict(sorted(control_flow_target_classes.items())),
                    "examples": control_flow_examples,
                    "qualification": (
                        "These sites come from the over-approximating linear walk. "
                        "They are evidence for the open CFG task, not proof that every "
                        "site or fallthrough is reachable."
                    ),
                },
                "terminal_opcodes": {
                    ("out-of-file" if opcode == -1 else f"0x{opcode:02X}"): count
                    for opcode, count in sorted(terminal_opcodes.items())
                },
                "runtime_route": spec.runtime_route,
                "runtime_base": f"0x{spec.runtime_base:08X}",
                "runtime_window_bytes": spec.runtime_window_bytes,
            }
        )
    return rows, source_reports


def mbanks_tables(data: bytes) -> tuple[tuple[int, ...], list[tuple[int, ...] | None]]:
    header_size = struct.unpack_from("<I", data, 0)[0]
    count = header_size // 4
    headers = struct.unpack_from(f"<{count}I", data, 0)
    tables: list[tuple[int, ...] | None] = []
    for header in headers:
        if not header:
            tables.append(None)
            continue
        if header + 0x200 > len(data):
            raise ValueError(f"M_BANKS pointer table 0x{header:X} is outside file")
        tables.append(struct.unpack_from("<256H", data, header))
    return headers, tables


def target_raw(
    data: bytes,
    headers: tuple[int, ...],
    tables: list[tuple[int, ...] | None],
    bank: int,
    slot: int,
) -> tuple[bytes | None, str, int | None]:
    if not 0 <= bank < len(headers):
        return None, "bank-out-of-range", None
    table = tables[bank]
    if table is None:
        return None, "null-bank", None
    offset = (headers[bank] & ~0xFFFF) + table[slot]
    if offset >= len(data):
        return None, "target-out-of-file", offset
    try:
        end = text_end(data, offset, offset + 0x400)
    except ValueError:
        return None, "no-terminator-in-runtime-window", offset
    return data[offset : end + 1], "token-terminated", offset


def load_candidate_previews() -> dict[str, str]:
    path = ANALYSIS / "mbanks_candidate_manifest.tsv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            row["stable_id"]: row.get("japanese_derived", "")
            for row in csv.DictReader(handle, delimiter="\t")
        }


def token_stats(records: list[bytes]) -> dict:
    glyph_ids: set[int] = set()
    glyph_occurrences = 0
    controls: Counter[str] = Counter()
    for raw in records:
        for token in parse_record(raw):
            if token.kind == "glyph":
                glyph_occurrences += 1
                assert token.glyph_id is not None
                glyph_ids.add(token.glyph_id)
            elif token.kind == "control":
                assert token.opcode is not None
                controls[f"{token.opcode:02X}"] += 1
    return {
        "record_occurrences": len(records),
        "unique_raw_records": len(set(records)),
        "glyph_occurrences": glyph_occurrences,
        "unique_glyph_ids": len(glyph_ids),
        "glyph_ids": glyph_ids,
        "control_occurrences": dict(sorted(controls.items())),
    }


def load_dnames_records() -> list[bytes]:
    path = ANALYSIS / "dnames_raw_manifest.tsv"
    if not path.exists():
        raise FileNotFoundError(f"required D_NAMES manifest is missing: {path}")
    records: list[bytes] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            records.append(bytes.fromhex(row["raw_hex_without_ff"]) + b"\xFF")
    return records


def build_closure(
    reference_rows: list[dict],
    mbanks_data: bytes,
    headers: tuple[int, ...],
    tables: list[tuple[int, ...] | None],
) -> tuple[list[dict], list[dict]]:
    evidence: dict[tuple[int, int], list[str]] = defaultdict(list)
    first_depth: dict[tuple[int, int], int] = {}
    first_parent: dict[tuple[int, int], str] = {}
    queue: deque[tuple[int, int]] = deque()

    def seed(bank: int, slot: int, why: str, depth: int = 0, parent: str = "") -> None:
        key = (bank, slot)
        evidence[key].append(why)
        if key not in first_depth:
            first_depth[key] = depth
            first_parent[key] = parent
            queue.append(key)

    for row in reference_rows:
        seed(
            row["bank"],
            row["slot"],
            f"{row['source']}:0x{row['operand_offset']:X}/op{row['opcode']:02X}",
        )

    # Exact direct consumers outside the C4-CC VM record path.
    seed(0x14, 0x00, "MAP:0x172B8/direct")
    seed(0x02, 0xA9, "MAP:0x17444/direct")
    for slot in range(0x30, 0x70):
        seed(0x00, slot, "MAP:0x4C668/direct-formula")
    for slot in range(0x65, 0x6D):
        seed(0x3C, slot, "MAP:0x42E40/C3-random-range")

    dynamic_fb: list[dict] = []
    processed: set[tuple[int, int]] = set()
    while queue:
        bank, slot = queue.popleft()
        if (bank, slot) in processed:
            continue
        processed.add((bank, slot))
        raw, status, target_offset = target_raw(
            mbanks_data, headers, tables, bank, slot
        )
        if raw is None:
            continue
        tokens = parse_record(raw)
        token_cursor = 0
        for token in tokens:
            if token.kind == "control" and token.opcode == 0xFB:
                if 0xFF in token.operands:
                    dynamic_fb.append(
                        {
                            "source_stable_id": f"M_BANKS:H{bank:02d}:E{slot:04d}",
                            "source_target_offset": target_offset,
                            "token_offset_in_record": token_cursor,
                            "operands_hex": token.operands.hex().upper(),
                            "status": "dynamic-FF-substitution",
                        }
                    )
                else:
                    selector = int.from_bytes(token.operands, "little")
                    if selector >= 0x9000:
                        packed = selector - 0x9000
                        child_bank = packed >> 8
                        child_slot = packed & 0xFF
                        seed(
                            child_bank,
                            child_slot,
                            (
                                f"M_BANKS:H{bank:02d}:E{slot:04d}"
                                f"+0x{token_cursor:X}/FB={selector:04X}"
                            ),
                            first_depth[(bank, slot)] + 1,
                            f"M_BANKS:H{bank:02d}:E{slot:04d}",
                        )
            token_cursor += len(token.raw)

    previews = load_candidate_previews()
    rows: list[dict] = []
    for bank, slot in sorted(first_depth):
        raw, status, target_offset = target_raw(
            mbanks_data, headers, tables, bank, slot
        )
        stable_id = f"M_BANKS:H{bank:02d}:E{slot:04d}"
        rows.append(
            {
                "stable_id": stable_id,
                "bank": bank,
                "slot": slot,
                "selector_hex": f"0x{0x9000 + bank * 0x100 + slot:04X}",
                "closure_depth": first_depth[(bank, slot)],
                "first_parent": first_parent[(bank, slot)],
                "evidence_count": len(evidence[(bank, slot)]),
                "evidence": " | ".join(evidence[(bank, slot)]),
                "target_offset": "" if target_offset is None else f"0x{target_offset:X}",
                "target_status": status,
                "raw_sha256": "" if raw is None else sha256(raw),
                "japanese_text": previews.get(stable_id, ""),
            }
        )
    return rows, dynamic_fb


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--references",
        type=Path,
        default=ANALYSIS / "mbanks_live_selector_refs.tsv",
    )
    parser.add_argument(
        "--closure",
        type=Path,
        default=ANALYSIS / "mbanks_live_closure.tsv",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ANALYSIS / "mbanks_live_selector_report.json",
    )
    args = parser.parse_args()

    map_data, consumed = decompress(MAP_PATH.read_bytes())
    lengths, handlers = read_vm_table(map_data)
    reference_rows, source_reports = collect_script_references(lengths, handlers)
    mbanks_data = MBANKS_PATH.read_bytes()
    headers, tables = mbanks_tables(mbanks_data)

    null_banks = {index for index, table in enumerate(tables) if table is None}
    for row in reference_rows:
        if row["bank"] >= len(headers):
            raise ValueError(
                f"{row['source']} selector at 0x{row['operand_offset']:X} has bank {row['bank']}"
            )
        if row["bank"] in null_banks:
            raise ValueError(
                f"{row['source']} selector at 0x{row['operand_offset']:X} uses null bank {row['bank']}"
            )
        row["stable_id"] = f"M_BANKS:H{row['bank']:02d}:E{row['slot']:04d}"
        row["selector_hex"] = f"0x{0x9000 + row['normalized']:04X}"
        row["command_offset"] = f"0x{row['command_offset']:X}"
        row["operand_offset"] = f"0x{row['operand_offset']:X}"
        row["opcode"] = f"0x{row['opcode']:02X}"
        row["raw_value"] = f"0x{row['raw_value']:04X}"
        row["normalized"] = f"0x{row['normalized']:04X}"
        row["bank"] = str(row["bank"])
        row["slot"] = str(row["slot"])
        row["state_flag_bit15"] = str(row["state_flag_bit15"]).lower()

    closure_rows, dynamic_fb = build_closure(
        [
            {
                **row,
                "bank": int(row["bank"]),
                "slot": int(row["slot"]),
                "operand_offset": int(row["operand_offset"], 16),
                "opcode": int(row["opcode"], 16),
            }
            for row in reference_rows
        ],
        mbanks_data,
        headers,
        tables,
    )

    closure_records: list[bytes] = []
    for row in closure_rows:
        raw, status, _ = target_raw(
            mbanks_data, headers, tables, row["bank"], row["slot"]
        )
        if raw is None or status != "token-terminated":
            raise ValueError(f"closure target {row['stable_id']} is not token-terminated")
        closure_records.append(raw)
    closure_token_stats = token_stats(closure_records)
    dnames_token_stats = token_stats(load_dnames_records())
    combined_glyph_ids = (
        closure_token_stats.pop("glyph_ids") | dnames_token_stats.pop("glyph_ids")
    )

    write_tsv(
        args.references,
        reference_rows,
        [
            "stable_id",
            "source",
            "source_path",
            "source_sha256",
            "runtime_route",
            "command_offset",
            "operand_offset",
            "opcode",
            "raw_value",
            "normalized",
            "state_flag_bit15",
            "bank",
            "slot",
            "selector_hex",
            "root_indices",
            "root_offsets",
            "root_reference_count",
        ],
    )
    write_tsv(
        args.closure,
        closure_rows,
        [
            "stable_id",
            "bank",
            "slot",
            "selector_hex",
            "closure_depth",
            "first_parent",
            "evidence_count",
            "evidence",
            "target_offset",
            "target_status",
            "raw_sha256",
            "japanese_text",
        ],
    )

    target_status = Counter(row["target_status"] for row in closure_rows)
    report = {
        "source_revision": {
            "map_lzb": str(MAP_PATH),
            "map_lzb_sha256": sha256(MAP_PATH.read_bytes()),
            "map_decompressed_sha256": sha256(map_data),
            "map_compressed_bytes_consumed": consumed,
            "mbanks": str(MBANKS_PATH),
            "mbanks_sha256": sha256(mbanks_data),
        },
        "consumer_contract": {
            "vm_length_formula": "MAP[0x274 + opcode*8] u32",
            "vm_handler_formula": "MAP[0x278 + opcode*8] u32",
            "message_opcodes": [f"0x{opcode:02X}" for opcode in MESSAGE_FIELD_BY_OPCODE],
            "record_field": "u16 little-endian at display record +6",
            "record_state_flag": "bit15 cleared before M_BANKS lookup",
            "packed_formula": "bank=(raw&0x7FFF)>>8; slot=raw&0xFF",
            "stable_selector_formula": "0x9000 + bank*0x100 + slot",
            "nested_message_control": "FB operands form little-endian selector; >=0x9000 routes to M_BANKS",
            "signatures_verified": True,
        },
        "scope": {
            "status": "consumer-bounded entry/fallthrough catalog; full CFG remains open",
            "included_sources": [source_report["source"] for source_report in source_reports],
            "excluded_sources": {
                "SC_01..SC_03": (
                    "opcode 0x60 connects root-selected 0x800-byte stage windows at "
                    "RAM 0x80080800/0x80081000/0x80081800, but promoting all 80 file "
                    "offsets as reachable roots yields invalid selectors; stage/root "
                    "reachability must be proven first"
                ),
                "raw scans": "not admissible as live-reference evidence",
            },
        },
        "sources": source_reports,
        "reference_field_site_count": len(reference_rows),
        "reference_target_count": len(
            set((row["stable_id"] for row in reference_rows))
        ),
        "reference_sites_with_bit15_flag": sum(
            row["state_flag_bit15"] == "true" for row in reference_rows
        ),
        "direct_formula_seed_count": 2 + 0x40 + 8,
        "closure_target_count": len(closure_rows),
        "closure_max_depth": max((row["closure_depth"] for row in closure_rows), default=0),
        "closure_target_status": dict(sorted(target_status.items())),
        "dynamic_fb_reference_count": len(dynamic_fb),
        "dynamic_fb_references": dynamic_fb,
        "font_capacity_baseline": {
            "representable_glyph_ids": 1776,
            "m_banks_consumer_bounded_closure": closure_token_stats,
            "d_names_full_inventory": dnames_token_stats,
            "combined_unique_source_glyph_ids": len(combined_glyph_ids),
            "conservative_slots_after_preserving_all_used_source_glyphs": (
                1776 - len(combined_glyph_ids)
            ),
            "qualification": (
                "This is a source-glyph capacity baseline, not Korean glyph demand. "
                "Final allocation requires the approved Korean corpus and decisions "
                "about which original glyphs must remain."
            ),
        },
        "outputs": {
            "references": str(args.references),
            "closure": str(args.closure),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"script reference sites: {len(reference_rows)}; "
        f"seed targets: {report['reference_target_count']}; "
        f"nested closure: {len(closure_rows)}; "
        f"dynamic FB: {len(dynamic_fb)}"
    )
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
