#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""창 그리기 스크립트의 **상대 커서 이동**을 절대 위치로 바꾼다.

출격 확인창(`DN:0C4C`)만 글자 위치를 `FC`(상대 이동)로 잡는다. 상대 이동은
**바로 앞 문자열의 폭**을 기준으로 삼기 때문에, 한글로 바꾸면 글자가 선택 칸
밖으로 밀려난다. 원문 폭에 맞춰도 소용이 없다 — 기준점 자체가 다르다.

같은 모양의 다른 확인창은 전부 절대 위치를 쓰고, 규칙이 일정하다.

    DN:29FB  창 FD 0E 8E -> 글자 FD 0F 8F   (+1,+1)
    DN:1B7C  창 FD 0E 8E -> 글자 FD 0F 8F   (+1,+1)
    DN:0C4C  창 FD 14 8B -> 글자 **FC 02 02**   <- 이것만 상대

그래서 `DN:0C4C` 의 두 상대 이동을 같은 규칙의 절대 위치로 바꾼다.
`FC` 와 `FD` 는 둘 다 인수 2개라 레코드 길이가 변하지 않는다.

    메시지   FC F3 F9  ->  FD 04 8A   (메시지 창 FD 03 89 + 1,1)
    네/아뇨  FC 02 02  ->  FD 15 8C   (선택 창  FD 14 8B + 1,1)

`reinsert_build.py` 가 만든 `build/D_NAMES_ko.BIN` 에 덧대는 단계다.
쓰기 전에 앞뒤 바이트를 확인하고, 후보가 정확히 하나일 때만 고친다.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "build" / "D_NAMES_ko.BIN"

# (설명, 앞 문맥, 원래 3바이트, 새 3바이트)
# 이 창은 형제 확인창(DN:29FB / DN:1B7C)과 구조가 한 글자까지 같은데 **위치 지정만**
# 상대(FC)다. 상대 이동은 바로 앞 문자열 폭을 기준으로 삼아 어디에 찍힐지 예측이 안 되고,
# 실제로 네/아뇨가 선택 칸을 벗어난다.
#
#   DN:29FB  선택창 FD 0E 8E -> 글자 FD 0F 8F   (+1,+1)   <- 정상
#   DN:0C4C  선택창 FD 14 8B -> 글자 FC 02 02             <- 이것만 상대
#
# 그래서 형제와 같은 규칙(창 +1,+1)의 절대 위치로 바꾼다. FC 와 FD 는 둘 다 3바이트라
# 레코드 길이가 변하지 않는다.
#
# 2026-09-03 — FD 를 피해야 한다고 적어 두었던 건 전함 발진 멈춤 때문이었는데,
#   그 원인은 M_BANKS 뱅크 30 의 스크립트 상대 점프였다 (FD 를 되돌려도 계속 멈췄고,
#   뱅크 30 배치를 보존하니 멈춤이 사라졌다). 형제 창이 같은 자리에서 FD 를 쓰고
#   멀쩡히 도는 것도 근거다.
#
# 메시지 글자(FC F3 F9)는 화면에 제대로 나오므로 건드리지 않는다.
PATCHES = [
    ("DN:0C4C 네/아뇨 -> 절대 위치", b"", bytes([0xFC, 0x02, 0x02]), bytes([0xFD, 0x15, 0x8C])),
]


def main() -> int:
    d = bytearray(TARGET.read_bytes())
    ok = True
    for note, ctx, old, new in PATCHES:
        pat = ctx + old
        hits = []
        i = -1
        while True:
            i = d.find(pat, i + 1)
            if i < 0:
                break
            hits.append(i)
        if len(hits) != 1:
            print(f"FAIL: {note} — 후보가 {len(hits)}개 (1개여야 한다) {[hex(h) for h in hits[:6]]}")
            ok = False
            continue
        at = hits[0] + len(ctx)
        d[at:at + 3] = new
        print(f"  {note}  0x{at:05X}  {old.hex(' ')} -> {new.hex(' ')}")
    if not ok:
        return 1
    TARGET.write_bytes(bytes(d))
    print(f"-> {TARGET.name}  {len(d):,}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
