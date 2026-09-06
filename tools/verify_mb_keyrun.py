#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB **키 레코드 런**이 원본과 자리까지 같은지 본다.

`0x0AC01` 부터 454개 레코드가 `fc 0f <키 u16>` 접두로 끊김 없이 이어진다.
이 런에는 **뱅크 표 슬롯도, {C:06}/{C:07} 점프도 하나도 안 들어온다**(전수 확인).
게임은 런 안의 base 레코드로 점프한 뒤 **키를 앞으로 훑어** 원하는 줄을 찾고,
찾으면 `fc 0f` + 키 2바이트를 건너뛴 자리부터 그린다. 그래서 이 런은

    슬롯도 점프도 아닌 **세 번째로 자리에 의존하는 것**이다.

런 #0 은 레코드 `BB:0ABC1` 의 마지막 이름 뒤 `{C:07}` **바로 다음에 붙어 있고
종단(`ff`)을 공유한다**. 그래서 그 레코드에서 이름을 늘리고 꼬리를 줄여 길이를
맞추면, 줄어드는 "꼬리"가 사실은 런 #0(키 0x0F03) 본문이다. 런 #0 만 밀리고
나머지 453개는 제자리에 남아 키 훑기가 어긋난다 — 화면에는 `{C:0F}` 뒤 색인
2바이트가 글자로 찍힌다(`카즈야Fケ「우옷!!」`, v0.99e/f 실측).

원본과 (레코드 수, 키 순서, **각 레코드 시작 오프셋**) 셋이 모두 같아야 통과한다.
기대값을 검사 대상에서 만들지 않으려고 **원본 blob 을 따로 풀어** 대조한다.
"""
from __future__ import annotations
import re, struct, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def walk(d, start):
    out, p = [], start
    while p < len(d) - 4 and d[p] == 0xFC and d[p + 1] == 0x0F:
        e = d.find(b"\xff", p)
        if e < 0:
            break
        out.append((p, struct.unpack_from("<H", d, p + 2)[0]))
        p = e + 1
    return out


def keyrun(d):
    """가장 긴 `fc 0f` 런을 낸다. 블롭 곳곳에 단발 `fc 0f` 레코드가 있어
    첫 등장으로 잡으면 1개짜리 런을 보게 된다."""
    best, seen = [], set()
    for m in re.finditer(b"\xfc\x0f", d):
        s = m.start()
        if s in seen:
            continue
        r = walk(d, s)
        seen.update(o for o, _ in r)
        if len(r) > len(best):
            best = r
    return best


def check(orig: bytes, built: bytes):
    a, b = keyrun(orig), keyrun(built)
    bad = []
    if len(a) != len(b):
        bad.append(f"레코드 수 {len(a)} -> {len(b)}")
    for i, (x, y) in enumerate(zip(a, b)):
        if x[0] != y[0]:
            bad.append(f"#{i} 시작 0x{x[0]:05X} -> 0x{y[0]:05X} ({y[0] - x[0]:+d})")
        elif x[1] != y[1]:
            bad.append(f"#{i} @0x{x[0]:05X} 키 0x{x[1]:04X} -> 0x{y[1]:04X}")
        if len(bad) >= 8:
            break
    return len(a), bad


def main(argv):
    import lzb
    orig, _ = lzb.decompress((ROOT / "extract" / "BTT" / "M_BANKB.LZB").read_bytes())
    tgt = pathlib.Path(argv[1]) if len(argv) > 1 else ROOT / "build" / "M_BANKB_ko.dec"
    n, bad = check(bytes(orig), tgt.read_bytes())
    if bad:
        print(f"FAIL 키 런({n}개)이 원본과 다르다 — {tgt.name}")
        for m in bad:
            print("   ", m)
        return 1
    print(f"키 런 {n}개: 시작 오프셋·키 순서 원본과 일치 — {tgt.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
