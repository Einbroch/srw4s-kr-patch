#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STAYDAT 한글판 빌드 — 글꼴 주입 + D_NAMES 슬라이스 교체.

STAYDAT는 통째로 RAM 0x80020000에 올라가고, 상주 blob들은 그 안의 슬라이스다.
  글꼴 mid  0x37838  ID 0x100-0x4FF (32B/글리프)
  글꼴 high 0x3F838  ID 0x500-0x6FF (32B/글리프)
  D_NAMES  0x49800-0x57000  (RAM 0x80069800, 55,296B)
           원래는 0x56800 까지였다. 바로 뒤 D_DEDMES 를 0x5D000 으로 옮겨
           2 KB 를 넘겨받았다 — `tools/relocate_dedmes.py` 참고.

원본 파일은 건드리지 않는다. 쓰기 전에 Expected Write로 대상 바이트를 확인한다.
"""
from __future__ import annotations
import hashlib, json, os, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from hangul_font import HangulFont   # noqa: E402

STAY = ROOT / "extract" / "DAT" / "STAYDAT.BIN"
FONT_LO, FONT_HI = 0x36838, 0x43838          # 전체 글꼴 구간
MID, HIGH = 0x37838, 0x3F838
DN_LO, DN_HI = 0x49800, 0x57000
# D_DEDMES 재배치 — 원래 0x56800 에 있던 1,166 B 를 잔재 구간으로 옮긴다.
# MAP 주소표(0x58FB4)도 같이 바꿔야 한다(`relocate_dedmes.py`).
DED_OLD, DED_NEW, DED_LEN = 0x56800, 0x5D000, 1166
DED_DST_SHA = "cb2797f8847125be9b6d264dc162c15970c0105e44c78e77bf5fdcf660c6a2bc"
# **M_BANKS 헤더와 포인터표가 STAYDAT 안에도 통째로 있다.**
#   +0x72800  헤더 61*4 = 244 B      (RAM 0x80092800)
#   +0x73000  표 61*0x200 = 31,232 B (RAM 0x80093000)
# M_BANKS 를 재배치하면 여기도 같이 갱신해야 한다. 파일만 고치면 게임은 옛 좌표로 읽는다
# (2026-08-24 실기: CD 읽기 대기 루프에서 정지). 글꼴이 두 벌이던 것과 같은 유형이다.
MB_HDR, MB_TBL = 0x72800, 0x73000
MB_BANKS = 61
FONT_SHA = "74b01b66d0708a0ed2b7747ec4cf4b31bcdd88a11c8f52049a9bb591e297835f"


def glyph_offset(gid: int) -> int:
    if 0x100 <= gid < 0x500:
        return MID + (gid - 0x100) * 32
    if 0x500 <= gid <= 0x6FF:
        return HIGH + (gid - 0x500) * 32
    raise ValueError(f"16x16 슬롯이 아니다: 0x{gid:X}")


def main() -> int:
    stay = bytearray(STAY.read_bytes())
    orig_len = len(stay)
    if hashlib.sha256(bytes(stay[FONT_LO:FONT_HI])).hexdigest() != FONT_SHA:
        print("FAIL: 원본 글꼴 구간 해시가 FONT.md와 다르다")
        return 1

    alloc = json.loads((ROOT / "translation" / "glyph_alloc.json").read_text(encoding="utf-8"))
    font = HangulFont()
    preserved = {int(k, 16) for k in alloc["preserved_ids"]}

    written = 0
    for ch, hexid in alloc["hangul"].items():
        gid = int(hexid, 16)
        if gid in preserved:
            print(f"FAIL: 보존 글리프 0x{gid:03X}에 한글을 덮으려 한다")
            return 1
        bm = font.glyph(ch)
        if len(bm) != 32:
            print(f"FAIL: {ch} 비트맵이 32B가 아니다 ({len(bm)}B)")
            return 1
        off = glyph_offset(gid)
        stay[off:off + 32] = bm
        written += 1

    # --- 전투 텍스트 풀 (0x72800~) ---
    # 전투 컷인의 실제 출처는 여기다. 상주 blob 이라 길이를 못 키우므로
    # 원문 바이트 수에 맞춘 짧은 역문을 넣고 남는 자리는 공백으로 메운다.
    import runpy
    from mb_codec import build_encoder as _be, encode as _enc
    _e = _be()
    _SP = _enc(" ", _e)[:-1]
    Q = runpy.run_path(str(ROOT / "translation" / "staydat_battle_ko.py"))["Q"]
    POOL = 0x72800
    hit, over, missing = 0, [], []
    for qj, qk in Q.items():
        bj, bk = _enc(qj, _e)[:-1], _enc(qk, _e)[:-1]
        if len(bk) > len(bj):
            over.append((qj, len(bj), len(bk))); continue
        bk = bk + _SP * (len(bj) - len(bk))
        i = bytes(stay).find(bj, POOL)
        if i < 0:
            missing.append(qj); continue
        while i >= 0:
            stay[i:i + len(bj)] = bk
            hit += 1
            i = bytes(stay).find(bj, i + len(bj))
    if over:
        for qj, a, b in over:
            print(f"FAIL 예산 초과 {a}B -> {b}B: {qj[:30]!r}")
        return 1
    print(f"전투 텍스트 풀: {len(Q)}종 / {hit}곳 교체"
          + (f" / 못 찾음 {len(missing)}종" if missing else ""))
    for qj in missing[:5]:
        print(f"  못 찾음: {qj[:40]!r}")

    if len(stay) != orig_len:
        print("FAIL: STAYDAT 크기가 변했다")
        return 1

    mb_path = ROOT / "build" / os.environ.get("SRW4S_MBANKS", "")
    if mb_path.name and mb_path.exists():
        mb = mb_path.read_bytes()
        first = struct.unpack_from("<I", mb, 0)[0]
        hdr = list(struct.unpack_from(f"<{first//4}I", mb, 0))
        if stay[MB_HDR:MB_HDR + first] != bytes(struct.pack(f"<{first//4}I",
                *struct.unpack_from(f"<{first//4}I",
                    (ROOT / "extract" / "DAT" / "M_BANKS.BIN").read_bytes(), 0))):
            print("FAIL: STAYDAT 의 M_BANKS 헤더 사본이 원본과 다르다")
            return 1
        stay[MB_HDR:MB_HDR + first] = mb[:first]
        n = 0
        for bi, off in enumerate(hdr):
            if not off or off + 0x200 > len(mb):
                continue
            stay[MB_TBL + bi * 0x200: MB_TBL + (bi + 1) * 0x200] = mb[off:off + 0x200]
            n += 1
        print(f"M_BANKS 사본 갱신: 헤더 {first}B + 표 {n}개  <- {mb_path.name}")

    ded = bytes(stay[DED_OLD:DED_OLD + DED_LEN])
    if ded != (ROOT / "extract" / "DAT" / "D_DEDMES.BIN").read_bytes():
        print("FAIL: STAYDAT 의 D_DEDMES 슬라이스가 별도 파일과 다르다")
        return 1
    if hashlib.sha256(bytes(stay[DED_NEW:DED_NEW + DED_LEN])).hexdigest() not in (
            DED_DST_SHA, hashlib.sha256(ded).hexdigest()):
        print("FAIL: D_DEDMES 옮길 자리가 예상과 다르다 (덮어쓰면 안 되는 내용일 수 있다)")
        return 1
    stay[DED_NEW:DED_NEW + DED_LEN] = ded
    print(f"D_DEDMES {DED_LEN:,}B  {DED_OLD:#07x} -> {DED_NEW:#07x}  (D_NAMES 슬롯 +2,048B)")

    dn = (ROOT / "build" / "D_NAMES_ko.BIN").read_bytes()
    cap = DN_HI - DN_LO
    if len(dn) > cap:
        print(f"FAIL: D_NAMES {len(dn):,}B > 슬라이스 {cap:,}B")
        return 1
    stay[DN_LO:DN_LO + len(dn)] = dn
    stay[DN_LO + len(dn):DN_HI] = bytes(cap - len(dn))     # 남은 자리는 0으로

    if len(stay) != orig_len:
        print("FAIL: STAYDAT 크기가 변했다")
        return 1

    out = ROOT / "build" / "STAYDAT_ko.BIN"
    left = [qj for qj in Q if bytes(stay).find(_enc(qj, _e)[:-1], POOL) >= 0]
    if left:
        print(f"경고: 풀에 일본어가 다시 남았다 {len(left)}종 (표 복사가 덮어썼을 수 있다)")
        for qj in left[:5]:
            print(f"  {qj[:36]!r}")

    out.write_bytes(stay)
    print(f"글리프 {written}자 주입 (mid/high bank)")
    print(f"D_NAMES 슬라이스 {len(dn):,}B / {cap:,}B  (여유 {cap-len(dn)}B)")
    print(f"STAYDAT {len(stay):,}B  sha {hashlib.sha256(stay).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
