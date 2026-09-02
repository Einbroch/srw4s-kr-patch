#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 번역 원장 생성 — D_NAMES에서 배운 것을 처음부터 적용한다.

구조: 61엔트리 u32 헤더 -> 뱅크당 256개 u16(뱅크 상대) -> 레코드는 0x400 창 안에서 종단.

D_NAMES 작업에서 값비싸게 배운 계약들:
  1. **정본 레코드**: 포인터 여럿이 한 종단을 공유한다(접미사 관계). 종단으로 묶어
     가장 앞선 시작만 정본으로 센다. 안 그러면 물량이 파일 크기를 넘는다.
  2. **스팬 경계 = 토큰 경계**: 제어 토큰(F8 수치삽입, FB selector, F6 줄바꿈)을
     스팬이 삼키면 재인코딩 때 삭제되어 **게임이 멈춘다**.
  3. **커버리지 지표**: '번역된 span / 전체 span'이 아니라 '스팬 밖에 남은 원문 글자수'.
  4. 원문 순서·인접성은 재삽입 때 보존한다(D_NAMES 스크립트 섹션에서 실증).
"""
from __future__ import annotations
import csv, hashlib, json, re, struct, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from text_codec import parse_record, MB_ARITY          # noqa: E402
from span_classify import charmap            # noqa: E402
from mb_codec import ambiguous_glyphs        # noqa: E402

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
CLOSURE = ROOT / "analysis" / "mbanks_live_closure.tsv"
OUT = ROOT / "translation" / "mbanks_ledger.json"
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


def markup(rec: bytes):
    """레코드 전체를 '글자 + 인라인 제어 표식' 한 덩어리로 만든다.

    대사는 문장 중간에 줄바꿈(F6)이 들어가므로 제어 토큰마다 끊으면 `ません」` 같은
    **번역 불가능한 조각**이 된다(어순이 다른 한국어로는 조각 단위 번역이 성립하지 않는다).
    그래서 레코드를 통째로 번역 단위로 삼고, 제어 토큰은 표식으로 보존한다:
        {N}      줄바꿈 F6        {P}   페이지 F7
        {8:2A}   F8 + 1바이트 인수 (수치 삽입점 등)
        {B:9012} FB + 2바이트 인수 (메시지 selector)
    표식은 역문에서도 반드시 같은 개수로 유지해야 하며, 재인코딩기가 그것으로 복원한다.
    """
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
    data = SRC.read_bytes()
    first = struct.unpack_from("<I", data, 0)[0]
    offsets = list(struct.unpack_from(f"<{first // 4}I", data, 0))

    owners = defaultdict(list)          # 대상 오프셋 -> [슬롯 id]
    for bi, off in enumerate(offsets):
        if not off or off + 0x200 > len(data):
            continue
        base = off & ~0xFFFF
        for slot, rel in enumerate(struct.unpack_from("<256H", data, off)):
            t = base + rel
            if t < len(data):
                owners[t].append(f"H{bi:02d}:E{slot:04d}")

    live = set()
    if CLOSURE.exists():
        with CLOSURE.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                try:
                    live.add(int(row["target_offset"], 16))
                except Exception:
                    pass

    # 종단을 공유하면 접미사 관계 -> 가장 앞선 시작만 정본
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
            "id": f"MB:{s:05X}",
            "offset": s,
            "end": end,
            "owners": sorted({o for t in starts for o in owners.get(t, [])})[:8],
            "alias_starts": [f"0x{x:05X}" for x in sorted(starts) if x != s],
            "live": bool(live & set(starts)),
            "raw_hex": raw.hex().upper(),
            "jp": mk,
            "ko": "",
            "status": "untranslated",
            "note": None,
        })

    doc = {
        "schema": "srw4s-mbanks-ledger-v1",
        "source": {"path": "DAT/M_BANKS.BIN", "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()},
        "unit": "record",
        "markers": {"{N}": "줄바꿈 F6", "{P}": "페이지 F7",
                    "{8:xx}": "F8+1바이트", "{9:xx}": "F9+1바이트", "{A}": "FA",
                    "{B:xxxx}": "FB+2바이트 selector", "{C:xxxx}": "FC+2바이트",
                    "{D:xxxx}": "FD+2바이트", "{E:xx}": "FE+1바이트"},
        "rule": "역문은 원문과 **같은 표식을 같은 개수로** 가져야 한다. 표식은 제어 토큰이며 빠지면 게임이 멈춘다.",
        "protected_fields": ["source.*", "id", "offset", "end", "owners", "alias_starts", "raw_hex", "jp"],
        "editable_fields": ["ko", "status", "note"],
        "records": records,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    nlive = sum(1 for r in records if r["live"])
    strip = lambda t: re.sub(r"\{[^}]*\}", "", t)
    nsp = len(records)
    nsp_live = nlive
    ch = sum(len(strip(r["jp"])) for r in records)
    ch_live = sum(len(strip(r["jp"])) for r in records if r["live"])
    print(f"정본 레코드 {len(records):,}개 (파싱 실패 {skipped})")
    print(f"  closure 도달 {nlive:,}개 / 그 외 {len(records)-nlive:,}개")
    print(f"번역 단위 = 레코드")
    print(f"원문 글자 {ch:,}자 (closure {ch_live:,}자)")
    print(f"-> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
