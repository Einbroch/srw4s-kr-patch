#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""같은 섹터 수 안에서 파일 크기가 바뀌는 교체 (ISO 디렉터리 레코드 갱신 포함).

크기 보존 교체는 `patch_image.py`가 한다. 이 도구는 **파일이 커지되 원래 할당된
섹터 수를 넘지 않는** 경우만 다룬다(예: LZB 재압축본). LBA는 그대로 두고
디렉터리 레코드의 data length(LE+BE 양쪽)만 고쳐 쓴다.

정책
  * 섹터 수가 달라지면 실패한다(재배치는 별도 게이트).
  * Expected Write: 쓰기 전에 해당 LBA의 현재 내용이 원본 추출본과 같아야 한다.
  * 마지막 섹터의 파일 밖 잔여 바이트는 건드리지 않는다.
  * 사용자 데이터만 고치고 sync/header/subheader는 그대로, EDC/ECC만 재계산한다.
  * 쓴 뒤 같은 경로로 다시 읽어 바이트 동일을 확인하고, 디렉터리 레코드도 되읽어 검증한다.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "reference" / "srwcb-korean-patch" / "tools"))

from isotool import Disc, RAW, HDR, USER              # noqa: E402
from patch_raw_track_exes import rebuild_mode2_form1  # noqa: E402


def load_listing(path: Path):
    files, dirs = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("FILE\t", "DIR\t")):
            kind, lba, size, full = line.split("\t")
            key = full.split(";")[0].lstrip("/").rstrip("/")
            (files if kind == "FILE" else dirs)[key] = (int(lba), int(size))
    return files, dirs


def find_dir_record(track: Path, dir_lba: int, dir_size: int, name: str):
    """디렉터리 extent 안에서 이름이 일치하는 레코드의 (이미지 절대 오프셋, 길이)."""
    disc = Disc(str(track))
    try:
        data = disc.read(dir_lba, dir_size)
    finally:
        disc.f.close()
    target = name.encode("ascii")
    off = 0
    while off < len(data):
        ln = data[off]
        if ln == 0:
            off = (off // USER + 1) * USER
            if off >= len(data):
                break
            continue
        namelen = data[off + 32]
        if data[off + 33:off + 33 + namelen] == target:
            sector = dir_lba + off // USER
            in_sec = off % USER
            return sector, in_sec, ln
        off += ln
    raise SystemExit(f"디렉터리 레코드를 찾지 못했다: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--listing", default=str(ROOT / "records" / "iso-listing.txt"))
    ap.add_argument("--extract", default=str(ROOT / "extract"))
    ap.add_argument("--replace", action="append", default=[], metavar="ISO=FILE")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    src, out = Path(args.source), Path(args.out)
    files, dirs = load_listing(Path(args.listing))
    extract_root = Path(args.extract)

    if args.fresh or not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        print(f"복사: {src.name} -> {out}")

    for spec in args.replace:
        iso, _, newfile = spec.partition("=")
        if iso not in files:
            raise SystemExit(f"listing에 없음: {iso}")
        lba, old_size = files[iso]
        original = (extract_root / iso).read_bytes()
        if len(original) != old_size:
            raise SystemExit(f"{iso}: 추출본 크기 불일치")
        payload = Path(newfile).read_bytes()
        old_sectors = (old_size + USER - 1) // USER
        new_sectors = (len(payload) + USER - 1) // USER
        if new_sectors != old_sectors:
            raise SystemExit(f"{iso}: 섹터 수가 달라진다 {old_sectors} -> {new_sectors} "
                             f"(재배치 게이트 필요)")

        # 1) Expected Write + 사용자 데이터 교체
        with out.open("r+b") as fh:
            for i in range(old_sectors):
                fh.seek((lba + i) * RAW)
                sector = bytearray(fh.read(RAW))
                here = original[i * USER:(i + 1) * USER]
                if sector[HDR:HDR + len(here)] != here:
                    raise SystemExit(f"{iso}: Expected Write 실패 — 섹터 {lba+i}")
                chunk = payload[i * USER:(i + 1) * USER]
                sector[HDR:HDR + len(chunk)] = chunk
                rebuild_mode2_form1(sector)
                fh.seek((lba + i) * RAW)
                fh.write(sector)

            # 2) 디렉터리 레코드의 data length 갱신
            parent = "/".join(iso.split("/")[:-1])
            leaf = iso.split("/")[-1] + ";1"
            if parent:
                if parent not in dirs:
                    raise SystemExit(f"부모 디렉터리를 listing에서 못 찾음: {parent}")
                d_lba, d_size = dirs[parent]
            else:
                d_lba, d_size = 22, 2048          # root (PVD의 root dir)
            sec, in_sec, reclen = find_dir_record(out, d_lba, d_size, leaf)
            fh.seek(sec * RAW)
            ds = bytearray(fh.read(RAW))
            rec = HDR + in_sec
            cur_lba = struct.unpack_from("<I", ds, rec + 2)[0]
            cur_size = struct.unpack_from("<I", ds, rec + 10)[0]
            if cur_lba != lba or cur_size != old_size:
                raise SystemExit(f"{iso}: 디렉터리 레코드 불일치 lba={cur_lba} size={cur_size}")
            struct.pack_into("<I", ds, rec + 10, len(payload))
            struct.pack_into(">I", ds, rec + 14, len(payload))
            rebuild_mode2_form1(ds)
            fh.seek(sec * RAW)
            fh.write(ds)

        # 3) 검증: 새 크기로 다시 읽어 비교 + 레코드 되읽기
        disc = Disc(str(out))
        try:
            back = disc.read(lba, len(payload))
            dsec = disc.sector(sec)
        finally:
            disc.f.close()
        ok = back == payload
        rsize = struct.unpack_from("<I", dsec, in_sec + 10)[0]
        rbe = struct.unpack_from(">I", dsec, in_sec + 14)[0]
        print(f"{iso}: lba={lba} {old_size} -> {len(payload)} B "
              f"({old_sectors}섹터 유지) 재추출일치={ok} "
              f"디렉터리크기(LE/BE)={rsize}/{rbe} "
              f"sha={hashlib.sha256(payload).hexdigest()[:16]}")
        if not ok or rsize != len(payload) or rbe != len(payload):
            raise SystemExit(f"{iso}: 검증 실패")

    print("out:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
