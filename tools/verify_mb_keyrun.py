#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB 의 **키 레코드 런 전부**가 원본과 자리까지 같은지 본다.

`fc 0f <키 u16>` 접두 레코드가 끊김 없이 이어진 구간이 원본에 **8개** 있다
(2개~454개). 이 런에는 뱅크 표 슬롯도 `{C:06}/{C:07}` 점프도 안 들어온다 —
게임은 런 안으로 점프한 뒤 **키를 앞으로 훑어** 원하는 줄을 찾는다. 그래서 런은
슬롯도 점프도 아닌 **세 번째로 자리에 의존하는 것**이다.

런 안 레코드를 하나라도 옮기면 그 지점에서 훑기가 끊긴다. 뒤쪽 레코드는 못 닿고,
운이 나쁘면 텍스트 VM 이 쓰레기를 파싱해 **게임이 멈춘다**
(2026-09-06 실측: 점보트3 합체 후 피격, 런 0x0CCA4 가 9개 -> 3개로 깨져 있었다).

**초판은 가장 긴 런 하나만 봤다가 이 사고를 놓쳤다.** 이제 8개를 전부 본다.
런마다 (레코드 수, 키 순서, 각 레코드 시작 오프셋)이 원본과 같아야 통과한다.
기대값을 검사 대상에서 만들지 않으려고 **원본 blob 을 따로 풀어** 대조한다.
"""
from __future__ import annotations
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

MIN_RUN = 2


def keyruns(d: bytes) -> dict[int, list[tuple[int, int]]]:
    """시작 오프셋 -> [(레코드 오프셋, 키)] . 길이 MIN_RUN 이상만."""
    out: dict[int, list[tuple[int, int]]] = {}
    seen: set[int] = set()
    for m in re.finditer(b"\xfc\x0f", d):
        s = m.start()
        if s in seen:
            continue
        p, rec = s, []
        while p < len(d) - 4 and d[p] == 0xFC and d[p + 1] == 0x0F:
            e = d.find(b"\xff", p)
            if e < 0:
                break
            rec.append((p, struct.unpack_from("<H", d, p + 2)[0]))
            p = e + 1
        seen.update(x for x, _ in rec)
        if len(rec) >= MIN_RUN:
            out[s] = rec
    return out


# 시작 자리가 **옮겨져도 되는** 레코드 (translation/mbankb_relocate_ko.py 의
# KEYRUN_SHIFT). 레코드 수와 키 순서는 그대로 강제한다.
# 2026-09-12 실기 확인: 훑기가 0xFF 종단을 세는 **순차 탐색**이라 자리가 밀려도
# 따라온다 (콤바트라V 도스프레셔 0x0C908 +1 이동분이 정상 출력).
# **단, 경계를 옮기면 `{C:01}{A}` 자기상대 참조를 반드시 다시 가리켜야 한다**
# — 안 그러면 옛 자리에서 읽어 대사가 중간부터 찍힌다(tools/mbankb_href.py).
SHIFT_OK: set = set()
try:
    import runpy as _rp
    SHIFT_OK = set(_rp.run_path(
        str(ROOT / "translation" / "mbankb_relocate_ko.py")).get("KEYRUN_SHIFT", ()))
except Exception:
    pass


def check(orig: bytes, built: bytes):
    a, b = keyruns(orig), keyruns(built)
    bad, moved = [], []
    for start in sorted(a):
        ra = a[start]
        rb = b.get(start)
        if rb is None:
            bad.append(f"런 0x{start:05X} ({len(ra)}개) 가 통째로 사라졌다")
            continue
        if len(ra) != len(rb):
            bad.append(f"런 0x{start:05X}: 레코드 {len(ra)} -> {len(rb)}")
            continue
        # **끝까지 본다.** 예전에는 첫 불일치에서 break 해서, 자리가 한 번 밀리면
        # 그 뒤 레코드의 키를 아예 검사하지 않았다(2026-09-12 발견). 키 순서는 이
        # 게이트가 지켜야 할 핵심이므로 이동과 무관하게 전수 비교한다.
        for i, (x, y) in enumerate(zip(ra, rb)):
            if x[1] != y[1]:
                bad.append(f"런 0x{start:05X} #{i} @0x{x[0]:05X} 키 0x{x[1]:04X} -> 0x{y[1]:04X}")
                break
            if x[0] != y[0]:
                if x[0] in SHIFT_OK:
                    moved.append(f"#{i} 0x{x[0]:05X}->0x{y[0]:05X}")
                else:
                    bad.append(f"런 0x{start:05X} #{i} 시작 0x{x[0]:05X} -> 0x{y[0]:05X}")
                    break
    return len(a), sum(len(v) for v in a.values()), bad, moved


def main(argv):
    import lzb
    orig, _ = lzb.decompress((ROOT / "extract" / "BTT" / "M_BANKB.LZB").read_bytes())
    tgt = Path(argv[1]) if len(argv) > 1 else ROOT / "build" / "M_BANKB_ko.dec"
    nrun, nrec, bad, moved = check(bytes(orig), tgt.read_bytes())
    if bad:
        print(f"FAIL 키 런 {nrun}개({nrec:,}레코드)가 원본과 다르다 — {tgt.name}")
        for m in bad[:10]:
            print("   ", m)
        return 1
    if moved:
        head = ", ".join(moved[:6])
        more = f" 외 {len(moved)-6}건" if len(moved) > 6 else ""
        print(f"  선언된 자리 이동 {len(moved)}건 허용: {head}{more}")
    print(f"키 런 {nrun}개 / 레코드 {nrec:,}개: 키 순서 원본과 일치 — {tgt.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
