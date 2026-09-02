#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""가시성 PoC 빌더.

증명 대상
  1. 한글 비트맵을 STAYDAT 내장 글꼴 은행에 넣으면 게임 자신의 렌더 경로로 화면에 나온다.
  2. 재할당한 글리프 ID로 다시 인코딩한 문자열이 한국어로 표시된다.
  3. 위 두 변경이 크기 보존 raw 섹터 교체로 디스크에 들어가고 다시 읽힌다.

정책
  * 문자열은 원본 레코드 길이(FF 포함)를 넘지 않는다. 넘으면 실패한다.
  * 글리프 ID는 mid bank(0x100-0x4FF) 안에서만 재할당한다. 이 PoC는 0x100-0x2FF만 쓴다.
  * 원본 파일은 수정하지 않는다. 산출물은 build/ 아래에만 만든다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from hangul_font import HangulFont          # noqa: E402
from text_codec import glyph_bytes, parse_record  # noqa: E402

EXTRACT = ROOT / "extract"
BUILD = ROOT / "build"
MANIFEST = ROOT / "analysis" / "dnames_raw_manifest.tsv"

# STAYDAT 내부 좌표 (records/FONT.md, ARCHITECTURE.md)
STAY_FONT_MID = 0x37838          # glyph ID 0x100-0x4FF, 32 bytes each
STAY_DNAMES = 0x49800            # D_NAMES.BIN 사본 시작

POC_ID_START = 0x100
POC_ID_END = 0x2FF               # inclusive

# (stable_id, 한국어, 메모)
TARGETS = [
    ("D_NAMES:S14:E0000", "발단",       "1화 시나리오 제목"),
    ("D_NAMES:S11:E0001", "도로",       "지형"),
    ("D_NAMES:S11:E0005", "평원",       "지형"),
    ("D_NAMES:S11:E0007", "숲",         "지형"),
    ("D_NAMES:S11:E0008", "산",         "지형"),
    ("D_NAMES:S11:E0010", "심해",       "지형"),
    ("D_NAMES:S11:E0012", "사막",       "지형"),
    ("D_NAMES:S11:E0013", "군사기지",   "지형"),
    ("D_NAMES:S11:E0014", "광자력연구소", "지형"),
    ("D_NAMES:S06:E0009", "료마",       "파일럿 풀네임"),
    ("D_NAMES:S06:E0010", "하야토",     "파일럿 풀네임"),
    ("D_NAMES:S06:E0011", "벤케이",     "파일럿 풀네임"),
    ("D_NAMES:S06:E0012", "호조신고",   "파일럿 풀네임"),
    ("D_NAMES:S07:E0009", "료",         "파일럿 약칭"),
]


def load_manifest() -> dict[str, dict[str, str]]:
    with MANIFEST.open(encoding="utf-8") as fh:
        return {row["stable_id"]: row for row in csv.DictReader(fh, delimiter="\t")}


def main() -> int:
    font = HangulFont()
    manifest = load_manifest()
    BUILD.mkdir(exist_ok=True)

    # 1) 글리프 할당 --------------------------------------------------------
    needed: list[str] = []
    for _, ko, _memo in TARGETS:
        for ch in ko:
            if ch not in font:
                raise SystemExit(f"KS X 1001 밖 문자: {ch}")
            if ch not in needed:
                needed.append(ch)

    alloc: dict[str, int] = {}
    next_id = POC_ID_START
    for ch in needed:
        alloc[ch] = next_id
        next_id += 1

    # 남은 슬롯은 순차 KS X 1001로 채워 한자 페이지가 통째로 한글이 되게 한다.
    filler = [c for c in font.syllables if c not in alloc]
    fi = 0
    while next_id <= POC_ID_END and fi < len(filler):
        alloc[filler[fi]] = next_id
        next_id += 1
        fi += 1
    print(f"글리프 할당: 0x{POC_ID_START:03X}-0x{next_id-1:03X} ({next_id-POC_ID_START}자), "
          f"PoC 전용 {len(needed)}자")

    # 2) STAYDAT 사본에 글꼴 주입 ------------------------------------------
    stay = bytearray((EXTRACT / "DAT" / "STAYDAT.BIN").read_bytes())
    dnames = bytearray((EXTRACT / "DAT" / "D_NAMES.BIN").read_bytes())
    orig_stay_len, orig_dnames_len = len(stay), len(dnames)

    for ch, gid in alloc.items():
        off = STAY_FONT_MID + (gid - 0x100) * 32
        stay[off:off + 32] = font.glyph(ch)

    # 3) 문자열 재인코딩 ----------------------------------------------------
    report = []
    for stable_id, ko, memo in TARGETS:
        row = manifest[stable_id]
        pointer = int(row["pointer_hex"], 16)
        original = bytes.fromhex(row["raw_hex_without_ff"]) + bytes.fromhex(row["terminator_hex"])
        parse_record(original)                       # 원본이 계약을 지키는지 확인
        new = b"".join(glyph_bytes(alloc[c]) for c in ko) + b"\xFF"
        if len(new) > len(original):
            raise SystemExit(f"{stable_id}: {ko!r} {len(new)}B > 원본 {len(original)}B")
        parse_record(new)                            # 새 레코드도 계약을 지키는지 확인

        for buf, base, label in ((dnames, 0, "D_NAMES.BIN"), (stay, STAY_DNAMES, "STAYDAT")):
            at = base + pointer
            if bytes(buf[at:at + len(original)]) != original:
                raise SystemExit(f"{stable_id}: {label} Expected Write 실패 @0x{at:X}")
            buf[at:at + len(new)] = new

        report.append(dict(stable_id=stable_id, memo=memo, korean=ko,
                           pointer=f"0x{pointer:04X}",
                           original_bytes=original.hex().upper(),
                           new_bytes=new.hex().upper(),
                           original_len=len(original), new_len=len(new)))
        print(f"  {stable_id} {memo}: {ko}  {len(original)}B -> {len(new)}B  @0x{pointer:04X}")

    if len(stay) != orig_stay_len or len(dnames) != orig_dnames_len:
        raise SystemExit("파일 크기가 변했다")

    (BUILD / "STAYDAT_poc.BIN").write_bytes(stay)
    (BUILD / "D_NAMES_poc.BIN").write_bytes(dnames)

    out = dict(
        glyph_alloc={f"0x{v:03X}": k for k, v in sorted(alloc.items(), key=lambda kv: kv[1])},
        poc_only_syllables=needed,
        id_range=[f"0x{POC_ID_START:03X}", f"0x{next_id-1:03X}"],
        strings=report,
        staydat_sha256=hashlib.sha256(stay).hexdigest(),
        dnames_sha256=hashlib.sha256(dnames).hexdigest(),
    )
    (ROOT / "analysis" / "poc_build_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STAYDAT_poc.BIN sha:", out["staydat_sha256"][:16])
    print("D_NAMES_poc.BIN sha:", out["dnames_sha256"][:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
