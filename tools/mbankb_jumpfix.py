#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전투 화자 이름을 늘리고 **상대 점프의 s16 을 보정한다.**

BATTLE 오버레이의 텍스트 VM 구조 (실기 브레이크포인트 + 역어셈블로 확정):

    0x80159B60  addu a0,s1,zero      ; a0 = 스크립트 포인터
    0x80159B64  jal  0x8015A808      ; 한 바이트 읽기
    0x80159B70  addiu v1,s2,-236     ; b - 0xEC
    0x80159B74  sltiu v0,v1,20       ; 0xEC..0xFF 면 토큰 -> 점프 테이블

`FC`(={C:xx}) 의 보조 테이블 0x80163F90 에서 **인덱스 6·7 이 상대 점프**다:

    0x8015A024  lbu v1,1(a0) / lbu v0,0(a0) / v1<<8|v0 / 부호확장 / addu v0,a0,v0

즉 `{C:07} <s16>` 은 `대상 = (s16 두 바이트의 주소) + s16` 인 **상대 점프**다.
이름표처럼 보이던 것은 사실 **[이름 글자][공통 대사로 점프]** 가 번갈아 놓인 구조였다.

    +48 '一矢'          <- 호출자가 여기로 진입해 이름을 찍고
    +52 {C:07} -> 0x0C760   이어지는 점프로 공통 대사에 합류한다

그래서 이름을 늘리면 **뒤 점프가 밀려** 엉뚱한 데 착지한다. 지금까지 네 번 깨진 이유가
전부 이것이다(M_BANKS 발진 멈춤과 같은 함정 → [[script-relative-jumps]]).

**고치는 법**: 이름을 늘린 만큼 그 뒤 점프의 s16 을 빼 준다. 레코드 길이는 꼬리 대사를
줄여 그대로 맞춘다. 바깥에서 이 레코드로 들어오는 점프는 0개임을 블롭 전수 조사로 확인했다.

검증은 **점프 대상 주소를 원본과 대조**한다 — 오프셋 계산을 다시 쓰지 않고 결과를 비교한다.
"""
from __future__ import annotations
import struct

JUMP_SUB = (0x06, 0x07)


def targets(buf, base):
    """buf 안 모든 {C:06}/{C:07} 의 **대상 절대 주소**를 순서대로."""
    out, p = [], 0
    while p < len(buf) - 3:
        if buf[p] == 0xFC and buf[p + 1] in JUMP_SUB:
            out.append(base + (p + 2) + struct.unpack_from("<h", buf, p + 2)[0])
            p += 4
        else:
            p += 1
    return out


def grow_names(old, names, tail, encode, enc, slots=None, rec_off=0, data=None):
    """old(레코드 바이트)에서 names=[(오프셋, 원문바이트수, 새이름)] 를 늘리고,
    **그 뒤에 오는 점프의 s16 을 그 시점까지 늘어난 만큼** 빼 준다.
    tail 로 꼬리를 갈아 레코드 길이를 원래대로 맞춘다.

    바이트를 순서대로 훑어야 한다. 이름들을 먼저 다 치환하고 나머지를 한꺼번에
    처리하면, **두 이름 사이에 낀 점프**가 보정을 못 받는다(2026-09-05 실수).
    """
    subs = {off: (oldlen, ko) for off, oldlen, ko in names}
    new, grown, p = bytearray(), 0, 0
    while p < len(old):
        if p in subs:
            oldlen, ko = subs[p]
            nb = encode(ko, enc)[:-1]
            new += nb
            grown += len(nb) - oldlen
            p += oldlen
            continue
        if old[p] == 0xFC and p + 3 < len(old) and old[p + 1] in JUMP_SUB:
            s16 = struct.unpack_from("<h", old, p + 2)[0]
            new += old[p:p + 2] + struct.pack("<h", s16 - grown)
            p += 4
            continue
        new += old[p:p + 1]
        p += 1
    # 이름 진입점은 **뱅크 표 슬롯**이다 (블롭 안 오프셋을 u16 으로 가리킨다).
    # 이름을 늘리면 그 뒤 진입점이 밀리므로 슬롯도 같이 옮겨야 한다.
    # 안 옮기면 진입점이 앞 점프의 오프셋 바이트를 가리켜 그게 글자로 찍힌다
    # (실측: `とF카즈야「…」`).
    if slots is not None and data is not None:
        for tb, k, v in slots:
            rel = v - rec_off
            if 0 <= rel < len(old):
                shift = sum(len(encode(ko, enc)) - 1 - ol
                            for o2, ol, ko in names if o2 < rel)
                if shift:
                    struct.pack_into("<H", data, tb + 2 * k, v + shift)

    i = bytes(new).rfind(encode("「", enc)[:-1])
    if i < 0:
        raise ValueError("꼬리의 여는 따옴표를 못 찾았다")
    new = new[:i] + encode(tail, enc)
    return bytes(new), grown
