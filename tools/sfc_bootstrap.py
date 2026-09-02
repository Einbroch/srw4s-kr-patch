#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFC 한글패치의 글리프 -> 음절 표를 **용어 대응**으로 부트스트랩한다.

왜 이렇게 하나
  SFC 한글패치의 글꼴은 갈무리 계열이 아니라 비트맵 대조로는 못 읽는다(정확 일치 0).
  대신 구조를 쓴다:
    * SFC 일본판은 **PS1 charmap 으로 그대로 디코드**된다(같은 글꼴을 공유한다).
    * 일본판/한글판의 텍스트 블록은 **엔트리 단위로 대응**한다(포인터표 길이·구조 동일).
    * 저뱅크 글자(구두점·ASCII·「」·제어)는 **양쪽이 같다** — 정렬 기준점이 된다.
  그래서 기준점 사이 구간에서 일본어가 내가 이미 번역한 용어와 정확히 같으면,
  같은 자리의 한글 글리프 수와 음절 수가 맞을 때 글리프->음절을 확정할 수 있다.

용어 사전은 D_NAMES 원장에서 만든다(원문은 raw_hex 를 charmap 으로 디코드).
"""
from __future__ import annotations
import json, struct, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from span_classify import charmap        # noqa: E402
from text_codec import parse_record      # noqa: E402

JROM = ROOT / "reference/sfc-kor/Dai-4-ji Super Robot Taisen (Japan) (Rev 1).sfc"
KROM = ROOT / "reference/sfc-kor/Dai-4-ji Super Robot Taisen (Korea) (Rev 1) v1.01.sfc"
ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 2, 0xFD: 2, 0xFE: 1}
CM = dict(charmap())


def tokens(d: bytes, p: int, limit: int = 4000):
    """(종류, 값) 목록. 종류: 'lo'(저뱅크 문자) / 'hi'(16x16 글리프 ID) / 'ctl'."""
    out = []
    while p < len(d) and len(out) < limit:
        b = d[p]
        if b == 0xFF:
            return out
        if b < 0xF0:
            out.append(("lo", b)); p += 1
        elif b <= 0xF5:
            out.append(("hi", ((b + 1) << 8 & 0x0F00) | d[p + 1])); p += 2
        else:
            out.append(("ctl", b)); p += 1 + ARITY[b]
    return out


def glossary() -> dict[str, str]:
    """일본어 원문 -> 내 한국어 역문 (D_NAMES 이름·용어)."""
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    g: dict[str, str] = {}
    for r in L["records"]:
        raw = bytes.fromhex(r["raw_hex"])
        toks = None
        for cand in (raw, raw + bytes([0xFF])):
            try:
                toks = parse_record(cand); break
            except Exception:
                pass
        if toks is None:
            continue
        pos, mp = 0, {}
        for t in toks:
            mp[pos] = t; pos += len(t.raw)
        for s in r["spans"]:
            ko = s.get("ko") or ""
            st, en = s.get("start"), s.get("end")
            if not ko or st is None or en is None:
                continue
            ja, p = "", st
            ok = True
            while p < en and p in mp:
                t = mp[p]
                if t.kind != "glyph":
                    ok = False; break
                ja += CM.get(t.glyph_id, "")
                p += len(t.raw)
            if ok and 2 <= len(ja) <= 14 and ja not in g:
                g[ja] = ko
    return g


def main() -> int:
    j, k = JROM.read_bytes(), KROM.read_bytes()
    JB, KB, N = 0x2D0000, 0x3C0000, 240
    jp = struct.unpack_from(f"<{N}H", j, JB)
    kp = struct.unpack_from(f"<{N}H", k, KB)
    gl = glossary()
    print(f"용어 사전 {len(gl):,}개")

    votes: dict[int, Counter] = defaultdict(Counter)
    pairs = 0
    for i in range(N):
        jt = tokens(j, JB + jp[i])
        kt = tokens(k, KB + kp[i])
        # 저뱅크/제어를 기준점으로 구간을 나눈다
        def split(ts):
            segs, cur = [], []
            for kind, v in ts:
                if kind == "hi":
                    cur.append(v)
                else:
                    segs.append((tuple(cur), (kind, v))); cur = []
            segs.append((tuple(cur), None))
            return segs
        js, ks = split(jt), split(kt)
        if len(js) != len(ks):
            continue
        for (jg, ja), (kg, ka) in zip(js, ks):
            if ja != ka or not jg or not kg:
                continue
            ja_txt = "".join(CM.get(g, "") for g in jg)
            ko = gl.get(ja_txt)
            if not ko or len(ko) != len(kg):
                continue
            pairs += 1
            for g, c in zip(kg, ko):
                votes[g][c] += 1

    solved = {g: c.most_common(1)[0][0] for g, c in votes.items()
              if c.most_common(1)[0][1] >= 2 or len(c) == 1}
    print(f"대응 구간 {pairs:,}개 -> 글리프 {len(votes)}종 관측 / 확정 {len(solved)}")
    print("  예시:", [(hex(g), c) for g, c in list(solved.items())[:16]])
    (ROOT / "build" / "sfc_glyph_map.json").write_text(
        json.dumps({f"0x{g:03X}": c for g, c in sorted(solved.items())},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("-> build/sfc_glyph_map.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
