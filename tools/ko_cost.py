#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""역문의 바이트 비용 계산 + 편집 적용.

한글 음절은 16x16 뱅크라 2 B, ASCII·공백·구두점은 저뱅크라 1 B다.
같은 글자 수라도 비용이 다르므로 **글자 수가 아니라 바이트로** 재야 한다.

사용법
  python tools/ko_cost.py report <섹션들>      비용 큰 레코드부터 보고
  python tools/ko_cost.py apply <patch.json>   {"DN:5FDB": {"1": "새 문장", ...}} 적용
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from span_classify import charmap    # noqa: E402

LEDGER = ROOT / "translation" / "dnames_ledger.json"

_base: dict[str, int] = {}
for _g, _c in sorted(charmap().items()):
    if _c and _c not in _base:
        _base[_c] = _g
_base[" "] = 0x000
_base["\u3000"] = 0x3FF


def cost(t: str) -> int:
    """이 문자열이 차지하는 바이트."""
    n = 0
    for ch in t:
        if "\uac00" <= ch <= "\ud7a3":
            n += 2
        else:
            g = _base.get(ch)
            n += 1 if (g is not None and g < 0x100) else 2
    return n


def load():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    L = load()
    if sys.argv[1] == "apply":
        patch = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        led = {r["id"]: r for r in L["records"]}
        saved = 0
        for rid, spans in patch.items():
            r = led[rid]
            for k, new in spans.items():
                sp = r["spans"][int(k)]
                old = sp.get("ko") or ""
                d = cost(old) - cost(new)
                if d < 0:
                    print(f"  [경고] {rid}[{k}] 오히려 {-d}B 늘어난다")
                saved += d
                sp["ko"] = new
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(patch)}레코드 적용 / 절약 {saved:,}B")
        return 0

    only = {x.strip() for x in sys.argv[2].split(",")} if len(sys.argv) > 2 else None
    rows = []
    for r in L["records"]:
        sec = r["owners"][0].split(":")[0] if r["owners"] else "?"
        if only and sec not in only:
            continue
        c = sum(cost(sp.get("ko") or "") for sp in r["spans"])
        if c:
            rows.append((c, r["id"], sec, r))
    rows.sort(reverse=True)
    for c, rid, sec, r in rows[:int(sys.argv[3]) if len(sys.argv) > 3 else 20]:
        print(f"### {rid}  {sec}  역문 {c}B")
        for k, sp in enumerate(r["spans"]):
            ko = sp.get("ko") or ""
            if ko:
                print(f"  [{k:2d}] {cost(ko):3d}B  {ko}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
