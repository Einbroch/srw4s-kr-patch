#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 문자열 풀 패커 (토큰 정합 검증).

접미사 공유의 함정: 바이트열이 파일 안 어딘가에 나타난다고 해서 거기서 읽을 수 있는 게 아니다.
토큰이 가변 길이라 **토큰 경계가 아닌 위치에서 시작하면 파싱이 어긋난다**. 그래서 후보 위치를
'이미 배치된 어떤 레코드의 토큰 시작점'으로만 제한한다. 각 레코드는 자기 종단 FF를 포함하므로
경계에서 시작해 바이트가 일치하면 읽기 결과도 정확히 같다.

버퍼는 **파일 전체를 만드는 하나의 bytearray**를 공유한다. 섹션마다 버퍼를 나누면 인덱스의
절대 오프셋과 어긋나 섹션 간 공유가 죽는다.
"""
from __future__ import annotations
from collections import defaultdict

from text_codec import parse_record

PREFIX = 4


def token_offsets(rec: bytes) -> list[int]:
    out, pos = [], 0
    for t in parse_record(rec):
        out.append(pos)
        pos += len(t.raw)
    return out


class Pool:
    """out(파일 버퍼)에 직접 덧붙이며 절대 오프셋으로 색인한다."""

    def __init__(self, out: bytearray) -> None:
        self.out = out
        self.index: dict[bytes, list[int]] = defaultdict(list)
        self.exact: dict[bytes, int] = {}
        self.reused = 0
        self.shared_bytes = 0

    def _register(self, at: int, rec: bytes) -> None:
        # 색인 키는 **레코드 자신의 접미사**에서 뽑는다. 버퍼에서 읽으면 레코드 끝을 넘어
        # 뒤 레코드 바이트가 섞이고, 조회 키(rec[:PREFIX])와 길이가 어긋나
        # PREFIX 보다 짧은 레코드는 영영 공유되지 않는다.
        for t in token_offsets(rec):
            self.index[rec[t:t + PREFIX]].append(at + t)
        self.exact.setdefault(rec, at)

    def register_only(self, at: int, rec: bytes) -> None:
        """이미 버퍼에 들어 있는 바이트를 공유 후보로만 등록한다(추가하지 않는다).
        토큰 파싱이 어긋나는 조각은 등록하지 않는다 — 경계가 아닌 위치를 후보로 주면
        거기서 읽은 결과가 달라진다."""
        try:
            offs = token_offsets(rec)
        except Exception:
            return
        if not offs or rec[-1] != 0xFF:
            return
        for tk in offs:
            o = at + tk
            self.index[bytes(self.out[o:o + PREFIX])].append(o)
        self.exact.setdefault(rec, at)

    def append(self, rec: bytes) -> int:
        """공유하지 않고 반드시 새로 붙인다(섹션 0번 엔트리용)."""
        at = len(self.out)
        self.out += rec
        self._register(at, rec)
        return at

    def place(self, rec: bytes) -> int:
        hit = self.exact.get(rec)
        if hit is not None:
            self.reused += 1
            self.shared_bytes += len(rec)
            return hit
        for off in self.index.get(rec[:PREFIX], ()):
            if self.out[off:off + len(rec)] == rec:
                self.exact[rec] = off
                self.reused += 1
                self.shared_bytes += len(rec)
                return off
        return self.append(rec)
