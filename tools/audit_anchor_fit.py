#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""위상 민감 앵커(FC/F8...) 앞 글리프 런의 advance/phase 적합성 감사.

근거: 도너 `third-ui/third_align_overrides.py` 문서화 —
"Width-safe override translations for ... runs whose Korean rendering advance
exceeds (or phase-mismatches) the retail run **before a phase-sensitive anchor
(FC/F8...)**. low glyph = 1 unit; high glyph = 1+phase, toggles phase."

즉 이 엔진의 렌더러는 **반칸 단위**로 진행하고, 전각 글리프는 위상에 따라 1 또는 2를 먹는다.
FC/F8 같은 앵커는 그 위상에 민감하므로, 역문 런은 원문 런과
  (1) advance 가 같거나 작고
  (2) 앵커 도달 시 phase 가 같아야
안전하다. 어긋나면 그리기가 틀어지고, 창 버퍼 밖으로 나가면 멈출 수 있다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections   # noqa: E402
from text_codec import parse_record, glyph_bytes  # noqa: E402
from span_classify import charmap                 # noqa: E402
from reinsert_build import build_encoder          # noqa: E402

ANCHORS = {0xF8, 0xF9, 0xFB, 0xFC, 0xFD}          # 인수를 갖는 위치/앵커 계열


def sig(ids: list[int], phase: int = 0) -> tuple[int, int]:
    adv = 0
    for i in ids:
        if i < 0x100:
            adv += 1
        else:
            adv += 1 + phase
            phase ^= 1
    return adv, phase


def runs_with_anchor(rec: bytes):
    """(글리프 ID 목록, 다음 제어 opcode) 목록."""
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


def main() -> int:
    data = (ROOT / "extract" / "DAT" / "D_NAMES.BIN").read_bytes()
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    led = {r["id"]: r for r in L["records"]}
    enc = build_encoder()
    cm = charmap()

    def rebuild(p, raw):
        rec = led.get(f"DN:{p:04X}")
        full = raw + bytes([0xFF])
        if not rec:
            return full
        out, cur = bytearray(), 0
        for s in sorted(rec["spans"], key=lambda x: x["start"]):
            out += full[cur:s["start"]]
            out += (b"".join(glyph_bytes(enc[c]) for c in s["ko"])
                    if s["ko"] else full[s["start"]:s["end"]])
            cur = s["end"]
        out += full[cur:]
        return bytes(out)

    alloc = json.loads((ROOT / "translation" / "glyph_alloc.json").read_text(encoding="utf-8"))
    inv = {int(v, 16): k for k, v in alloc["hangul"].items()}

    def dec(ids):
        return "".join(inv.get(i) or cm.get(i, "") or "?" for i in ids)

    over, phase_only = [], []
    seen = set()
    for sec in dnames_sections(data):
        if sec["start"] is None:
            continue
        for st in sec["strings"]:
            p = st["pointer"]
            if p in seen:
                continue
            seen.add(p)
            old = st["raw"] + bytes([0xFF])
            new = rebuild(p, st["raw"])
            if old == new:
                continue
            o_runs, n_runs = runs_with_anchor(old), runs_with_anchor(new)
            if len(o_runs) != len(n_runs):
                over.append((f"DN:{p:04X}", "런 개수 불일치", 0, 0, "", ""))
                continue
            ph_o = ph_n = 0
            first = True
            for (oi, oop), (ni, nop) in zip(o_runs, n_runs):
                ao, ph_o = sig(oi, ph_o)
                an, ph_n = sig(ni, ph_n)
                if oop not in ANCHORS:
                    continue
                if pad_to(ni, ph_n_prev, ao, ph_o) is None:
                    over.append((f"DN:{p:04X}", f"{oop:02X}", ao, an,
                                 "".join(cm.get(i, "") for i in oi), dec(ni)))
                else:
                    ph_n = ph_o                   # 패딩이 위상을 다시 맞춘다
    recs_over = len({x[0] for x in over})
    print(f"[위험] advance 넘침 {len(over)}건 / 레코드 {recs_over}개")
    for rid, op, a, b, ot, nt in sorted(over, key=lambda x: -(x[3] - x[2]))[:25]:
        print(f"  {rid} 앵커{op}  {a}->{b} (+{b-a})  {ot!r} -> {nt!r}")
    print("")
    print(f"[주의] 위상만 어긋남 {len(phase_only)}건 / 레코드 {len({x[0] for x in phase_only})}개")
    for rid, op, a, b, ot, nt in phase_only[:8]:
        print(f"  {rid} 앵커{op}  {a}->{b}  {ot!r} -> {nt!r}")
    (ROOT / "translation" / "_anchor_overflow.json").write_text(
        json.dumps([list(x) for x in over], ensure_ascii=False, indent=0), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
