#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`{A}` 레코드의 **앞머리를 원문 그대로** 되돌린다.

전투 대사 일부는 [표 데이터][「대사」] 꼴이다. 앞머리는 글자가 아니라
`{A}` 로 시작하는 표라서, 재조판이 거기에 `{N}` 을 끼워 넣으면 두 가지가 깨진다.

  1. 표 자체가 망가진다 (공백이 줄바꿈으로 바뀌기도 했다).
  2. `mb_rebank4` 의 별칭 처리가 무너진다 — 별칭은 역문 앞머리가 원문과
     **바이트로 같은 데까지만** 따라가고, 어긋나는 순간부터 원문 접미사 사본을
     따로 붙인다. 그 사본에 **일본어 대사 꼬리가 통째로 딸려 온다.**
     그래서 원본 15곳이던 「くっ,だめか!?」 가 빌드에서 일본어 59곳이 됐다.

`{A}` 는 산문 레코드에 한 번도 나오지 않는다(전수 확인) — 판별자로 안전하다.
고치는 방법은 하나뿐이다: 앞머리와 꼬리는 원문 바이트 그대로, 「」 안쪽만 역문.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, markers                    # noqa: E402
from mb_layout import rewrap, atom_px, atoms, LINE_PX          # noqa: E402
from reflow_ko import flatten                                  # noqa: E402

LEDGER = ROOT / "translation" / "mbanks_ledger.json"
MARK = "{A}"


def split(s: str):
    i, j = s.rfind("「"), s.rfind("」")
    return (s[:i + 1], s[i + 1:j], s[j:]) if 0 <= i < j else None


def width(markup: str, enc) -> int:
    return sum(atom_px(a, enc) for a in atoms(markup))


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()
    n, wrapped, bad = 0, 0, 0
    for r in L["records"]:
        if not r["ko"] or MARK not in r["jp"]:
            continue
        sj, sk = split(r["jp"]), split(r["ko"])
        if not sj or not sk:
            print(f"SKIP {r['id']}: 「」 짝을 못 찾았다")
            bad += 1
            continue
        q = flatten(sk[1])
        # 대사 한 줄이 창을 넘으면 그때만 다시 조판한다.
        if width(q, enc) > LINE_PX:
            q = rewrap(q, enc, LINE_PX)
            wrapped += 1
        new = sj[0] + q + sj[2]
        # 「」 밖 표식은 원문과 **완전히** 같아야 한다.
        if markers(sj[0] + sj[2]) != markers(split(new)[0] + split(new)[2]):
            print(f"FAIL {r['id']}: 앞뒤 표식이 어긋난다")
            return 1
        if new != r["ko"]:
            n += 1
            if apply:
                r["ko"] = new
    print(f"앞머리 복원 {n}개 / 대사 재조판 {wrapped}개"
          + (f" / 「」 없음 {bad}개" if bad else ""))
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장에 반영했다")
    else:
        print("(--apply 를 붙여야 반영된다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
