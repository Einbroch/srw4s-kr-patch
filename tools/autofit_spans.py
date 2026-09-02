#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""앵커 앞 런이 원문보다 넓거나 위상이 어긋난 역문을 자동으로 줄여 맞춘다.

후보 생성 순서(정보량이 많은 쪽부터):
  1. 그대로            2. 공백 제거
  3. 공백 제거 + 뒤에서 한 글자씩 제거
각 후보는 `align_fit.pad_to`로 검사하고, **맞는 것 중 가장 긴 것**을 고른다.
하나도 못 맞추면 그 span은 역문을 비워 원문을 보존한다(fail safe — 화면은 일본어로 남지만
그리기는 깨지지 않는다). 무엇을 골랐는지 전부 출력해 사람이 검토한다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections     # noqa: E402
from text_codec import parse_record, glyph_bytes   # noqa: E402
from align_fit import sig, pad_to                  # noqa: E402
from reinsert_build import build_encoder           # noqa: E402

ANCH = {0xF8, 0xF9, 0xFB, 0xFC, 0xFD}


_OVR = {}
_p = ROOT / "translation" / "align_overrides.json"
if _p.exists():
    _OVR = json.loads(_p.read_text(encoding="utf-8"))["candidates"]


def candidates(ko: str, jp: str = ""):
    """뜻이 남는 후보를 먼저, 그다음 공백 제거, 마지막에 절단."""
    seen = []
    for c in _OVR.get(jp, []):
        if c not in seen:
            seen.append(c)
    for c in [ko, ko.replace(" ", "").replace("\u3000", "")]:
        if c and c not in seen:
            seen.append(c)
    base = seen[-1]
    for k in range(1, len(base)):
        c = base[:-k]
        if c:
            seen.append(c)
    seen.append("")
    return seen


def main() -> int:
    apply = "--apply" in sys.argv
    data = (ROOT / "extract" / "DAT" / "D_NAMES.BIN").read_bytes()
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    led = {r["id"]: r for r in L["records"]}
    enc = build_encoder()
    byp = {}
    for sec in dnames_sections(data):
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            byp.setdefault(st["pointer"], st["raw"])

    def runs(rec):
        out, cur = [], []
        for t in parse_record(rec):
            if t.kind == "glyph":
                cur.append(t.glyph_id)
            else:
                out.append((cur, t.opcode if t.kind == "control" else None))
                cur = []
        if cur:
            out.append((cur, None))
        return out

    def build(rid, raw, sub):
        rec = led[rid]
        full = raw + bytes([0xFF])
        out, cur = bytearray(), 0
        for s in sorted(rec["spans"], key=lambda x: x["start"]):
            out += full[cur:s["start"]]
            ko = sub.get(s["start"], s["ko"])
            out += (b"".join(glyph_bytes(enc[c]) for c in ko)
                    if ko else full[s["start"]:s["end"]])
            cur = s["end"]
        out += full[cur:]
        return bytes(out)

    changes = []
    for rid, rec in led.items():
        raw = byp.get(int(rid[3:], 16))
        if raw is None:
            continue
        old = raw + bytes([0xFF])
        sub: dict[int, str] = {}
        for _round in range(60):
            new = build(rid, raw, sub)
            if new == old:
                break
            o, n = runs(old), runs(new)
            if len(o) != len(n):
                break
            if not any(op in ANCH for _, op in o):
                break                    # 앵커 없는 이름·용어표는 폭 제약 대상이 아니다
            ph_o = ph_n = 0
            hit = None
            for (oi, oop), (ni, _) in zip(o, n):
                ao, ph_o2 = sig(oi, ph_o)
                _, ph_n2 = sig(ni, ph_n)
                if True:
                    if pad_to(ni, ph_n, ao, ph_o2) is None:
                        hit = (ao, ph_o2, ph_n, ni)
                        break
                    # 정렬기가 패딩으로 위상을 다시 맞춘다 — 시뮬레이션도 동기화해야
                    # 뒤쪽 런이 멀쩡한데도 어긋난 것으로 잘못 잡히지 않는다.
                    ph_n2 = ph_o2
                ph_o, ph_n = ph_o2, ph_n2
            if hit is None:
                break
            ao, tph, sph, ni = hit
            # 이 런에 해당하는 span 찾기: 런의 글리프 수와 위치로 매칭
            target = None
            pos = 0
            for s in sorted(rec["spans"], key=lambda x: x["start"]):
                ko = sub.get(s["start"], s["ko"])
                if ko and [enc[c] for c in ko] == ni:
                    target = s
                    break
            if target is None:
                break
            cur_ko = sub.get(target["start"], target["ko"])
            picked = None
            for c in candidates(cur_ko, target["jp"]):
                if any(ch not in enc for ch in c):
                    continue          # 타깃 문자표에 없는 후보는 건너뛴다
                ids = [enc[ch] for ch in c]
                if pad_to(ids, sph, ao, tph) is not None:
                    picked = c
                    break
            if picked is None or picked == cur_ko:
                sub[target["start"]] = ""
                changes.append((rid, target["start"], target["jp"], cur_ko, "<원문 보존>"))
                continue
            sub[target["start"]] = picked
            changes.append((rid, target["start"], target["jp"], cur_ko, picked))
        if apply and sub:
            for s in rec["spans"]:
                if s["start"] in sub:
                    s["ko"] = sub[s["start"]]
                    s["note"] = "앵커 폭 자동정렬"
    print(f"자동 정렬 {len(changes)}건")
    for rid, a, jp, old_ko, new_ko in changes:
        print(f"  {rid}[{a}] {jp[:20]!r}  {old_ko!r} -> {new_ko!r}")
    if apply:
        (ROOT / "translation" / "dnames_ledger.json").write_text(
            json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장에 반영했다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
