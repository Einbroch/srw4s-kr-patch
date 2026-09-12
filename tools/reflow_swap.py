#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""넘치는 줄을 **길이를 안 바꾸고** 다시 조판한다.

레이아웃 엔진은 자동 줄바꿈을 하지 않는다. `{N}` 으로 나뉜 구간을 그대로 한 줄로
그리므로, 넘치는 줄은 **그 구간이 긴 것**이다. 고치는 법은 구간 경계를 왼쪽으로
옮기는 것 — 끝쪽 어절을 다음 줄로 넘긴다.

  전  ...마라!! 사야카 씨,{N}보스, 간다!!」
  후  ...마라!!{N}사야카 씨, 보스, 간다!!」

공백 1 B 와 `{N}` 1 B 를 맞바꾸므로 **인코딩 길이가 같다.** M_BANKS 는 길이를
바꾸면 원장이 모르는 포인터가 어긋나 멈추는데([[mbanks-length-is-frozen]]),
이 방법은 그 제약을 지킨다.

검증기와 같은 기준을 쓴다(`verify_mb_ledger.py`):
  * `{A}` 가 있는 레코드는 앞머리가 **표 데이터**다. 통째로 재면 폭이 뻥튀기되고,
    한 글자라도 바꾸면 표가 어긋난다. 마지막 「」 **안쪽만** 재고 안쪽만 고친다.
  * 나머지는 `budget(jp, enc, owners)` 가 주는 (줄 폭, 줄 수)로 잰다.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from mb_codec import build_encoder, encode          # noqa: E402
from mb_layout import violations, budget, LINE_PX, PAGE_LINES   # noqa: E402

LEDGER = ROOT / "translation" / "mbanks_ledger.json"


def _inner(t: str):
    """고쳐도 되는 구간 = 마지막 인용부 안쪽.

    속마음 대사는 「」 가 아니라 **괄호 `( )`** 를 쓴다(`마사키(도청이라도...)`).
    괄호만 보던 시절에는 그런 쪽이 통째로 재조판에서 빠졌다 — 「」 를 먼저 찾고
    없을 때만 괄호를 본다(대사 안에 괄호가 섞인 경우를 밀어내지 않으려고).
    """
    a, b = t.rfind("「"), t.rfind("」")
    if 0 <= a < b:
        return (a + 1, b)
    a, b = t.rfind("("), t.rfind(")")
    return (a + 1, b) if 0 <= a < b else None


def bad(rec, ko: str, enc) -> int:
    """검증기와 같은 방식으로 위반 수를 센다."""
    if "{A}" in rec["jp"]:
        sp = _inner(ko)
        if not sp:
            return 0
        w, _ = violations(ko[sp[0]:sp[1]], enc, LINE_PX, PAGE_LINES)
        return len(w)
    lpx, pl = budget(rec["jp"], enc, rec.get("owners", ()))
    w, d = violations(ko, enc, lpx, pl)
    return len(w) + len(d)


def _words(seg: str):
    """어절 경계로 쪼갠다. 공백과 {N} 은 **둘 다 1 B** 라 서로 바꿔도 길이가 같다."""
    return [w for w in re.split(r" |\{N\}", seg) if w != ""]


def _px(t: str, enc) -> int:
    from mb_layout import layout as _lay
    rows = _lay(t, enc)
    return rows[0][0] if rows and rows[0] else 0


def _is_speech(t: str) -> bool:
    """인용부 안이 **진짜 한국어 대사**인가. 표가 글자로 디코드된 것과 가른다.

    `live` 표시는 못 믿는다([[live-false-is-table-data]]) — 화면에 버젓이 나오는
    레코드가 live:False 로 찍혀 있다(MB:6C649). 그래서 표시가 아니라 내용으로 본다.
    표 데이터는 가나·기호가 섞여 나오므로 한글 비율로 걸러진다.
    """
    body = re.sub(r"\{[^}]*\}", "", t)
    if len(body) < 2:
        return False
    # 가나가 한 자라도 있으면 표 데이터다. 한국어 역문에는 안 나온다 —
    # 비율 계산보다 이쪽이 훨씬 단단한 경계다.
    if re.search(r"[぀-ヿ]", body):
        return False
    han = sum(1 for c in body if "가" <= c <= "힣")
    # 2026-09-12 — **영문자를 세지 않아** `DC`·`ZZ건담`·`mkⅡ` 가 든 평범한 대사가
    # 표 데이터로 오판돼 재조판에서 통째로 빠졌다(MB:0D6E2 / MB:1BE37).
    ok = sum(1 for c in body
             if c.isspace() or c.isascii() and (c.isalnum() or c in ".,!?'\"()·:;-=/")
             or c in "~〜…")
    return han >= 2 and (han + ok) / len(body) >= 0.9


def _rewrap_page(rec, pg: str, enc, lpx: int, pl: int):
    """한 페이지의 **마지막 인용부 안쪽만** 다시 조판한다."""
    sp = _inner(pg)
    if not sp:
        return pg
    head, body, tail = pg[:sp[0]], pg[sp[0]:sp[1]], pg[sp[1]:]
    if not _is_speech(body):
        return pg
    first = 0 if "{A}" in rec["jp"] else _px(head.split("{N}")[-1], enc)
    used = len(head.split("{N}")) - 1
    ws = _words(body)
    if not ws:
        return pg
    # 마지막 줄에는 닫는 `」`(tail) 이 붙는다. 이걸 안 세면 288px 로 꽉 채운 줄이
    # 실제로는 296px 이 되어 화면에서 감긴다 — backlog 87건이 전부 이 8px 였다.
    # `_px` 는 첫 줄 폭만 재므로 tail 이 `{N}」` 이면 0 이 나온다(맞는 값이다).
    tailpx = _px(tail, enc)
    rows, cur, base = [], "", first
    for i, w in enumerate(ws):
        extra = tailpx if i == len(ws) - 1 else 0
        trial = w if cur == "" else cur + " " + w
        if base + _px(trial, enc) + extra <= lpx:
            cur = trial
        else:
            if cur == "":
                return None
            rows.append(cur)
            cur, base = w, 0
    rows.append(cur)
    if used + len(rows) + tail.count("{N}") > pl:
        return None
    return head + "{N}".join(rows) + tail


def rewrap(rec, ko: str, enc):
    """레코드를 다시 조판한다. **인용부 안쪽만** 바꾸고 길이는 그대로다.

    `{P}` 로 나뉜 페이지는 각각 따로 처리한다 — 넘치는 줄이 마지막 페이지가
    아닐 수 있다(MB:6C649 은 다섯 번째 페이지가 296px 였다).
    """
    lpx, pl = ((LINE_PX, PAGE_LINES) if "{A}" in rec["jp"]
               else budget(rec["jp"], enc, rec.get("owners", ())))
    out = []
    for pg in ko.split("{P}"):
        r = _rewrap_page(rec, pg, enc, lpx, pl)
        if r is None:
            return None
        out.append(r)
    v = "{P}".join(out)
    return None if v == ko else v


def plan(enc=None):
    enc = enc or build_encoder()
    doc = json.loads(LEDGER.read_text(encoding="utf-8"))
    fixed, stuck = [], []
    from verify_mb_ledger import NO_REFLOW
    for r in doc["records"]:
        ko = r.get("ko")
        if not ko:
            continue
        # 검증기가 조판을 재지 않는 것은 여기서도 건드리지 않는다.
        #   live:False — 화면에 안 뜨는 u16 표가 글자로 디코드된 것일 수 있다.
        #     이 표시는 믿을 게 못 되지만([[live-false-is-table-data]]), 표라면
        #     공백(0x00)을 {N}(0xF6) 로 바꾸는 순간 표가 깨진다. 만지지 않는다.
        #   NO_REFLOW — 바이너리 앞머리 + 대사 꼬리라 조판 검사가 뜻이 없다.
        if r["id"] in NO_REFLOW:
            continue
        if bad(r, ko, enc) == 0:
            continue
        n0 = len(encode(ko, enc))
        span = _inner(ko) if "{A}" in r["jp"] else (0, len(ko))
        if not span:
            stuck.append((r["id"], ko, "인용부를 못 찾음"))
            continue
        best = rewrap(r, ko, enc)
        if best is not None:
            # 게이트: 위반이 사라졌고, **길이가 한 바이트도 안 바뀌었고**,
            # 인용부 밖(표 데이터·화자 이름)이 그대로여야 한다.
            # 공백 1자 -> {N} 3자라 **문자열 길이는 바뀐다**(인코딩 바이트는 같다).
            # 그래서 인덱스가 아니라 내용으로 앞뒤를 대조한다.
            def _outside(t):
                return [re.sub(r"(?<=「).*(?=」)", "", pg, count=1)
                        for pg in t.split("{P}")]
            outside_same = _outside(best) == _outside(ko)
            if (bad(r, best, enc) or len(encode(best, enc)) != n0
                    or not outside_same):
                best = None
            else:
                # **별칭이 가리키는 자리보다 뒤에서만 바꾼다.**
                # 길이가 같으니 별칭 오프셋 자체는 안 밀린다. 문제는 그 자리의
                # *내용*이다. 첫 변화 지점이 모든 별칭보다 뒤면 rebank 의 접미사
                # 사본이 그대로라 파일 크기도 안 변한다.
                # (「별칭 있으면 통째로 제외」로 막았더니 화면에 넘치는 대사가
                #  남았다 — MB:6C649 은 별칭이 앞쪽인데 넘치는 줄은 뒤 페이지였다.)
                # 별칭이 안쪽을 가리키는 레코드는 여기서 막지 않는다.
                # 별칭 1,942개 중 대부분은 **원문 접미사 사본**이라 역문을 바꿔도
                # 영향이 없고(MB:6C649 로 실측), 역문에 매핑된 51개만 문제다.
                # 어느 쪽인지는 모델로 가리기 어려워, 적용 뒤 **rebank 출력 크기**로
                # 거른다(tools/reflow_swap.py --apply 뒤 크기가 변하면 그 건을 뺀다).
                pass
        if best:
            fixed.append((r["id"], ko, best))
        else:
            stuck.append((r["id"], ko, "길이를 지키며 고칠 수 없음"))
    return fixed, stuck


def main() -> int:
    apply = "--apply" in sys.argv
    enc = build_encoder()
    fixed, stuck = plan(enc)
    print(f"넘치는 레코드 {len(fixed) + len(stuck)}건")
    print(f"  길이를 지키며 고칠 수 있음 : {len(fixed)}건")
    print(f"  그래도 안 되는 것          : {len(stuck)}건")
    for i, o, n in fixed[:15]:
        print("  " + i)
        print("    - " + o)
        print("    + " + n)
    if len(fixed) > 15:
        print(f"  ... 외 {len(fixed) - 15}건")
    if not apply:
        print("")
        print("--apply 를 주면 원장에 씁니다.")
        return 0
    s = LEDGER.read_text(encoding="utf-8")
    doc = json.loads(s)
    assert json.dumps(doc, ensure_ascii=False, indent=1) == s, "원장 형식이 다르다"
    by = {r["id"]: r for r in doc["records"]}
    for i, _o, n in fixed:
        by[i]["ko"] = n
    LEDGER.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("")
    print(f"원장에 {len(fixed)}건 적용")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
