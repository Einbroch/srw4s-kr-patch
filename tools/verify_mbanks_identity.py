#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 구조 모델 항등 검증.

파일을 (헤더 + 포인터표 + 정본 레코드)로 분해한 뒤 **그 표현만으로 다시 조립**해
원본과 바이트가 같은지 본다. 어긋나면 내 모델이 설명하지 못하는 바이트가 있다는 뜻이다.

D_NAMES에는 이 게이트가 없었다. 그래서 재배치가 레코드 인접성을 깨뜨린 것을
모든 정적 검증을 통과한 채 실기에서야 발견했다.
"""
from __future__ import annotations
import hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"


def main() -> int:
    d = SRC.read_bytes()
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    if L["source"]["sha256"] != hashlib.sha256(d).hexdigest():
        print("FAIL: 원장 source.sha256이 현재 추출과 다르다")
        return 1

    out = bytearray(len(d))
    covered = bytearray(len(d))

    first = struct.unpack_from("<I", d, 0)[0]
    out[0:first] = d[0:first]
    covered[0:first] = b"\x01" * first

    offsets = list(struct.unpack_from(f"<{first // 4}I", d, 0))
    for off in offsets:
        if not off or off + 0x200 > len(d):
            continue
        out[off:off + 0x200] = d[off:off + 0x200]
        covered[off:off + 0x200] = b"\x01" * 0x200

    for r in L["records"]:
        s, e = r["offset"], r["end"]
        raw = bytes.fromhex(r["raw_hex"])
        if len(raw) != e - s:
            print(f"FAIL: {r['id']} raw 길이 불일치")
            return 1
        out[s:e] = raw
        covered[s:e] = b"\x01" * (e - s)

    same = bytes(out[i] for i in range(len(d)) if covered[i]) == \
           bytes(d[i] for i in range(len(d)) if covered[i])
    ncov = sum(covered)
    gaps = len(d) - ncov
    # 빈 구간의 성격
    gapbytes = {}
    run = 0
    runs = []
    for i in range(len(d)):
        if not covered[i]:
            run += 1
            gapbytes[d[i]] = gapbytes.get(d[i], 0) + 1
        elif run:
            runs.append(run); run = 0
    if run:
        runs.append(run)

    print(f"파일 {len(d):,}B")
    print(f"  모델이 덮은 바이트 {ncov:,} ({ncov/len(d)*100:.1f}%)")
    print(f"  설명 못 한 바이트 {gaps:,} ({gaps/len(d)*100:.1f}%) / 구간 {len(runs)}개")
    if runs:
        runs.sort(reverse=True)
        print(f"  가장 긴 빈 구간 {runs[:8]}")
        top = sorted(gapbytes.items(), key=lambda x: -x[1])[:6]
        print(f"  빈 구간 바이트 분포: {[(hex(k), v) for k, v in top]}")
    print(f"\n덮은 영역 바이트 일치: {'PASS' if same else 'FAIL'}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
