#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKB 역문이 **원본 레코드 바이트 안에** 들어가는지 본다.

이 파일은 RAM 에서 자랄 수 없다(구멍이 딱 맞게 차 있다 — `records/HANDOFF.md`
`mbankb-cannot-grow`). 그래서 역문은 원본 길이 이하여야 하고, 남는 자리는
종단 FF 앞에 공백 글리프로 메운다.

입력: KO = {레코드id: "「 뒤부터의 역문(」 포함)"}  — 앞머리는 원문 것을 그대로 쓴다.
"""
from __future__ import annotations
import importlib.util, io, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode   # noqa: E402

LEDGER = ROOT / "translation" / "mbankb_ledger.json"


def load_ko(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location("ko_mod", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.KO, getattr(m, "FULL", {}), getattr(m, "DROP", [])


def main() -> int:
    ko, full, drop = load_ko(Path(sys.argv[1]))
    doc = json.loads(LEDGER.read_text(encoding="utf-8"))
    by = {r["id"]: r for r in doc["records"]}
    enc = build_encoder()

    fit, over, miss, bad = [], [], [], []
    # FULL: 앞머리까지 통째로 쓴다(화자 이름이 화면에 그려지는 레코드)
    for rid, mk in full.items():
        r = by.get(rid)
        if r is None:
            miss.append(rid)
            continue
        total = r["end"] - r["offset"]
        try:
            b = encode(mk, enc)
        except KeyError as e:
            bad.append((rid, str(e)))
            continue
        (fit if len(b) <= total else over).append((rid, len(b), total, mk))

    for rid, txt in ko.items():
        if rid in full:
            continue
        r = by.get(rid)
        if r is None:
            miss.append(rid)
            continue
        jp = r["jp"]
        k = jp.find("「")
        prefix = jp[: k + 1]
        total = r["end"] - r["offset"]
        try:
            b = encode(prefix + txt, enc)
        except KeyError as e:
            bad.append((rid, str(e)))
            continue
        if len(b) <= total:
            fit.append((rid, len(b), total, txt))
        else:
            over.append((rid, len(b), total, txt))

    print(f"들어감 {len(fit)} / 넘침 {len(over)} / 없는 id {len(miss)} / 글리프없음 {len(bad)}")
    for rid, n, t, txt in over:
        print(f"  넘침 {rid} {n}>{t} (+{n-t})  {txt}")
    for rid, e in bad:
        print(f"  글리프없음 {rid} {e}")
    if miss:
        print("  없는 id:", miss)

    if "--apply" in sys.argv and not over and not bad:
        for rid, n, t, txt in fit:
            r = by[rid]
            pad = " " * (t - n)          # 남는 자리는 공백(1바이트 글리프)으로
            if rid in full:
                r["ko"] = txt + pad
            else:
                jp = r["jp"]
                r["ko"] = jp[: jp.find("「") + 1] + txt + pad
            r["status"] = "translated"
        for rid in drop:                 # 손대면 안 되는 레코드는 원문으로 되돌린다
            if rid in by:
                by[rid]["ko"] = ""
                by[rid]["status"] = "untranslated"
        LEDGER.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"원장에 {len(fit)}건 반영")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
