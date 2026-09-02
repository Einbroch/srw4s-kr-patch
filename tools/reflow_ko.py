#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""역문의 줄바꿈을 **처음부터 다시** 놓는다.

배치에 적힌 원본 역문의 `{N}` 은 줄당 30자 를 가정하고 찍은 것이라 실제 폭(320px)에
맞지 않는다. 그래서 `{N}` 을 전부 지우고 다시 조판하는데, 한국어는 띄어쓰기가 있어서
지운 자리에 공백이 필요한지 아닌지를 가려야 한다("모르는당신을" 사고).

  * 기본은 **공백을 넣는다** — 358개 경계를 전수 확인한 결과 대부분이 어절 경계였다.
  * 앞이 `...` 로 끝나거나 뒤가 `.` 로 시작하면 넣지 않는다(원문도 말줄임 뒤는 붙인다).
  * 나머지 어절 중간 끊김은 아래 표에 적는다.
"""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, markers          # noqa: E402
from mb_layout import (rewrap, violations, atom_px, atoms, LINE_PX,        # noqa: E402
                       VARIANT, budget)

LEDGER = ROOT / "translation" / "mbanks_ledger.json"

# 바이너리 앞머리 + 대사 꼬리로 된 레코드. 다시 조판하면 앞머리에 줄바꿈이 끼어 깨진다.
NO_REFLOW = {"MB:00014", "MB:004DD", "MB:05058", "MB:6BFAF", "MB:0D29D",
              # 앞머리가 글자가 아니라 FC08 뒤 u16 표 데이터라 폭 계산이 성립하지 않는다
              "MB:3AE49", "MB:3AEF3",
              # 같은 사정: 첫 「 앞이 전부 데이터라 폭·줄 계산이 성립하지 않는다
              "MB:0CC39", "MB:0CFCC", "MB:0D039",
              "MB:0F771", "MB:0FB43", "MB:0FBDD",
              # 엔딩 문구 — 승리 조건·엔딩 창은 대사창(296px)보다 좁다.
              # 원문 최대 폭이 248px 라 296px 로 재조판하면 창을 넘는다.
              "MB:65E2E", "MB:65E64", "MB:65ED3",
              # 도감의 **공용 앞머리**. 뒤 레코드가 같은 줄에 이어 그려지므로
              # 여기서 줄을 끊어 둬야 이어지는 쪽이 x=0 에서 시작한다.
              # 재조판에 맡기면 앞머리가 줄을 꽉 채워 뒤가 넘치고,
              # 넘친 만큼이 같은 줄 앞으로 감겨 글자를 덮어쓴다(실기 확인).
              "MB:585CB", "MB:597E8", "MB:5EE2B",
              # 앞머리가 표 데이터인데 `{A}` 토큰이 없어 자동 판별에 안 걸린다.
              # 통째로 재면 폭이 1,000px 넘게 나온다 — 화면에 나오는 건 「」 안쪽뿐이다.
              "MB:100E4", "MB:400E4", "MB:46045", "MB:62745",
              "MB:6489F", "MB:6884A",
              # 데이터 앞머리 + 꼬리 문자열 — 폭 측정이 뜻이 없다
              "MB:5FF4C"}

# 어절 중간에서 끊긴 자리 — 합칠 때 공백을 넣으면 안 된다. (앞토막, 뒤토막)
NO_SPACE = {
    # 이름 속 점 — 끊겼다 합쳐질 때 `라. 기어스` 로 벌어지면 안 된다
    ("라.", "기어스"), ("윌.", "윕스"), ("야크트.", "도가"), ("돈.", "자우사"),
    ("메카부스트.", "도미라"), ("메카부스트.", "가비탄"),
    ("그란.", "가란"), ("게아.", "가링"), ("디바인.", "크루세이더즈"),
    ("넬.", "아가마"), ("윌.", "윕스"),
    ("인스펙", "터란"), ("않겠", "습니까?」"), ("통달", "입니다."), ("빼앗", "겼나!?」"),
    ("경호", "니까..."), ("초", "나라"), ("뜻인", "가?」"), ("정체불명", "기가"),
    ("연구소", "네요."), ("생각", "이신지...」"), ("로봇", "입니다」{P}"),
    ("같았는데", "요오〜...뭘"), ("안성맞춤", "이겠어!!」"), ("마", "시지!!」"),
    ("아쉽", "네요오〜」"), ("살았어", "요오."), ("해야", "겠네」"),
    ("이름", "만이라도"), ("놈들", "이라면"), ("걸까", "요오〜?"),
    ("싶었는", "데에...」{"), ("참이었더", "라?"), ("좋아하", "잖아!」"),
    ("도착", "했습니다」"), ("있잖", "아!?」{P}{"), ("있었", "을"),
    ("출발", "할"), ("배속", "되다니"), ("실력", "이라면"), ("노리다", "니이」"),
    ("회복", "되고"), ("회복", "됐다!?」"), ("분이신가", "요오〜?」"),
    ("생각이다」", "마사키「..."), ("노이에", "DC의"),
}


def need_space(tail: str, head: str) -> bool:
    if not tail or not head:
        return False
    if tail.endswith("...") or head.startswith("."):
        return False
    return (tail, head) not in NO_SPACE


def is_menu(page: str, enc) -> bool:
    """선택지 페이지 — 대사가 아니라 **커서가 오르내리는 줄 목록**이다.

    따옴표가 없고 `{N}` 으로 나뉜 짧은 토막들로만 되어 있다(` Sガンダム{N}ガンタンク`).
    여기서 `{N}` 은 조판이 아니라 **구조**라, 지우면 선택지가 한 줄로 붙어
    두 번째 선택지가 화면에서 사라진다. 재조판 대상이 아니다.
    """
    if not page.startswith(" ") or "「" in page or "{N}" not in page:
        return False        # 선행 공백 = 커서가 설 자리. 이게 없으면 그냥 지문이다.
    seg = page.split("{N}")
    if len(seg) > 4:
        return False
    return all(sum(atom_px(a, enc) for a in atoms(s)) <= LINE_PX for s in seg)




def relayout_page(page: str, enc, line_px: int = LINE_PX) -> str:
    return "{N}".join(rewrap(flatten(x), enc, line_px) for x in VARIANT.split(page))


def relayout(ko: str, jp: str, enc, owners=()) -> str:
    """페이지 단위로 재조판하되, 선택지 페이지는 손대지 않는다.

    선택지인지는 **원문 페이지**로 판정한다 — 역문이 이미 망가져 선행 공백이나
    `{N}` 을 잃었으면 역문만 봐서는 선택지인 줄 알 수 없다."""
    kp, jpg = ko.split("{P}"), jp.split("{P}")
    if len(kp) != len(jpg):
        jpg = kp
    line_px = budget(jp, enc, owners)[0]   # 유닛 도감은 넓은 창(440px)이다
    return "{P}".join(k if is_menu(j, enc) else relayout_page(k, enc, line_px)
                      for k, j in zip(kp, jpg))


def flatten(ko: str) -> str:
    parts = ko.split("{N}")
    out = parts[0]
    for p in parts[1:]:
        if need_space(out.split(" ")[-1][-7:], p.split(" ")[0][:7]):
            out += " "
        out += p
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    idx = {r["id"]: r for r in L["records"]}
    # 배치 파일마다 열 구성이 다르다(`m01_short.tsv` 는 id/start/end/jp/ko).
    # 헤더가 `# id\tjp\tko` 인 것만 읽고, jp 가 원장과 **바이트 일치**하는 행만 정본으로 쓴다.
    src = {}
    for f in sorted(glob.glob(str(ROOT / "translation" / "batches" / "mb_*.tsv"))
                    + glob.glob(str(ROOT / "translation" / "mb_batches" / "*.tsv"))):
        rows = Path(f).read_text(encoding="utf-8").splitlines()
        if not rows or rows[0].rstrip("\r") != "# id\tjp\tko":
            continue
        for line in rows[1:]:
            q = line.rstrip("\r").split("\t")
            if len(q) < 3 or not q[2].strip():
                continue
            r = idx.get(q[0])
            if r is None or r["jp"] != q[1]:
                continue
            # strip() 금지 — 선택지 페이지의 **선행 공백은 커서가 설 자리**다.
            ko = q[2].replace("~", "〜").replace("～", "〜")
            ko = ko.replace("—", "-").replace("–", "-").replace("…", "...")
            src[q[0]] = ko
    enc = build_encoder()
    n, deep = 0, []
    for r in L["records"]:
        if not r["ko"]:
            continue
        # `{A}` 가 든 레코드는 [표 데이터][「대사」] 꼴이다. 앞머리는 글자가 아니라
        # 표라서 여기에 `{N}` 이 끼면 표가 깨지고, mb_rebank4 의 별칭 처리도 무너져
        # **일본어 원문 사본이 수십 벌 되살아난다**(tools/fix_data_prefix.py 참고).
        # `{A}` 는 산문 레코드에 한 번도 나오지 않는다 — 전수 확인했다.
        if "{A}" in r["jp"]:
            continue
        if r["id"] in NO_REFLOW:
            base = src.get(r["id"], r["ko"])
            if base != r["ko"] and apply:
                r["ko"] = base
                n += 1
            continue
        base = src.get(r["id"], r["ko"])
        new = relayout(base, r["jp"], enc, r.get("owners", ()))
        keep = lambda m: [x for x in markers(m) if x != "{N}"]
        if keep(new) != keep(base):
            print(f"FAIL: {r['id']} 표식이 바뀌었다")
            return 1
        lpx, plines = budget(r["jp"], enc, r.get("owners", ()))
        w, d = violations(new, enc, lpx, plines)
        if w:
            print(f"FAIL: {r['id']} 줄이 넘친다 {w[0]}")
            return 1
        if d:
            deep.append((r["id"], d))
        if new != r["ko"]:
            n += 1
            if apply:
                r["ko"] = new
    print(f"재조판 {n}개 / 3줄 초과 {len(deep)}개")
    for rid, d in deep:
        print(f"   {rid} " + " ".join(f"p{p}={c}줄" for p, c in d))
    if apply:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
        print("원장에 반영했다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
