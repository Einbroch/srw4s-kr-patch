#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BTT/C_BEFCT.BIN 한국어판 — **M_BANKB 의 세 번째 사본**을 고친다.

C_BEFCT.BIN 꼬리(0x66EEF ~ 파일 끝)에 LZB 스트림이 하나 박혀 있고,
그게 풀리면 77,429 B 가 나오는데 그 안 **+0xA8 에 M_BANKB 55,353 B 가 통째로** 들어 있다.
게임은 맵 대화 장면에서 이쪽을 RAM 0x80107AE4 로 풀어 쓴다(실기 브레이크포인트로 확인).
전투에서는 BTT/M_BANKB.LZB 를 읽는다 — 그래서 한 벌만 고치면 **화면 절반만 한글**이 된다.

  2026-09-01 실기: 디스크 392MB 전 바이트에 원본 M_BANKB 가 없는데도 RAM 에 통째로
  올라와 있었다. 압축된 채 다른 파일 안에 숨어 있었기 때문이다 —
  해제본으로 훑는 검색은 이런 사본을 절대 못 잡는다. [[font-duplicate-copies]] 와 같은 유형.

스트림이 파일 맨 끝에서 끝나므로 뒤로 늘릴 수 있다. 한글은 커지므로 파일이
1섹터 자란다(229 -> 230). 그 자리는 BTT/M_BANKB.LZB 를 꼬리로 옮겨 비운다.
"""
from __future__ import annotations
import hashlib, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lzb, lzb_encode                          # noqa: E402

SRC = ROOT / "extract" / "BTT" / "C_BEFCT.BIN"
MB_ORIG = ROOT / "build" / "M_BANKB_raw.bin"
MB_KO = ROOT / "build" / "M_BANKB_ko_noext.dec"   # 확장 구간을 안 쓴 판
OUT = ROOT / "build" / "C_BEFCT_ko.BIN"
STREAM = 0x66EEF                                # 파일 안 LZB 스트림 시작


def main() -> int:
    f = SRC.read_bytes()
    dec, end = lzb.decompress(f, STREAM)
    if end != len(f):
        print(f"FAIL: 스트림이 파일 끝({len(f)})이 아니라 {end} 에서 끝난다")
        return 1
    data = bytearray(dec)

    orig, ko = MB_ORIG.read_bytes(), MB_KO.read_bytes()
    if len(orig) != len(ko):
        print(f"FAIL: M_BANKB 길이가 다르다 {len(orig)} != {len(ko)}")
        return 1
    at = bytes(data).find(orig)
    if at < 0:
        print("FAIL: 이 스트림 안에서 원본 M_BANKB 를 못 찾았다")
        return 1
    if bytes(data).count(orig) != 1:
        print("FAIL: M_BANKB 사본이 이 스트림 안에 둘 이상이다")
        return 1
    data[at:at + len(ko)] = ko

    # --- 블롭 밖 확장 구간은 **여기 넣으면 안 된다** (2026-09-04 실기 회귀) ---
    # 이 컨테이너는 RAM 0x80107AE4 에 풀리고 M_BANKB 는 +0xA8 이라 전투용 사본과
    # 블롭 시작 주소가 같다. 그래서 블롭 뒤 확장 구간(BATTLE 오버레이에 열어 둔 자리)에
    # 옮긴 레코드를 여기에도 넣어야 맵 대화가 읽는다고 판단해 9,670 B 를 써 넣었다.
    #
    # **틀렸다.** 읽기 브레이크포인트로 "안 읽힌다"고 확인한 것은 **BATTLE 오버레이**의
    # 그 자리였지, 이 컨테이너의 같은 오프셋이 아니다. 두 자리는 내용이 전혀 다르고
    # (BATTLE: `00 01 fd 8c 00 c0 27...` / 여기: `00 01 fa af 1b 00...`),
    # 이 컨테이너 쪽은 맵 대화가 쓰는 산 데이터였다. 덮어쓰자 맵 대화가
    # 통째로 비거나 레코드 중간부터 읽혔다.
    #
    # 확장 구간은 **BATTLE 오버레이에만** 쓴다. 맵 경로도 쓰게 하려면 먼저 이 컨테이너의
    # 같은 자리에 읽기 브레이크포인트를 걸어 안 읽히는 걸 따로 확인해야 한다.

    data = bytes(data)
    print(f"해제 {len(dec):,} B / M_BANKB 위치 0x{at:X} / 교체 {len(ko):,} B")

    comp = lzb_encode.compress(data)
    back, _ = lzb.decompress(comp)
    if bytes(back) != data:
        print("FAIL: 재압축 왕복 불일치")
        return 1

    out = f[:STREAM] + comp
    # 번역이 늘수록 압축본이 작아져 섹터 수가 줄고(229 -> 228) 제자리 교체가 거부된다.
    # 스트림은 종단 표시로 끝나므로 뒤에 0을 붙여도 무해하다 — 원본 크기까지 채운다.
    if len(out) < len(f):
        out = out + bytes(len(f) - len(out))
    OUT.write_bytes(out)
    old_sec, new_sec = (len(f) + 2047) // 2048, (len(out) + 2047) // 2048
    print(f"압축 {end - STREAM:,} -> {len(comp):,} B  ({len(comp) - (end - STREAM):+,})")
    print(f"파일 {len(f):,} -> {len(out):,} B  ({old_sec} -> {new_sec}섹터)")
    print(f"-> {OUT.relative_to(ROOT)}  sha {hashlib.sha256(out).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
