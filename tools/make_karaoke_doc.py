#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""가라오케 가사(D_NAMES S17)를 번역 작업용 문서로 뽑는다.

한도는 **줄 단위가 아니라 D_NAMES 총량**이다. 그래서 예산을 전체로 잡고 줄마다
원문 길이에 비례해 나눠 준다. 첫 판에서 원문 바이트의 절반을 줄 한도로 줬더니
띄어쓰기와 조사가 전부 빠진 역문이 나왔다 — 그건 한도가 틀렸던 것이다.

**진짜 한도는 D_NAMES 공간이 아니라 화면 폭이다** (2026-09-02 실기 확인).
  이 폰트는 한글 1자 = 2바이트 = 16px, 공백/반각기호 = 1바이트 = 8px 이라
  **바이트 수 x 8 = 픽셀 폭**이다. 화면은 320px 이고 가사는 두 단계 들여쓰기로
  번갈아 그려진다 — 깊은 쪽이 약 109px 에서 시작하므로 (320-109)/8 = **26바이트**.
  실측: 24B 는 들어가고("정의의 마음을 파일더 온!"), 30B 는 넘쳤다.

  D_NAMES 공간은 넉넉하다 (슬롯 55,296 / 가사 몫 약 4,000 B). 124줄 x 26B = 3,224 B
  라 공간은 더 이상 제약이 아니다.

줄 목록은 **원장에서 직접** 읽는다. TSV 를 읽으면 원장에만 있는 줄을 놓친다 —
실제로 `spans` 가 비어 있어 건너뛴 6줄이 게임에서 일본어로 떴다.
"""
from __future__ import annotations
import csv
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

TSV = ROOT / "records" / "karaoke_lyrics.tsv"
LINE_MAX = 26          # 화면 폭 한도 (26 x 8 = 208px)


GROUPS = [
    (0xC202, 0xC280, "마징가Z"),
    (0xC286, 0xC310, "겟타로보"),
    (0xC312, 0xC3AA, "콤바트라V"),
    (0xC3AE, 0xC440, "다이탄3"),
    (0xC44E, 0xC4D8, "용자 라이딘"),
    (0xC4EC, 0xC5A0, "성전사 단바인"),
    (0xC5A3, 0xC610, "전국마신 고쇼군"),
    (0xC61C, 0xC69A, "UFO로보 그렌다이저"),
    (0xC6A7, 0xC720, "무적초인 잔보트3"),
    (0xC72A, 0xC7C8, "투장 다이모스"),
    (0xC7D1, 0xC8B0, "미상 — 발라드"),
    (0xC903, 0xC990, "열풍! 질풍! 사이바스터"),
    (0xC99C, 0xCA60, "미상 — 오리지널"),
]


def group_of(rid: str) -> str:
    v = int(rid.split(":")[1], 16)
    for lo, hi, name in GROUPS:
        if lo <= v <= hi:
            return name
    return "미분류"


def rows_from_ledger() -> list[dict]:
    """S17 의 일본어 스팬을 순서대로 뽑는다 (원장이 정본)."""
    import re
    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    jp_re = re.compile(r"[぀-ヿ一-鿿]")
    out = []
    for r in L["records"]:
        ow = r["owners"]
        if not (ow and ow[0].startswith("S17")):
            continue
        for s in r["spans"]:
            if not jp_re.search(s["jp"]):
                continue
            out.append({"id": r["id"], "jp": s["jp"],
                        "bytes": str(s["end"] - s["start"]),
                        "ko": (s.get("ko") or "").strip()})
    out.sort(key=lambda r: int(r["id"].split(":")[1], 16))
    return out


def budget_for(rows: list[dict]) -> None:
    """줄마다 화면 폭 한도를 준다. 공간이 아니라 폭이 제약이므로 전부 같은 값이다."""
    for r in rows:
        r["max_bytes"] = str(LINE_MAX)
        r["max_ko"] = str((LINE_MAX - 3) // 2)   # 공백을 셋쯤 쓴다고 보고 환산


def main() -> int:
    from mb_codec import build_encoder, encode
    enc = build_encoder()
    rows = rows_from_ledger()
    budget_for(rows)
    for r in rows:
        ko = (r.get("ko") or "").strip()
        try:
            r["now"] = str(len(encode(ko, enc)) - 1) if ko else "0"
        except KeyError:
            r["now"] = "?"

    tot_jp = sum(int(r["bytes"]) for r in rows)
    tot_now = sum(int(r["now"]) for r in rows if r["now"].isdigit())
    tot_max = sum(int(r["max_bytes"]) for r in rows)

    cols = ["id", "jp", "bytes", "max_bytes", "max_ko", "ko"]
    with TSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, delimiter="\t", fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    json.dump([{c: r.get(c, "") for c in cols} for r in rows],
              (ROOT / "records" / "karaoke_lyrics.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(group_of(r["id"]), []).append(r)
    parts = []
    for g, rs in buckets.items():
        body = "".join(
            "<tr>"
            f'<td class="id">{r["id"]}</td>'
            f'<td class="jp" lang="ja">{html.escape(r["jp"])}</td>'
            f'<td class="num">{r["bytes"]}</td>'
            f'<td class="num cap">{r["max_bytes"]}</td>'
            f'<td class="num">{r["max_ko"]}</td>'
            f'<td class="ko">{html.escape((r.get("ko") or "").strip()) or "—"}</td>'
            "</tr>" for r in rs)
        parts.append(
            f'<section class="song"><h2>{html.escape(g)}'
            f'<span class="tally">{len(rs)}줄</span></h2><div class="tw">'
            '<table><thead><tr><th>레코드</th><th>원문</th><th>원문 B</th>'
            '<th>한도 B</th><th>대략 글자</th><th>현재 역문</th></tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>")

    tsv_text = "\t".join(cols) + "\n" + "\n".join(
        "\t".join(str(r.get(c, "")) for c in cols) for r in rows)
    page = TEMPLATE.format(
        n=len(rows), jp=f"{tot_jp:,}", now=f"{tot_now:,}", mx=f"{tot_max:,}",
        songs=len(buckets), sections="\n".join(parts), tsv=html.escape(tsv_text))
    (ROOT / "records" / "karaoke_lyrics.html").write_text(page, encoding="utf-8")
    print(f"줄 {len(rows)} / 원문 {tot_jp:,} B / 현재 역문 {tot_now:,} B / 새 한도 합계 {tot_max:,} B")
    print(f"줄당 한도 평균 {tot_max/len(rows):.1f} B (한글 약 {(tot_max/len(rows)-3)/2:.0f}자)")
    print("-> records/karaoke_lyrics.tsv / .json / .html")
    return 0


TEMPLATE = """<title>가라오케 가사 대장</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@600;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
:root {{
  --ink:#191b2c; --ink-soft:#565a76; --ink-faint:#8b8fa8;
  --ground:#f6f4ef; --card:#fffefb; --rule:#e2ded3;
  --amber:#a86a12; --amber-soft:#f5e9d2; --indigo:#2b2f52;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ink:#eceaf3; --ink-soft:#a3a7c2; --ink-faint:#787c9a;
    --ground:#131529; --card:#1b1e35; --rule:#2c3050;
    --amber:#f2b657; --amber-soft:#312817; --indigo:#c8cbe6;
  }}
}}
:root[data-theme="dark"] {{
  --ink:#eceaf3; --ink-soft:#a3a7c2; --ink-faint:#787c9a;
  --ground:#131529; --card:#1b1e35; --rule:#2c3050;
  --amber:#f2b657; --amber-soft:#312817; --indigo:#c8cbe6;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Noto Sans KR", system-ui, sans-serif; font-size:15px; line-height:1.6;
}}
.wrap {{ max-width:1000px; margin:0 auto; padding:48px 24px 96px; }}
header {{ border-bottom:3px solid var(--indigo); padding-bottom:24px; }}
h1 {{
  font-family:"Noto Serif KR", serif; font-weight:700;
  font-size:clamp(28px,5vw,42px); line-height:1.15; margin:0 0 10px;
  letter-spacing:-.01em; text-wrap:balance;
}}
.sub {{ color:var(--ink-soft); margin:0; max-width:62ch; }}
.stats {{ display:flex; flex-wrap:wrap; gap:14px 34px; margin:26px 0 0; padding:0; list-style:none; }}
.stats div {{ display:flex; flex-direction:column; }}
.stats b {{
  font-family:"JetBrains Mono", monospace; font-size:23px; font-weight:600;
  font-variant-numeric:tabular-nums; color:var(--amber); line-height:1.2;
}}
.stats span {{ font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--ink-faint); }}
.note {{
  margin:34px 0 44px; padding:18px 22px; background:var(--amber-soft);
  border-left:3px solid var(--amber); border-radius:0 4px 4px 0;
}}
.note p {{ margin:0 0 10px; }}
.note p:last-child {{ margin:0; }}
.note strong {{ color:var(--amber); }}
.note code {{ font-family:"JetBrains Mono", monospace; font-size:.9em; }}
.song {{ margin:0 0 42px; }}
.song h2 {{
  font-family:"Noto Serif KR", serif; font-size:19px; font-weight:600;
  margin:0 0 10px; display:flex; align-items:baseline; gap:12px;
  position:sticky; top:0; background:var(--ground); padding:12px 0 7px; z-index:2;
  border-bottom:1px solid var(--rule);
}}
.tally {{
  font-family:"JetBrains Mono", monospace; font-size:12px; font-weight:400;
  color:var(--ink-faint); font-variant-numeric:tabular-nums; margin-left:auto;
}}
.tw {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); }}
th {{
  text-align:left; font-size:11px; letter-spacing:.07em; text-transform:uppercase;
  color:var(--ink-faint); font-weight:500; padding:9px 10px;
  border-bottom:1px solid var(--rule); white-space:nowrap;
}}
td {{ padding:7px 10px; border-bottom:1px solid var(--rule); vertical-align:top; }}
tbody tr:last-child td {{ border-bottom:none; }}
.id, .num {{ font-family:"JetBrains Mono", monospace; font-size:12px; font-variant-numeric:tabular-nums; }}
.id {{ color:var(--ink-faint); white-space:nowrap; }}
.num {{ text-align:right; width:1%; white-space:nowrap; color:var(--ink-soft); }}
.cap {{ color:var(--amber); font-weight:600; }}
.jp {{ font-size:15px; }}
.ko {{ color:var(--ink-soft); }}
details {{ margin-top:48px; border-top:1px solid var(--rule); padding-top:22px; }}
summary {{ cursor:pointer; font-weight:500; }}
summary:focus-visible {{ outline:2px solid var(--amber); outline-offset:3px; }}
pre {{
  margin:16px 0 0; padding:16px; background:var(--card); border:1px solid var(--rule);
  border-radius:4px; overflow-x:auto; font-family:"JetBrains Mono", monospace;
  font-size:12px; line-height:1.7; white-space:pre; -webkit-user-select:all; user-select:all;
}}
footer {{ margin-top:56px; color:var(--ink-faint); font-size:12px; font-family:"JetBrains Mono", monospace; }}
@media (max-width:640px) {{
  .wrap {{ padding:32px 14px 64px; }}
  td, th {{ padding:6px 7px; }}
  .jp {{ font-size:14px; }}
}}
</style>
<div class="wrap">
<header>
  <h1>가라오케 가사 대장</h1>
  <p class="sub">제4차 슈퍼로봇대전 S 가라오케 모드 주제가 가사입니다.
  <strong>한도를 화면 폭 기준으로 다시 냈습니다</strong> — 앞선 한도는 D_NAMES 공간만 보고
  계산해서 화면 밖으로 넘치는 줄이 나왔습니다. 이번 값은 실기에서 잰 것입니다.</p>
  <ul class="stats">
    <div><b>{n}</b><span>가사 줄</span></div>
    <div><b>{jp}</b><span>원문 바이트</span></div>
    <div><b>{now}</b><span>현재 역문 바이트</span></div>
    <div><b>{mx}</b><span>새 한도 합계</span></div>
    <div><b>{songs}</b><span>곡</span></div>
  </ul>
</header>

<div class="note">
  <p><strong>한도는 바이트입니다.</strong> 한글 한 글자 <strong>2바이트</strong>,
  공백과 <code>!</code> <code>?</code> <code>.</code> 같은 반각 기호는 <strong>1바이트</strong>입니다.
  표의 <em>한도 B</em> 칸이 그 줄에 쓸 수 있는 바이트이고,
  <em>대략 글자</em>는 공백을 세 개쯤 쓴다고 보고 환산한 한글 글자 수입니다.</p>
  <p><strong>한도는 줄마다 따로입니다.</strong> 화면 폭이 제약이라 다른 줄에서 아껴도
  이 줄이 길어지지는 않습니다. 26바이트 = 208픽셀이고, 가사가 그려지는 자리가
  화면 왼쪽에서 약 109픽셀부터라 그 이상은 오른쪽으로 잘려 다음 줄로 넘어갑니다.
  실제로 30바이트짜리 줄이 잘려 나왔습니다.</p>
  <p>가라오케 화면이라 <strong>노래로 부를 수 있게 음절을 맞추면</strong> 가장 좋습니다.
  직역보다 원곡 박자에 얹히는 의역을 권합니다.</p>
</div>

{sections}

<details>
  <summary>TSV 원본 — 그대로 복사해 쓸 수 있습니다</summary>
  <pre>{tsv}</pre>
</details>

<footer>records/karaoke_lyrics.tsv · records/karaoke_lyrics.json · translation/dnames_ledger.json (S17)</footer>
</div>
"""

if __name__ == "__main__":
    raise SystemExit(main())
