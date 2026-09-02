#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FC 인수 2->1 정정에 따른 표기 이관.

바이트는 하나도 바뀌지 않는다 — 표식 {C:XXYY} 안에 삼켜져 있던 글자(대부분 여는 「)를
글자로 되돌려 놓을 뿐이다. 조판이 그 글자의 폭을 세지 못하던 것이 목적이다.

원문(jp)과 역문(ko)은 문자표가 다르다: 역문의 글리프 슬롯 일부는 한글로 갈아끼워져 있어
원래 문자표로 되읽으면 한자로 돌아가 버린다. 그래서 한글 배정을 얹은 역맵을 쓴다.
모든 문자열은 '이관 전 바이트 == 이관 후 바이트'를 통과해야만 채택한다.
"""
from __future__ import annotations
import glob, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode, ambiguous_glyphs   # noqa: E402
from span_classify import charmap                              # noqa: E402
from text_codec import parse_record, MB_ARITY                            # noqa: E402

ENC = build_encoder()
NAME = {0xF6: "N", 0xF7: "P", 0xF8: "8", 0xF9: "9", 0xFA: "A",
        0xFB: "B", 0xFC: "C", 0xFD: "D", 0xFE: "E"}
TAB, HEADER = "\t", "# id\tjp\tko"


def _rev(hangul: bool) -> tuple[dict, set]:
    m = dict(charmap()); m[0x000] = " "; m[0x3FF] = "\u3000"
    amb = set(ambiguous_glyphs())
    if hangul:
        p = ROOT / "translation" / "glyph_alloc.json"
        for ch, h in json.loads(p.read_text(encoding="utf-8"))["hangul"].items():
            g = int(h, 16); m[g] = ch; amb.discard(g)   # 한글 슬롯은 더 이상 모호하지 않다
    return m, amb


REV_JP, AMB_JP = _rev(False)
REV_KO, AMB_KO = _rev(True)


def markup(rec: bytes, rev: dict, amb: set) -> str:
    out = []
    for t in parse_record(rec, MB_ARITY):
        if t.kind == "glyph":
            ch = rev.get(t.glyph_id, "")
            out.append("{G:%03X}" % t.glyph_id if (t.glyph_id in amb or not ch) else ch)
        elif t.kind == "control":
            n = NAME.get(t.opcode, "%02X" % t.opcode)
            out.append("{" + n + "}" if not t.operands
                       else "{" + n + ":" + t.operands.hex().upper() + "}")
    return "".join(out)


def remap(s: str, rev: dict, amb: set) -> str:
    if not s:
        return s
    b = encode(s, ENC)
    new = markup(b, rev, amb)
    if encode(new, ENC) != b:
        raise ValueError("왕복 불일치: " + s[:60])
    return new


def main() -> int:
    p = ROOT / "translation" / "mbanks_ledger.json"
    L = json.loads(p.read_text(encoding="utf-8"))
    njp = nko = 0
    jpx: dict[str, str] = {}
    kox: dict[str, str] = {}
    for r in L["records"]:
        j = remap(r["jp"], REV_JP, AMB_JP)
        if j != r["jp"]:
            r["jp"] = j; njp += 1
        jpx[r["id"]] = j
        if r["ko"]:
            k = remap(r["ko"], REV_KO, AMB_KO)
            if k != r["ko"]:
                r["ko"] = k; nko += 1
        kox[r["id"]] = r["ko"]
    p.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"원장: jp {njp}건 · ko {nko}건 표기 이관")

    nb = 0
    for f in sorted(glob.glob(str(ROOT / "translation" / "batches" / "*.tsv"))):
        rows = Path(f).read_text(encoding="utf-8").splitlines()
        if not rows or rows[0].rstrip("\r") != HEADER:
            continue
        out, n = [rows[0]], 0
        for line in rows[1:]:
            q = line.rstrip("\r").split(TAB)
            if len(q) >= 3 and q[0] in jpx:
                jp, ko = jpx[q[0]], kox[q[0]]
                if q[2].strip() and not ko:      # 배치에만 있는 역문은 그대로 이관
                    ko = remap(q[2], REV_KO, AMB_KO)
                if jp != q[1] or ko != q[2]:
                    q[1], q[2], n = jp, ko, n + 1
            out.append(TAB.join(q))
        if n:
            Path(f).write_text("\n".join(out) + "\n", encoding="utf-8")
            nb += n
    print(f"배치: {nb}행 이관")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
