#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lossless token codec for the target's custom text bytecode."""
from __future__ import annotations

from dataclasses import dataclass

from analyze_structures import CONTROL_ARGUMENT_BYTES

def _fb_argc(buf: bytes, cursor: int) -> int:
    """FB 인수 개수는 **형식 바이트(두 번째 인수)** 에 달렸다.

    0x80/0x12 등은 이름 삽입이라 2바이트지만, 0x0C·0x08 은 4바이트다.
    2로 읽으면 뒤 2바이트가 글자로 새어 나와 `{B:490C}ご{8:9B}ラリア` 처럼 보인다
    (실제로는 `ガラリア`). 실측: 형식 0C/08 레코드 28개에서 화자 이름이 SSOT 와
    맞는 것이 2바이트로는 0개, 4바이트로는 12개(나머지는 화자가 없는 승리 조건).
    """
    return 4 if cursor + 2 < len(buf) and buf[cursor + 2] in (0x0C, 0x08) else 2


# M_BANKS 는 FC 를 1인수로 읽고, FB 는 형식에 따라 2/4인수다 (analyze_structures 의 주석 참조)
MB_ARITY = dict(CONTROL_ARGUMENT_BYTES) | {0xFC: 1, 0xFB: _fb_argc}


@dataclass(frozen=True)
class Token:
    kind: str
    raw: bytes
    glyph_id: int | None = None
    opcode: int | None = None
    operands: bytes = b""


def glyph_bytes(glyph_id: int) -> bytes:
    if 0 <= glyph_id < 0xF0:
        return bytes((glyph_id,))
    if 0x100 <= glyph_id <= 0x6FF:
        return bytes((0xEF + (glyph_id >> 8), glyph_id & 0xFF))
    raise ValueError(f"glyph ID 0x{glyph_id:X} is not representable")


def parse_record(raw_including_ff: bytes, arity: dict | None = None) -> list[Token]:
    tokens: list[Token] = []
    cursor = 0
    while cursor < len(raw_including_ff):
        lead = raw_including_ff[cursor]
        if lead == 0xFF:
            if cursor != len(raw_including_ff) - 1:
                raise ValueError("bytes follow structural FF")
            tokens.append(Token("terminator", b"\xFF", opcode=0xFF))
            return tokens
        if lead < 0xF0:
            raw = raw_including_ff[cursor : cursor + 1]
            tokens.append(Token("glyph", raw, glyph_id=lead))
            cursor += 1
            continue
        if lead < 0xF6:
            if cursor + 1 >= len(raw_including_ff):
                raise ValueError("truncated extended glyph")
            raw = raw_including_ff[cursor : cursor + 2]
            glyph_id = ((((lead + 1) << 8) & 0x0F00) | raw[1])
            tokens.append(Token("glyph", raw, glyph_id=glyph_id))
            cursor += 2
            continue
        argc = (arity or CONTROL_ARGUMENT_BYTES)[lead]
        if callable(argc):
            argc = argc(raw_including_ff, cursor)
        end = cursor + 1 + argc
        if end > len(raw_including_ff):
            raise ValueError(f"truncated control 0x{lead:02X}")
        raw = raw_including_ff[cursor:end]
        tokens.append(Token("control", raw, opcode=lead, operands=raw[1:]))
        cursor = end
    raise ValueError("record has no structural FF")


def encode_tokens(tokens: list[Token]) -> bytes:
    output = bytearray()
    for token in tokens:
        if token.kind == "glyph":
            if token.glyph_id is None:
                raise ValueError("glyph token lacks glyph ID")
            encoded = glyph_bytes(token.glyph_id)
            if encoded != token.raw:
                raise ValueError("glyph token raw bytes disagree with glyph ID")
            output.extend(encoded)
        elif token.kind == "control":
            if token.opcode not in CONTROL_ARGUMENT_BYTES:
                raise ValueError("unknown control opcode")
            expected = bytes((token.opcode,)) + token.operands
            if expected != token.raw or len(token.operands) != CONTROL_ARGUMENT_BYTES[token.opcode]:
                raise ValueError("control token raw/arity mismatch")
            output.extend(expected)
        elif token.kind == "terminator":
            if token.raw != b"\xFF":
                raise ValueError("invalid terminator token")
            output.append(0xFF)
        else:
            raise ValueError(f"unknown token kind {token.kind!r}")
    return bytes(output)
