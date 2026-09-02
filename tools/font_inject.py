#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""글꼴 주입 공용 모듈 — **폰트는 디스크에 두 벌 있다.**

  STAYDAT.BIN  [low 0x36838][mid 0x37838][high 0x3F838]
  C_DEMOG.BIN  [mid 0x41afc][low 0x49afc][high 0x4aafc]     ← 뱅크 순서가 다르다

세 뱅크 모두 두 파일에서 바이트 동일하다. 한쪽만 주입하면 그 파일을 쓰지 않는 화면에서는
원본 한자가 그대로 나온다(2026-08-23: STAYDAT 만 주입해 mid 뱅크 한글이 전부 한자로 나왔다).
새 소비자가 나오면 여기 COPIES 에 추가하고 `verify_font_copies.py` 로 확인한다.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

# (이름, 추출 경로, 산출 경로, {뱅크: 오프셋})
COPIES = [
    ("STAYDAT", "DAT/STAYDAT.BIN", "STAYDAT_ko.BIN",
     {"low": 0x36838, "mid": 0x37838, "high": 0x3F838}),
    ("C_DEMOG", "DAT/C_DEMOG.BIN", "C_DEMOG_ko.BIN",
     {"low": 0x49AFC, "mid": 0x41AFC, "high": 0x4AAFC}),
]
BANK_LEN = {"low": 0x1000, "mid": 0x8000, "high": 0x4000}
BANK_SHA = {                      # 원본 뱅크 해시 (두 파일 공통)
    "low":  "1e0d2b04dd0f8bfb01a4dcb27a3a8b4de35b0c9e9fb1a10a06f6f5f0e9d8e0b4",
    "mid":  "",
    "high": "",
}


def bank_of(gid: int) -> str:
    if 0x100 <= gid < 0x500:
        return "mid"
    if 0x500 <= gid <= 0x6FF:
        return "high"
    raise ValueError(f"16x16 슬롯이 아니다: 0x{gid:X}")


def glyph_offset(offs: dict, gid: int) -> int:
    b = bank_of(gid)
    base = offs[b]
    return base + (gid - (0x100 if b == "mid" else 0x500)) * 32


def load_alloc() -> dict:
    return json.loads((ROOT / "translation" / "glyph_alloc.json").read_text(encoding="utf-8"))


def inject(data: bytearray, offs: dict, alloc: dict, font) -> int:
    preserved = {int(k, 16) for k in alloc["preserved_ids"]}
    n = 0
    for ch, hexid in alloc["hangul"].items():
        gid = int(hexid, 16)
        if gid in preserved:
            raise SystemExit(f"보존 글리프 0x{gid:03X}에 한글을 덮으려 한다")
        bm = font.glyph(ch)
        if len(bm) != 32:
            raise SystemExit(f"{ch} 비트맵이 32B가 아니다 ({len(bm)}B)")
        o = glyph_offset(offs, gid)
        data[o:o + 32] = bm
        n += 1
    return n


def bank_hashes(data: bytes, offs: dict) -> dict:
    return {b: hashlib.sha256(data[offs[b]:offs[b] + BANK_LEN[b]]).hexdigest()
            for b in BANK_LEN}
