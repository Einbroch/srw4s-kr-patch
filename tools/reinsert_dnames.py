#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 재삽입 — 확정 역문을 원본 구조 그대로 다시 인코딩한다.

레이아웃 원칙: **테이블은 원래 자리에 그대로 둔다.**
D_NAMES는 [18개 u32 헤더][섹션 테이블][그 섹션의 문자열 풀][다음 섹션 테이블]... 순으로
섹션마다 테이블 바로 뒤에 자기 풀이 붙는다. 테이블 위치를 유지하면 헤더 u32가 한 바이트도
바뀌지 않고, 접근자 `base + (header[sec] & 0xFFFF0000) + u16`도 그대로 성립한다.
바뀌는 것은 포인터 값과 풀 내용뿐이다.

별칭 섹션(S05/S09/S10/S16)은 소유 섹션 테이블의 부분 구간이므로 소유 테이블을 쓰면 같이 갱신된다.
"""
from __future__ import annotations
import json, struct, sys, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections   # noqa: E402
from text_codec import glyph_bytes, parse_record  # noqa: E402
from span_classify import charmap                 # noqa: E402

SRC = ROOT / "extract" / "DAT" / "D_NAMES.BIN"


def build_encoder() -> dict:
    cm = charmap()
    alloc = json.loads((ROOT / "translation" / "glyph_alloc.json").read_text(encoding="utf-8"))
    enc: dict[str, int] = {}
    for gid, ch in sorted(cm.items()):          # 낮은 ID 우선 = low bank 우선
        if ch and ch not in enc:
            enc[ch] = gid
    # 타깃 charmap 확정 사항(records/HANDOFF.md 2026-08-23):
    # 글리프 0x000 = 비트맵이 전부 0인 빈 8x16 = 도달 가능한 유일한 **반각 공백**(1바이트).
    # 전각 공백은 0x3FF로 따로 구분해 쓴다. charmap 역인덱스에는 빈 문자열로 들어와 있어
    # 자동으로는 잡히지 않으므로 여기서 명시한다.
    enc[" "] = 0x000
    enc["　"] = 0x3FF
    for ch, hexid in alloc["hangul"].items():   # 한글은 할당표가 정본
        enc[ch] = int(hexid, 16)
    return enc


def owners(secs: list[dict]) -> list[int]:
    """다른 섹션 테이블에 감싸이지 않은 섹션만 소유자다."""
    live = [s for s in secs if s["start"] is not None]
    out = []
    for s in live:
        if not any(o["start"] < s["start"] < o["table_end"] for o in live if o is not s):
            out.append(s["section"])
    return out


def main() -> int:
    data = SRC.read_bytes()
    secs = dnames_sections(data)
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    led = {r["id"]: r for r in L["records"]}
    enc = build_encoder()

    def rebuild(pointer: int, raw: bytes) -> bytes:
        rec = led.get(f"DN:{pointer:04X}")
        full = raw + bytes([0xFF])
        if not rec:
            return full
        out = bytearray(); cur = 0
        for s in sorted(rec["spans"], key=lambda x: x["start"]):
            out += full[cur:s["start"]]
            if s["ko"]:
                for ch in s["ko"]:
                    if ch not in enc:
                        raise SystemExit(f"인코딩 불가 문자 {ch!r} in {rec['id']}")
                    out += glyph_bytes(enc[ch])
            else:
                out += full[s["start"]:s["end"]]
            cur = s["end"]
        out += full[cur:]
        return bytes(out)

    own = owners(secs)
    live = [s for s in secs if s["start"] is not None]
    tbl_starts = sorted(s["start"] for s in live)

    rows = []
    for i in own:
        s = secs[i]
        pool_start = s["table_end"]
        after = [t for t in tbl_starts if t > pool_start]
        pool_cap = (min(after) if after else len(data)) - pool_start
        seen, size = {}, 0
        for st in s["strings"]:
            if st["pointer"] in seen:
                continue
            seen[st["pointer"]] = True
            size += len(rebuild(st["pointer"], st["raw"]))
        rows.append((i, pool_start, pool_cap, size, len(seen)))

    print(f"{'S':>3}{'풀시작':>8}{'용량':>8}{'재구성':>8}{'차이':>8}{'레코드':>7}")
    bad = 0
    for i, ps, cap, size, n in rows:
        d = cap - size
        if d < 0:
            bad += 1
        print(f"{i:>3}{ps:>8}{cap:>8}{size:>8}{d:>+8}{n:>7}{'  넘침' if d<0 else ''}")
    print(f"\n합계 용량 {sum(r[2] for r in rows):,}  재구성 {sum(r[3] for r in rows):,}  "
          f"여유 {sum(r[2]-r[3] for r in rows):+,}")
    print(f"넘치는 섹션 {bad}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
