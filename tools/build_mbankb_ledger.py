#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BTT/M_BANKB.LZB 번역 원장 생성 — 전투 컷인 대사.

M_BANKS 와 **구조가 같다**(61엔트리 u32 헤더 -> 뱅크당 256개 u16 -> 0xFF 종단 레코드).
다른 점 둘:
  1. 파일이 LZB 로 압축돼 있어 먼저 풀어야 한다(`lzb.decompress`).
  2. 헤더 앞쪽 20칸이 **0**이라 `u32[0]` 을 헤더 크기로 쓸 수 없다.
     0이 아닌 최소 오프셋(=0xF4=61*4)이 헤더 크기다.
closure 자료가 없으므로 도달성은 판정하지 않는다(전부 live 취급).
"""
from __future__ import annotations
import hashlib, json, re, struct, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from text_codec import parse_record, MB_ARITY          # noqa: E402
from span_classify import charmap                      # noqa: E402
from mb_codec import ambiguous_glyphs                   # noqa: E402
import lzb                                              # noqa: E402

SRC = ROOT / "extract" / "BTT" / "M_BANKB.LZB"
OUT = ROOT / "translation" / "mbankb_ledger.json"
WINDOW = 0x400
ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 1, 0xFD: 2, 0xFE: 1}
JP = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def tok_end(buf: bytes, start: int, limit: int):
    p = start
    while p < limit:
        b = buf[p]
        if b == 0xFF:
            return p + 1
        if b < 0xF0:
            p += 1
        elif b <= 0xF5:
            p += 2
        else:
            a = ARITY.get(b)
            if a is None:
                return None
            p += 1 + a
    return None


def nslots(d: bytes, off: int) -> int:
    """표 길이는 뱅크마다 다르다(80~255칸). 256 고정으로 읽으면 레코드 바이트를
    포인터로 오해해 **가짜 레코드**가 쏟아진다(실측 312 -> 진짜 대사는 그중 일부).
    표 끝 = 어떤 슬롯도 표 자신을 가리키지 않는 최대 길이."""
    n, mn = 0, 1 << 30
    while off + 2 * (n + 1) <= len(d):
        v = struct.unpack_from("<H", d, off + 2 * n)[0]
        m = min(mn, v)
        if m < off + 2 * (n + 1) or v >= len(d):
            break
        mn = m
        n += 1
    return n


def markup(rec: bytes):
    m = charmap()
    m[0x000] = " "
    NAME = {0xF6: "N", 0xF7: "P", 0xF8: "8", 0xF9: "9", 0xFA: "A",
            0xFB: "B", 0xFC: "C", 0xFD: "D", 0xFE: "E"}
    amb = ambiguous_glyphs()
    out = []
    for t in parse_record(rec, MB_ARITY):
        if t.kind == "glyph":
            ch = m.get(t.glyph_id, "")
            out.append("{G:%03X}" % t.glyph_id if (t.glyph_id in amb or not ch) else ch)
        elif t.kind == "control":
            n = NAME.get(t.opcode, f"{t.opcode:02X}")
            out.append("{" + n + "}" if not t.operands
                       else "{" + n + ":" + t.operands.hex().upper() + "}")
    return "".join(out)


def main() -> int:
    raw_lzb = SRC.read_bytes()
    data, _used = lzb.decompress(raw_lzb)
    data = bytes(data)

    head = list(struct.unpack_from("<61I", data, 0))
    hdr = min(o for o in head if o)                     # 0xF4 = 61*4
    offsets = list(struct.unpack_from(f"<{hdr // 4}I", data, 0))

    owners = defaultdict(list)
    for bi, off in enumerate(offsets):
        if not off or off + 2 > len(data):
            continue
        base = off & ~0xFFFF
        n = nslots(data, off)
        for slot, rel in enumerate(struct.unpack_from(f"<{n}H", data, off)):
            t = base + rel
            if t < len(data):
                owners[t].append(f"H{bi:02d}:E{slot:04d}")

    byend = defaultdict(list)
    for t in owners:
        e = tok_end(data, t, min(t + WINDOW, len(data)))
        if e is not None:
            byend[e].append(t)

    records, skipped = [], 0
    for end, starts in sorted(byend.items()):
        s = min(starts)
        raw = data[s:end]
        try:
            mk = markup(raw)
        except Exception:
            skipped += 1
            continue
        if not JP.search(mk):
            continue
        records.append({
            "id": f"BB:{s:05X}",
            "offset": s,
            "end": end,
            "owners": sorted({o for t in starts for o in owners.get(t, [])})[:8],
            "alias_starts": [f"0x{x:05X}" for x in sorted(starts) if x != s],
            "live": True,
            "raw_hex": raw.hex().upper(),
            "jp": mk,
            "ko": "",
            "status": "untranslated",
            "note": None,
        })

    doc = {
        "schema": "srw4s-mbankb-ledger-v1",
        "source": {"path": "BTT/M_BANKB.LZB", "compressed": len(raw_lzb),
                   "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "unit": "record",
        "markers": {"{N}": "줄바꿈 F6", "{P}": "페이지 F7",
                    "{8:xx}": "F8+1바이트", "{9:xx}": "F9+1바이트", "{A}": "FA",
                    "{B:xxxx}": "FB selector", "{C:xx}": "FC+1바이트",
                    "{D:xxxx}": "FD+2바이트", "{E:xx}": "FE+1바이트"},
        "rule": "역문은 원문과 **같은 표식을 같은 개수로** 가져야 한다.",
        "protected_fields": ["source.*", "id", "offset", "end", "owners",
                             "alias_starts", "raw_hex", "jp"],
        "editable_fields": ["ko", "status", "note"],
        "records": records,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    strip = lambda t: re.sub(r"\{[^}]*\}", "", t)
    ch = sum(len(strip(r["jp"])) for r in records)
    print(f"뱅크 {sum(1 for o in offsets if o)}개 / 정본 레코드 {len(records):,}개 (파싱 실패 {skipped})")
    print(f"원문 글자 {ch:,}자")
    print(f"-> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
