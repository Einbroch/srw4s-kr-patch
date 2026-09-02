#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 제자리 재삽입 — **파일 배치를 한 바이트도 바꾸지 않는다.**

왜 제자리인가
  재뱅킹(창 재구성)은 정적 검증을 전부 통과했는데도 실기에서 대사가 엉뚱하게 나오고 멈춘다
  (2026-08-24, 번역 0개인 항등 재뱅킹으로도 재현). 즉 런타임은 표를 거친 (뱅크,슬롯) 접근
  외에 **레코드 뒤에 무엇이 오는지에도 의존한다**(0x400 창을 이어 읽는 것으로 보인다).
  그래서 배치를 건드리지 않는 경로를 따로 둔다.

규칙
  * 역문의 인코딩 길이가 원본 레코드 길이 **이하**일 때만 넣는다.
  * 모자란 만큼 공백 글리프(0x00)로 채워 **길이를 정확히 맞춘다** — 종단 FF 위치가 그대로여야
    뒤따르는 스트림이 어긋나지 않는다.
  * 다른 포인터가 그 레코드 **안쪽**을 가리키면(접미사 공유) 건너뛴다. 덮으면 그 포인터가
    읽는 내용이 바뀐다.
"""
from __future__ import annotations
import hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode      # noqa: E402

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
OUT = ROOT / "build" / "M_BANKS_inplace.BIN"


def main() -> int:
    d = bytearray(SRC.read_bytes())
    orig = bytes(d)
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()
    first = struct.unpack_from("<I", d, 0)[0]
    offs = list(struct.unpack_from(f"<{first // 4}I", d, 0))

    # 모든 포인터 대상 (접미사 공유 판정용)
    targets: set[int] = set()
    for off in offs:
        if not off or off + 0x200 > len(d):
            continue
        base = off & 0xFFFF0000
        for rel in struct.unpack_from("<256H", d, off):
            targets.add(base + rel)

    fit = skip_len = skip_alias = 0
    for r in L["records"]:
        if not r["ko"]:
            continue
        p = r["offset"]
        raw = bytes.fromhex(r["raw_hex"])
        try:
            new = encode(r["ko"], enc)
        except KeyError:
            continue
        if len(new) > len(raw):
            skip_len += 1
            continue
        # 레코드 안쪽을 가리키는 다른 포인터가 있으면 건너뛴다
        if any(p < t < p + len(raw) for t in targets):
            skip_alias += 1
            continue
        pad = len(raw) - len(new)
        body = new[:-1] + bytes(pad) + new[-1:]     # 종단 앞에 공백 글리프로 채운다
        assert len(body) == len(raw)
        d[p:p + len(raw)] = body
        fit += 1

    OUT.write_bytes(bytes(d))
    changed = sum(1 for a, b in zip(orig, d) if a != b)
    print(f"제자리 삽입 {fit}개 / 길이 초과로 제외 {skip_len} / 접미사 공유로 제외 {skip_alias}")
    print(f"크기 {len(d):,}B (원본과 동일) / 바뀐 바이트 {changed:,}")
    print(f"-> {OUT.name}  sha {hashlib.sha256(bytes(d)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
