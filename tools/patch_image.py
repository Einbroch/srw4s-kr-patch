#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SRW4S Track 1(MODE2/2352) 제자리 파일 교체기.

정책
  * 같은 크기 교체만 허용한다. 크기가 바뀌면 실패한다(재배치는 별도 게이트).
  * Expected Write: 쓰기 전에 대상 LBA의 현재 사용자 데이터가 원본 추출본과
    바이트 동일한지 확인한다. 다르면 중단한다.
  * sync/header/subheader는 건드리지 않는다. 사용자 데이터만 덮고 EDC/ECC를
    다시 계산한다.
  * 마지막 섹터의 파일 밖 패딩 바이트는 원본 값을 그대로 보존한다.
  * 쓴 뒤 같은 추출기로 다시 읽어 교체본과 바이트 동일한지 검증한다.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "reference" / "srwcb-korean-patch" / "tools"))

from isotool import Disc, RAW, HDR, USER            # noqa: E402
from patch_raw_track_exes import rebuild_mode2_form1  # noqa: E402


def load_listing(path: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("FILE\t"):
            continue
        _, lba, size, full = line.split("\t")
        out[full.split(";")[0].lstrip("/")] = (int(lba), int(size))
    return out


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_file(track: Path, lba: int, size: int) -> bytes:
    disc = Disc(str(track))
    try:
        return disc.read(lba, size)
    finally:
        disc.f.close()


def patch_in_place(track: Path, lba: int, size: int, original: bytes, payload: bytes,
                   label: str) -> int:
    if len(payload) != size:
        raise ValueError(f"{label}: 크기 변경 불가 {size} -> {len(payload)}")
    if len(original) != size:
        raise ValueError(f"{label}: 원본 추출본 크기 불일치")
    count = (size + USER - 1) // USER
    with track.open("r+b") as fh:
        for i in range(count):
            fh.seek((lba + i) * RAW)
            sector = bytearray(fh.read(RAW))
            if len(sector) != RAW:
                raise ValueError(f"{label}: 섹터 {lba+i} 잘림")
            here = original[i * USER:(i + 1) * USER]
            if sector[HDR:HDR + len(here)] != here:
                raise ValueError(f"{label}: Expected Write 실패 — 섹터 {lba+i}의 현재 "
                                 f"내용이 원본과 다르다")
            chunk = payload[i * USER:(i + 1) * USER]
            sector[HDR:HDR + len(chunk)] = chunk
            rebuild_mode2_form1(sector)
            fh.seek((lba + i) * RAW)
            fh.write(sector)
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="원본 Track 1 .bin")
    ap.add_argument("--out", required=True, help="패치 결과 .bin")
    ap.add_argument("--listing", default=str(ROOT / "records" / "iso-listing.txt"))
    ap.add_argument("--extract", default=str(ROOT / "extract"),
                    help="원본 추출 루트 (Expected Write 기준)")
    ap.add_argument("--replace", action="append", default=[], metavar="ISO=FILE",
                    help="예: DAT/STAYDAT.BIN=build/STAYDAT_ko.BIN")
    ap.add_argument("--fresh", action="store_true", help="out이 있어도 원본에서 다시 복사")
    args = ap.parse_args()

    src, out = Path(args.source), Path(args.out)
    listing = load_listing(Path(args.listing))
    extract_root = Path(args.extract)

    if args.fresh or not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        print(f"복사: {src.name} -> {out}")

    for spec in args.replace:
        iso, _, newfile = spec.partition("=")
        if iso not in listing:
            raise SystemExit(f"listing에 없음: {iso}")
        lba, size = listing[iso]
        original = (extract_root / iso).read_bytes()
        payload = Path(newfile).read_bytes()
        sectors = patch_in_place(out, lba, size, original, payload, iso)
        back = read_file(out, lba, size)
        ok = back == payload
        print(f"{iso}: lba={lba} size={size} sectors={sectors} "
              f"sha={sha(payload)[:16]} 재추출일치={ok}")
        if not ok:
            raise SystemExit(f"{iso}: 재추출 검증 실패")

    print("out:", out, "sha256:", sha(out.read_bytes())[:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
