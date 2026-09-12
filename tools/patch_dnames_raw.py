#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""빌드된 D_NAMES 의 **구간(span) 밖 바이트**를 문맥으로 찾아 고친다.

창 좌표 같은 값은 텍스트 구간이 아니라서 원장으로는 못 건드린다. 재삽입이 끝난 뒤
유일하게 일치하는 바이트 문맥을 찾아 그 자리만 바꾼다. 문맥이 0개거나 2개 이상이면
실패시킨다 — 엉뚱한 데를 고치는 것보다 멈추는 편이 낫다.

    patch_dnames_raw.py            # tools/dnames_raw_patch.json 을 적용

2026-09-12 — 규칙이 비었다. 하나뿐이던 `DN:0C4C` 네/아뇨 이동(`fc0202`->`fc0602`,
눈대중 32px)은 **`patch_dnames_script.py`** 의 절대 위치 변환(`fc0202`->`fd158c`,
형제 확인창과 같은 창 +1,+1 규칙)으로 대체됐다. 둘은 같은 바이트를 노려 **동시에
쓸 수 없다** — 스크립트 쪽이 먼저 돌면 여기 find 가 0군데가 되어 실패한다.

규칙: {"why": "...", "find": "hex", "replace": "hex"}  (find 와 replace 는 같은 길이)
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "build" / "D_NAMES_ko.BIN"
RULES = ROOT / "tools" / "dnames_raw_patch.json"


def main() -> int:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    d = bytearray(TARGET.read_bytes())
    for r in rules:
        a = bytes.fromhex(r["find"]); b = bytes.fromhex(r["replace"])
        if len(a) != len(b):
            print(f"FAIL: 길이가 다르다 — {r['why']}")
            return 1
        n = d.count(a)
        if n != 1:
            print(f"FAIL: 문맥이 {n}군데 (1군데여야 한다) — {r['why']}")
            print(f"      find={r['find']}")
            return 1
        i = d.find(a)
        d[i:i+len(b)] = b
        print(f"  +0x{i:05X} 고침: {r['why']}")
    TARGET.write_bytes(bytes(d))
    print(f"{len(rules)}건 적용 -> {TARGET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
