#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""글리프 할당표 재생성 — D_NAMES + M_BANKS 양쪽 역문을 함께 본다.

  살아야 할 글리프 = D_NAMES 미번역분 + M_BANKS 미번역 레코드가 쓰는 16x16 글리프
  한글 수요       = 두 원장의 역문에 쓰인 고유 음절
  슬롯 순위       = 아무도 안 쓰는 칸 -> 남은 사용 빈도가 낮은 칸 -> ID 순
(번역이 진행될수록 그 레코드의 한자가 풀려 자유 슬롯이 늘어난다.)
"""
from __future__ import annotations
import json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from glyph_census import dnames_survivors        # noqa: E402
from text_codec import parse_record               # noqa: E402
from span_classify import charmap                 # noqa: E402
from hangul_font import HangulFont                # noqa: E402

EXTRA: dict = {}
try:
    import runpy as _rp
    EXTRA = _rp.run_path(str(ROOT / "translation" / "glyph_extra.py"))["EXTRA"]
except Exception:
    pass

LO, HI = 0x100, 0x700

# **코드가 직접 넣는 글리프** — 텍스트 어디에도 안 나와서 빈도 조사에 안 잡힌다.
# 0x6FC~0x6FF 는 PS 버튼 기호 ○ × △ □ 이고, 버튼 설정 화면이 이것을 그린다.
# charmap 은 이 자리를 飽/割/▲/や 로 잘못 적어 두었으니 문자 기준 필터로는 못 거른다.
# (2026-08-24 실기: 한글이 덮여서 결정/캔슬/스피드업/전체맵 값이 매/맥/맨/맵 으로 나왔다.)
CODE_GLYPHS = {0x6FC, 0x6FD, 0x6FE, 0x6FF}
OUT = ROOT / "translation" / "glyph_alloc.json"
TOK = re.compile(r"\{[^}]*\}")


def main() -> int:
    keep, _ = dnames_survivors()
    live = Counter({g: c for g, c in keep.items() if LO <= g < HI})

    MB = json.loads((ROOT / "translation" / "mbanks_ledger.json").read_text(encoding="utf-8"))
    mb_tr = 0
    for r in MB["records"]:
        if r["ko"]:
            mb_tr += 1
            continue                              # 번역됨 -> 이 한자들은 놓아준다
        for t in parse_record(bytes.fromhex(r["raw_hex"])):
            if t.kind == "glyph" and LO <= t.glyph_id < HI:
                live[t.glyph_id] += 1

    DN = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    syl = {ch for r in DN["records"] for s in r["spans"] if s["ko"]
           for ch in s["ko"] if "\uac00" <= ch <= "\ud7a3"}
    syl |= {ch for r in MB["records"] if r["ko"]
            for ch in TOK.sub("", r["ko"]) if "\uac00" <= ch <= "\ud7a3"}
    # BTT/M_BANKB.LZB(전투 컷인)도 같은 글리프표를 쓴다. 여기 음절이 빠지면
    # 컷인 역문이 엉뚱한 글자로 그려진다.
    BBP = ROOT / "translation" / "mbankb_ledger.json"
    if BBP.exists():
        BB = json.loads(BBP.read_text(encoding="utf-8"))
        syl |= {ch for r in BB["records"] if r["ko"]
                for ch in TOK.sub("", r["ko"]) if "가" <= ch <= "힣"}

    # 한글이 아닌 **선언된 추가 글리프**(translation/glyph_extra.py) 도 자리를 받는다.
    syl |= set(EXTRA)
    syl = sorted(syl)

    font = HangulFont()
    missing = [c for c in syl if c not in font and c not in EXTRA]
    if missing:
        print(f"FAIL: 글꼴에 없는 음절 {len(missing)}자: {''.join(missing[:20])}")
        return 1

    # 자유 슬롯이 수요보다 적으면(= M_BANKS가 아직 대부분 일본어면) **잔여 빈도가 낮은 칸부터**
    # 덮는다. 저빈도 한자는 고유명사에 몰려 있어 눈에 띄지만, 다른 선택지가 없다 —
    # 번역이 진행될수록 그 한자들이 풀려 충돌이 저절로 줄어든다.
    # 역문 자신이 쓰는 **비한글** 글리프도 지켜야 한다. 안 지키면 그 칸이 한글에 넘어가
    # 역문 안의 공백·문장부호·구두점이 엉뚱한 글자로 그려진다.
    # (2026-08-23: 전각공백 0x3FF 가 '응'에게 넘어갔다 — 원문 기준으로만 live 를 셌기 때문.)
    base: dict[str, int] = {}
    for gid, ch in sorted(charmap().items()):
        if ch and ch not in base:
            base[ch] = gid
    base[" "] = 0x000
    base["　"] = 0x3FF
    need: set[int] = set()

    def scan(t: str) -> None:
        for ch in t:
            if "가" <= ch <= "힣":
                continue
            g = base.get(ch)
            if g is not None and LO <= g < HI:
                need.add(g)

    for r in DN["records"]:
        for sp in r["spans"]:
            if sp["ko"]:
                scan(sp["ko"])
    for r in MB["records"]:
        if r["ko"]:
            scan(TOK.sub("", r["ko"]))
            for m in re.finditer(r"\{G:([0-9A-Fa-f]{3})\}", r["ko"]):
                g = int(m.group(1), 16)
                if LO <= g < HI:
                    need.add(g)      # 역문이 ID 로 직접 지목한 글리프

    need |= CODE_GLYPHS
    free = [g for g in range(LO, HI) if g not in live and g not in need]
    used = sorted((g for g in live if g not in need), key=lambda g: (live[g], g))
    cand = free + used
    if len(syl) > len(cand):
        print(f"FAIL: 수요 {len(syl)} > 전체 슬롯 {len(cand)}")
        return 1

    # **이전 배정을 유지한다.** 세이브 파일에 주인공 이름이 *글리프 ID* 로 들어 있어서,
    # 할당표가 바뀌면 이미 만든 세이브의 이름이 다른 글자로 읽힌다
    # (2026-08-24 실기: 로드 화면 이름이 세이브 화면과 달랐다).
    # 그래서 본문을 고쳐도 기존 음절의 ID 는 그대로 두고 **새 음절만** 남은 자리에 넣는다.
    prev: dict[str, int] = {}
    if OUT.exists():
        try:
            prev = {c: int(g, 16)
                    for c, g in json.loads(OUT.read_text(encoding="utf-8")).get("hangul", {}).items()}
        except Exception:
            prev = {}
    candset = set(cand)
    alloc: dict[str, int] = {}
    taken: set[int] = set()
    for c in syl:
        g = prev.get(c)
        if g is not None and g in candset and g not in taken:
            alloc[c] = g
            taken.add(g)
    kept = len(alloc)
    # **기존 배정이 하나라도 옮겨지면 멈춘다.** 세이브가 주인공 이름을 글리프 ID 로
    # 들고 있어(2026-08-24 실기) 배정이 바뀌면 이미 만든 세이브의 이름이 깨진다.
    # 2026-09-12: 글자 하나 추가하려고 돌렸다가 71자가 조용히 옮겨졌다 —
    # 배포된 글꼴에서 비트맵을 대조해 역산해 되돌려야 했다.
    lost = sorted(c for c in prev if c in syl and c not in alloc)
    if lost and "--allow-move" not in sys.argv:
        print(f"FAIL: 기존 배정 {len(lost)}자가 옮겨진다 — 세이브의 이름이 깨진다.")
        print(f"  {''.join(lost[:40])}{'...' if len(lost) > 40 else ''}")
        print("  이전 슬롯이 이번 후보에서 빠졌다(보존/역문보호로 분류되었을 수 있다).")
        print("  정말 옮겨야 하면 --allow-move 를 주고, **기존 세이브가 깨진다**고 알린다.")
        return 1
    pool = iter([g for g in cand if g not in taken])
    for c in syl:
        if c in alloc:
            continue
        try:
            alloc[c] = next(pool)
        except StopIteration:
            print(f"FAIL: 새 음절 {c!r} 을 넣을 자리가 없다")
            return 1
        taken.add(alloc[c])
    print(f"이전 배정 유지 {kept}자 / 새로 배정 {len(syl) - kept}자")
    preserved = (set(live) | need) - set(alloc.values())

    cm = charmap()
    doc = {
        "schema": "srw4s-glyph-alloc-v2",
        "policy": {
            "sources": "D_NAMES + M_BANKS 두 원장의 역문",
            "live": "D_NAMES 미번역분 + M_BANKS 미번역 레코드가 쓰는 16x16 글리프",
            "order": "미사용 -> 잔여 빈도 낮은 순 -> ID 순",
            "stability": "한글 ID는 이후 단계에서도 재배치하지 않는다",
        },
        "supply": {"slots": HI - LO, "preserved": len(preserved), "candidates": len(cand)},
        "demand": {"hangul": len(syl), "mbanks_translated": mb_tr},
        "preserved_ids": {f"0x{g:03X}": cm.get(g, "") for g in sorted(preserved)},
        "hangul": {c: f"0x{alloc[c]:03X}" for c in syl},
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    clash = [g for g in alloc.values() if live.get(g, 0)]
    dmg = sum(live[g] for g in clash)
    tot = sum(live.values())
    print(f"16x16 슬롯 {HI-LO}  자유 {len(free)}  보존 {len(preserved)}  역문보호 {len(need)}")
    print(f"덮은 사용중 슬롯 {len(clash)}칸 — 남은 일본어 글리프 사용 {tot:,}회 중 {dmg:,}회 영향 ({dmg/tot*100:.1f}%)")
    print(f"한글 {len(syl)}자 할당 (M_BANKS 번역 {mb_tr}레코드 반영)")
    print(f"잔여 여유 {len(cand)-len(syl)}칸")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
