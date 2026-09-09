#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""파일을 트랙 1 꼬리 여유 섹터로 재배치한다 (ISO 디렉터리 레코드 LBA+크기 갱신).

크기 보존 교체는 `patch_image.py`, 같은 섹터 수 안의 확대는 `patch_image_resize.py`가 한다.
이 도구는 **섹터 수가 늘어 제자리에 못 두는 파일**을 꼬리 여유로 옮긴다.

이 디스크의 여유
  * 트랙 1은 166,731섹터, 마지막 파일이 LBA 166,581에서 끝난다.
  * LBA 166,581–166,730의 150섹터(307,200 B)는 mode 2 / submode 0 / 사용자 데이터 전부 0이다.

쓰는 섹터는 게임의 다른 데이터 섹터와 같은 규약으로 만든다.
  * sync 00 FF*10 00, header = MSF(BCD)+mode 2
  * subheader = `00 00 08 00` (데이터), 파일 마지막 섹터는 `00 00 89 00` (EOF)
  * EDC/ECC 재계산

정책
  * 옮기기 전에 원래 LBA의 내용이 원본 추출본과 같은지 확인한다(Expected Write).
  * 목적지가 기존 파일이나 트랙 끝과 겹치면 실패한다.
  * 옮긴 뒤 패치 이미지의 ISO를 다시 파싱해 새 LBA/크기로 읽히는지 검증한다.
  * 원래 섹터는 건드리지 않고 남긴다(재실행 시 Expected Write가 계속 유효).
"""
from __future__ import annotations

import argparse
import hashlib
import math
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "reference" / "srwcb-korean-patch" / "tools"))

from isotool import Disc, RAW, HDR, USER               # noqa: E402
from patch_raw_track_exes import rebuild_mode2_form1   # noqa: E402
from patch_image_resize import load_listing, find_dir_record   # noqa: E402


def bcd(v: int) -> int:
    return ((v // 10) << 4) | (v % 10)


def sector_header(lba: int) -> bytes:
    absolute = lba + 150
    minute, rest = divmod(absolute, 75 * 60)
    second, frame = divmod(rest, 75)
    return bytes((bcd(minute), bcd(second), bcd(frame), 2))


def make_sector(lba: int, payload: bytes, final: bool) -> bytes:
    sec = bytearray(RAW)
    sec[0:12] = b"\x00" + b"\xFF" * 10 + b"\x00"
    sec[12:16] = sector_header(lba)
    sub = 0x89 if final else 0x08
    sec[16:20] = bytes((0, 0, sub, 0))
    sec[20:24] = sec[16:20]
    sec[HDR:HDR + len(payload)] = payload
    rebuild_mode2_form1(sec)
    return bytes(sec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--listing", default=str(ROOT / "records" / "iso-listing.txt"))
    ap.add_argument("--extract", default=str(ROOT / "extract"))
    ap.add_argument("--relocate", action="append", default=[], metavar="ISO=FILE")
    ap.add_argument("--place", action="append", default=[], metavar="ISO=FILE@LBA",
                    help="지정한 LBA 에 쓴다. 덮는 모든 섹터는 그 파일의 원래 자리이거나 "
                         "같은 실행의 --relocate 로 비워진 자리여야 한다.")
    ap.add_argument("--grow", action="append", default=[], metavar="ISO=FILE",
                    help="원래 LBA에 그대로 두되 섹터 수를 늘린다. 늘어난 섹터는 "
                         "같은 실행의 --relocate 로 비워진 자리여야 한다.")
    ap.add_argument("--assume-free", action="append", default=[], metavar="LBA-LBA",
                    help="ISO 디렉터리상 **미할당**임을 확인한 구간을 빈자리로 인정한다. "
                         "파일을 꼬리로 옮기고 남은 잔재 자리처럼, 같은 실행의 "
                         "--relocate 로 비우지 않았지만 이미 비어 있는 곳에 쓴다. "
                         "리스팅의 어떤 파일과도 겹치면 실패한다.")
    ap.add_argument("--free-start", type=int, default=166581)
    ap.add_argument("--free-end", type=int, default=166730)   # inclusive
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    src, out = Path(args.source), Path(args.out)
    files, dirs = load_listing(Path(args.listing))
    extract_root = Path(args.extract)

    # 여유 구간이 기존 파일과 겹치지 않는지
    for name, (lba, size) in files.items():
        end = lba + max(1, math.ceil(size / USER))
        if lba <= args.free_end and end > args.free_start:
            raise SystemExit(f"여유 구간이 {name}(LBA {lba}..{end-1})와 겹친다")

    if args.fresh or not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        print(f"복사: {src.name} -> {out}")

    cursor = args.free_start
    manifest = []
    for spec in args.relocate:
        iso, _, newfile = spec.partition("=")
        if iso not in files:
            raise SystemExit(f"listing에 없음: {iso}")
        old_lba, old_size = files[iso]
        original = (extract_root / iso).read_bytes()
        if len(original) != old_size:
            raise SystemExit(f"{iso}: 추출본 크기 불일치")
        payload = Path(newfile).read_bytes()
        count = max(1, math.ceil(len(payload) / USER))
        if cursor + count - 1 > args.free_end:
            raise SystemExit(f"{iso}: 여유 구간 초과 (필요 {count}섹터, 남은 "
                             f"{args.free_end - cursor + 1}섹터)")

        with out.open("r+b") as fh:
            # Expected Write: 원래 자리가 아직 원본인가
            for i in range(max(1, math.ceil(old_size / USER))):
                fh.seek((old_lba + i) * RAW)
                sec = fh.read(RAW)
                here = original[i * USER:(i + 1) * USER]
                if sec[HDR:HDR + len(here)] != here:
                    raise SystemExit(f"{iso}: Expected Write 실패 — 섹터 {old_lba+i}")
            # 새 자리에 기록
            for i in range(count):
                chunk = payload[i * USER:(i + 1) * USER]
                fh.seek((cursor + i) * RAW)
                fh.write(make_sector(cursor + i, chunk, i == count - 1))
            # 디렉터리 레코드 갱신
            parent = "/".join(iso.split("/")[:-1])
            leaf = iso.split("/")[-1] + ";1"
            d_lba, d_size = dirs[parent] if parent else (22, 2048)
            sec_no, in_sec, _ = find_dir_record(out, d_lba, d_size, leaf)
            fh.seek(sec_no * RAW)
            ds = bytearray(fh.read(RAW))
            rec = HDR + in_sec
            if (struct.unpack_from("<I", ds, rec + 2)[0] != old_lba
                    or struct.unpack_from("<I", ds, rec + 10)[0] != old_size):
                raise SystemExit(f"{iso}: 디렉터리 레코드가 예상과 다르다")
            struct.pack_into("<I", ds, rec + 2, cursor)
            struct.pack_into(">I", ds, rec + 6, cursor)
            struct.pack_into("<I", ds, rec + 10, len(payload))
            struct.pack_into(">I", ds, rec + 14, len(payload))
            rebuild_mode2_form1(ds)
            fh.seek(sec_no * RAW)
            fh.write(ds)

        manifest.append(dict(iso=iso, old_lba=old_lba, new_lba=cursor,
                             old_size=old_size, new_size=len(payload),
                             sectors=count,
                             sha256=hashlib.sha256(payload).hexdigest()))
        print(f"{iso}: LBA {old_lba} -> {cursor}, {old_size} -> {len(payload)} B "
              f"({count}섹터)")
        cursor += count

    # 제자리 확대 — 앞선 재배치로 비워진 섹터로만 넘어갈 수 있다.
    # (게임은 실행 파일의 경로 표 0x800E0410 -> ISO 디렉터리로 파일을 찾으므로
    #  LBA 를 유지하는 것 자체는 요구사항이 아니지만, 유지하면 건드리는 범위가 줄어든다.)
    freed = set()
    for m in manifest:
        n = max(1, math.ceil(m["old_size"] / USER))
        freed.update(range(m["old_lba"], m["old_lba"] + n))

    # --assume-free: 디렉터리가 할당의 정본이다. 어떤 파일과도 안 겹치면 빈자리로 본다.
    for spec in args.assume_free:
        a_s, _, b_s = spec.partition("-")
        a, b = int(a_s, 0), int(b_s, 0)
        for name, (lba, size) in files.items():
            end = lba + max(1, math.ceil(size / USER))
            if lba <= b and end > a:
                raise SystemExit(f"--assume-free {a}-{b} 가 {name}(LBA {lba}..{end-1})와 겹친다")
        freed.update(range(a, b + 1))
        print(f"미할당으로 인정: LBA {a}..{b} ({b - a + 1}섹터)")

    for spec in args.grow:
        iso, _, newfile = spec.partition("=")
        if iso not in files:
            raise SystemExit(f"listing에 없음: {iso}")
        old_lba, old_size = files[iso]
        original = (extract_root / iso).read_bytes()
        if len(original) != old_size:
            raise SystemExit(f"{iso}: 추출본 크기 불일치")
        payload = Path(newfile).read_bytes()
        own = max(1, math.ceil(old_size / USER))
        count = max(1, math.ceil(len(payload) / USER))
        for i in range(own, count):
            if old_lba + i not in freed:
                raise SystemExit(f"{iso}: 확장 섹터 {old_lba + i}가 비어 있지 않다 "
                                 f"(먼저 --relocate 로 비울 것)")
        with out.open("r+b") as fh:
            for i in range(own):
                fh.seek((old_lba + i) * RAW)
                sec = fh.read(RAW)
                here = original[i * USER:(i + 1) * USER]
                if sec[HDR:HDR + len(here)] != here:
                    raise SystemExit(f"{iso}: Expected Write 실패 — 섹터 {old_lba + i}")
            for i in range(count):
                chunk = payload[i * USER:(i + 1) * USER]
                fh.seek((old_lba + i) * RAW)
                fh.write(make_sector(old_lba + i, chunk, i == count - 1))
            parent = "/".join(iso.split("/")[:-1])
            leaf = iso.split("/")[-1] + ";1"
            d_lba, d_size = dirs[parent] if parent else (22, 2048)
            sec_no, in_sec, _ = find_dir_record(out, d_lba, d_size, leaf)
            fh.seek(sec_no * RAW)
            ds = bytearray(fh.read(RAW))
            rec = HDR + in_sec
            if (struct.unpack_from("<I", ds, rec + 2)[0] != old_lba
                    or struct.unpack_from("<I", ds, rec + 10)[0] != old_size):
                raise SystemExit(f"{iso}: 디렉터리 레코드가 예상과 다르다")
            struct.pack_into("<I", ds, rec + 10, len(payload))
            struct.pack_into(">I", ds, rec + 14, len(payload))
            rebuild_mode2_form1(ds)
            fh.seek(sec_no * RAW)
            fh.write(ds)
        manifest.append(dict(iso=iso, old_lba=old_lba, new_lba=old_lba,
                             old_size=old_size, new_size=len(payload),
                             sectors=count,
                             sha256=hashlib.sha256(payload).hexdigest()))
        print(f"{iso}: LBA {old_lba} 유지, {old_size} -> {len(payload)} B "
              f"({own} -> {count}섹터)")

    # 지정 LBA 배치 — 앞쪽 파일을 비워 시작점을 당길 때 쓴다.
    for spec in args.place:
        left, _, lba_s = spec.partition("@")
        iso, _, newfile = left.partition("=")
        new_lba = int(lba_s, 0)
        if iso not in files:
            raise SystemExit(f"listing에 없음: {iso}")
        old_lba, old_size = files[iso]
        original = (extract_root / iso).read_bytes()
        if len(original) != old_size:
            raise SystemExit(f"{iso}: 추출본 크기 불일치")
        payload = Path(newfile).read_bytes()
        own = max(1, math.ceil(old_size / USER))
        count = max(1, math.ceil(len(payload) / USER))
        mine = set(range(old_lba, old_lba + own))
        for i in range(count):
            t = new_lba + i
            if t not in mine and t not in freed:
                raise SystemExit(f"{iso}: 섹터 {t}가 비어 있지 않다 "
                                 f"(먼저 --relocate 로 비울 것)")
        with out.open("r+b") as fh:
            for i in range(own):        # Expected Write: 원래 자리가 아직 원본인가
                fh.seek((old_lba + i) * RAW)
                here = original[i * USER:(i + 1) * USER]
                if fh.read(RAW)[HDR:HDR + len(here)] != here:
                    raise SystemExit(f"{iso}: Expected Write 실패 — 섹터 {old_lba+i}")
            for i in range(count):
                fh.seek((new_lba + i) * RAW)
                fh.write(make_sector(new_lba + i, payload[i * USER:(i + 1) * USER],
                                     i == count - 1))
            parent = "/".join(iso.split("/")[:-1])
            leaf = iso.split("/")[-1] + ";1"
            d_lba, d_size = dirs[parent] if parent else (22, 2048)
            sec_no, in_sec, _ = find_dir_record(out, d_lba, d_size, leaf)
            fh.seek(sec_no * RAW)
            ds = bytearray(fh.read(RAW))
            rec = HDR + in_sec
            if (struct.unpack_from("<I", ds, rec + 2)[0] != old_lba
                    or struct.unpack_from("<I", ds, rec + 10)[0] != old_size):
                raise SystemExit(f"{iso}: 디렉터리 레코드가 예상과 다르다")
            struct.pack_into("<I", ds, rec + 2, new_lba)
            struct.pack_into(">I", ds, rec + 6, new_lba)
            struct.pack_into("<I", ds, rec + 10, len(payload))
            struct.pack_into(">I", ds, rec + 14, len(payload))
            rebuild_mode2_form1(ds)
            fh.seek(sec_no * RAW)
            fh.write(ds)
        manifest.append(dict(iso=iso, old_lba=old_lba, new_lba=new_lba,
                             old_size=old_size, new_size=len(payload), sectors=count,
                             sha256=hashlib.sha256(payload).hexdigest()))
        print(f"{iso}: LBA {old_lba} -> {new_lba}, {old_size} -> {len(payload)} B ({count}섹터)")

    # 검증: 패치 이미지의 ISO를 다시 걸어 새 좌표로 읽히는지
    sys.path.insert(0, str(ROOT / "tools"))
    import isotool
    disc = Disc(str(out))
    try:
        pvd = disc.sector(16)
        rlba = struct.unpack_from("<I", pvd[156:190], 2)[0]
        rsize = struct.unpack_from("<I", pvd[156:190], 10)[0]
        entries = []
        isotool.walk(disc, rlba, rsize, "", entries)
        table = {f.lstrip("/").split(";")[0]: (l, s)
                 for f, l, s, k in entries if k == "FILE"}
        for m in manifest:
            lba, size = table[m["iso"]]
            data = disc.read(lba, size)
            ok = (lba == m["new_lba"] and size == m["new_size"]
                  and hashlib.sha256(data).hexdigest() == m["sha256"])
            print(f"  검증 {m['iso']}: ISO가 LBA {lba} 크기 {size}로 보고, 내용일치={ok}")
            if not ok:
                raise SystemExit(f"{m['iso']}: 재배치 검증 실패")
    finally:
        disc.f.close()
    print("out:", out, f"(여유 잔여 {args.free_end - cursor + 1}섹터)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
