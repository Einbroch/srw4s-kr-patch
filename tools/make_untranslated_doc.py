#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""records/untranslated.tsv -> records/untranslated.html (읽을 수 있는 대조표).

가라오케 가사(D_NAMES S17)는 **원문을 싣지 않는다** — 개수만 적는다.
"""
from __future__ import annotations
import collections
import html
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TSV = ROOT / "records" / "untranslated.tsv"
OUT = ROOT / "records" / "untranslated.html"

NOTE = {
    "M_BANKS": "재뱅킹으로 레코드를 늘릴 수 있어 칸에 매이지 않는다. 칸 값은 원본 레코드 크기다.",
    "M_BANKB": "칸이 고정이다. 「」 안쪽만 바꾸고 남는 자리는 공백으로 메운다.",
    "D_NAMES": "풀에 다시 채워 넣는 구조라 슬롯 총량(여유 195 B) 안에서만 늘릴 수 있다.",
}


def main() -> int:
    rows = [l.split("\t") for l in TSV.read_text(encoding="utf-8").splitlines()[1:]]
    groups: dict[str, list] = collections.OrderedDict()
    for f, i, b, k, j in rows:
        groups.setdefault(f.split()[0], []).append((f, i, b, j))

    parts = []
    for name, items in groups.items():
        trs = []
        for f, i, b, j in items:
            sec = f.split(" ", 1)[1] if " " in f else ""
            trs.append(
                '<tr><td class="id">%s</td><td class="sec">%s</td>'
                '<td class="num">%s</td><td class="jp" lang="ja">%s</td></tr>'
                % (html.escape(i), html.escape(sec), html.escape(b), html.escape(j)))
        parts.append(
            '<section class="group"><div class="ghead"><h3>%s</h3>'
            '<span class="count">%d</span></div><p class="gnote">%s</p>'
            '<div class="scroll"><table><thead><tr><th>ID</th><th>구간</th>'
            '<th>칸</th><th>원문</th></tr></thead><tbody>%s</tbody></table></div></section>'
            % (name, len(items), NOTE.get(name, ""), "\n".join(trs)))

    OUT.write_text(TEMPLATE.replace("<!--ROWS-->", "\n".join(parts)), encoding="utf-8")
    print("%s (%d행)" % (OUT.relative_to(ROOT), len(rows)))
    return 0


TEMPLATE = """<title>남은 일본어 대조표</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Sans+JP:wght@400&family=Noto+Serif+KR:wght@700&display=swap">
<style>
:root{
  --ground:#F6F5F1; --surface:#FFFFFF; --line:#DFDED7; --line-soft:#ECEBE5;
  --ink:#1B211F; --muted:#5D6A65; --accent:#1E6E5B; --accent-soft:#E4EFEA; --warn:#9F5228;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#121614; --surface:#1A201D; --line:#2C3531; --line-soft:#232A27;
    --ink:#E6E9E6; --muted:#8FA098; --accent:#59BCA0; --accent-soft:#1C2A26; --warn:#D08A5F;
  }
}
:root[data-theme="dark"]{
  --ground:#121614; --surface:#1A201D; --line:#2C3531; --line-soft:#232A27;
  --ink:#E6E9E6; --muted:#8FA098; --accent:#59BCA0; --accent-soft:#1C2A26; --warn:#D08A5F;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans KR","Noto Sans JP",system-ui,sans-serif;
  font-size:16px; line-height:1.65; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:62rem; margin:0 auto; padding:4rem 1.5rem 6rem;
  display:flex; flex-direction:column; gap:3.5rem}
.prose{max-width:34rem}
h1,h2,h3{font-family:"Noto Serif KR",Georgia,serif; font-weight:700;
  text-wrap:balance; margin:0}
h1{font-size:2.3rem; line-height:1.25; letter-spacing:-.01em}
h2{font-size:1.35rem}
h3{font-size:1.05rem}
p{margin:0}
.eyebrow{font-family:"IBM Plex Mono",monospace; font-size:.72rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--accent); margin-bottom:.9rem}
.lede{color:var(--muted); margin-top:1rem}
header{display:flex; flex-direction:column; gap:2rem;
  border-bottom:1px solid var(--line); padding-bottom:2.5rem}
.tally{display:flex; flex-wrap:wrap; gap:2.5rem}
.tally div{display:flex; flex-direction:column; gap:.15rem}
.tally b{font-family:"Noto Serif KR",Georgia,serif; font-size:2.6rem; line-height:1;
  font-variant-numeric:tabular-nums; color:var(--accent)}
.tally b.plain{color:var(--ink)}
.tally span{font-size:.82rem; color:var(--muted)}
section{display:flex; flex-direction:column; gap:1rem}
.scroll{overflow-x:auto; border:1px solid var(--line); border-radius:2px;
  background:var(--surface)}
table{width:100%; border-collapse:collapse; font-size:.87rem}
th,td{text-align:left; padding:.55rem .8rem; border-bottom:1px solid var(--line-soft);
  vertical-align:top}
thead th{font-size:.7rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--muted); font-weight:500; background:var(--ground)}
tbody tr:last-child td{border-bottom:0}
.id,.sec,.num{font-family:"IBM Plex Mono",monospace; font-size:.8rem; white-space:nowrap}
.num{text-align:right; font-variant-numeric:tabular-nums; color:var(--muted)}
.sec{color:var(--muted)}
.jp{font-family:"Noto Sans JP",sans-serif; min-width:20rem}
.group{gap:.6rem}
.ghead{display:flex; align-items:baseline; gap:.7rem}
.count{font-family:"IBM Plex Mono",monospace; font-size:.78rem; color:var(--accent);
  background:var(--accent-soft); padding:.1rem .5rem; border-radius:2px}
.gnote{font-size:.85rem; color:var(--muted); max-width:36rem}
.status{display:grid; border:1px solid var(--line); border-radius:2px;
  background:var(--surface)}
.status .row{display:grid;
  grid-template-columns:minmax(9rem,1.4fr) repeat(3,minmax(4.5rem,.6fr));
  gap:1rem; padding:.7rem .9rem; border-bottom:1px solid var(--line-soft);
  align-items:center}
.status .row:last-child{border-bottom:0}
.status .row.head{font-size:.7rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--muted); background:var(--ground)}
.status .n{font-family:"IBM Plex Mono",monospace; font-size:.85rem;
  font-variant-numeric:tabular-nums; text-align:right}
.status .who{font-size:.88rem}
.status .who small{display:block; color:var(--muted); font-size:.76rem}
.left{color:var(--warn); font-weight:500}
.done{color:var(--accent)}
.notes{display:grid; gap:1.6rem; grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))}
.note{border-left:2px solid var(--line); padding-left:1rem;
  display:flex; flex-direction:column; gap:.35rem}
.note h3{font-size:.95rem}
.note p{font-size:.87rem; color:var(--muted)}
.note b{color:var(--ink); font-weight:600}
.rule{border-left-color:var(--accent)}
code{font-family:"IBM Plex Mono",monospace; font-size:.85em;
  background:var(--accent-soft); padding:.08em .35em; border-radius:2px}
footer{border-top:1px solid var(--line); padding-top:1.5rem;
  font-size:.82rem; color:var(--muted); max-width:36rem}
</style>

<div class="wrap">
<header>
  <div class="prose">
    <div class="eyebrow">제4차 슈퍼로봇대전 S · 한글패치</div>
    <h1>남은 일본어 대조표</h1>
    <p class="lede">디스크 안 네 곳의 텍스트를 전수 조사해, 아직 일본어로 남아 있는 것을
      추려냈습니다. 손댈 수 있는 것과 손대면 안 되는 것을 갈라 두었습니다.</p>
  </div>
  <div class="tally">
    <div><b>47</b><span>작업 대상</span></div>
    <div><b class="plain">466</b><span>데이터 · 조각 (제외)</span></div>
    <div><b class="plain">111</b><span>가라오케 가사 (제외)</span></div>
  </div>
</header>

<section>
  <h2>어디에 얼마나 남았나</h2>
  <div class="status">
    <div class="row head"><span>구간</span><span class="n">전체</span>
      <span class="n">역문</span><span class="n">남은 것</span></div>
    <div class="row"><span class="who">M_BANKS<small>시나리오 대사</small></span>
      <span class="n">9,070</span><span class="n done">8,939</span>
      <span class="n left">131</span></div>
    <div class="row"><span class="who">M_BANKB 본 원장<small>전투 컷인</small></span>
      <span class="n">232</span><span class="n done">214</span>
      <span class="n left">18</span></div>
    <div class="row"><span class="who">M_BANKB 표 밖<small>파일럿 전투 대사</small></span>
      <span class="n">1,686</span><span class="n done">1,686</span>
      <span class="n done">0</span></div>
    <div class="row"><span class="who">D_NAMES S04–S16<small>이름 · 용어</small></span>
      <span class="n">1,637</span><span class="n done">1,630</span>
      <span class="n left">7</span></div>
    <div class="row"><span class="who">D_NAMES S00–S02<small>스크립트 조각</small></span>
      <span class="n">443</span><span class="n done">260</span>
      <span class="n left">160</span></div>
    <div class="row"><span class="who">D_NAMES S17<small>가라오케 가사</small></span>
      <span class="n">134</span><span class="n done">7</span>
      <span class="n left">111</span></div>
  </div>
  <p class="gnote">남은 것 가운데 실제로 번역할 문장은 <b>47개</b>입니다. 나머지는 뜻 없는
    조각이거나, 구조상 손대면 다른 대사가 깨지거나, 가사입니다.</p>
</section>

<section>
  <h2>작업 대상 47개</h2>
<!--ROWS-->
</section>

<section>
  <h2>제외한 것과 이유</h2>
  <div class="notes">
    <div class="note">
      <h3>데이터 · 조각 466개</h3>
      <p>글자로 보이지만 문장이 아닙니다. 애니메이션 스크립트나 u16 표가 글리프로
        해석된 것이라, 번역하면 표가 깨집니다. <b>D_NAMES S00–S02</b>가 대부분입니다.</p>
    </div>
    <div class="note">
      <h3>별칭이 얽힌 레코드</h3>
      <p>다른 표가 레코드 <b>안쪽</b>을 가리키고 있어, 번역하면 엮인 대사가 함께
        깨집니다. 검증 게이트가 잡아내며 지금은 원문 그대로 둡니다.</p>
    </div>
    <div class="note">
      <h3>가라오케 가사 111줄</h3>
      <p>주제가 가사입니다. 이 문서에는 원문을 싣지 않았습니다. 각 줄이 통째로 하나의
        span이라 고유명사만 바꾸는 것도 되지 않습니다.</p>
    </div>
  </div>
</section>

<section>
  <h2>번역할 때 지켜야 할 것</h2>
  <div class="notes">
    <div class="note rule">
      <h3>칸 바이트</h3>
      <p>한글·한자는 <b>2바이트</b>, 반각 가나와 <code>!</code> <code>?</code>
        <code>,</code> 공백은 <b>1바이트</b>, 줄바꿈 <code>{N}</code>과 종단이 각 1바이트.
        한글이 길어지기 쉬우니 칸을 먼저 보고 씁니다.</p>
    </div>
    <div class="note rule">
      <h3>제어 토큰은 그대로</h3>
      <p><code>{C:0F}</code> <code>{B:xxxx}</code> 같은 토큰은 개수와 순서를 원문과
        똑같이 유지해야 합니다. 하나라도 빠지면 게임이 멈춥니다.</p>
    </div>
    <div class="note rule">
      <h3>「」 안쪽만</h3>
      <p>앞머리에 <code>{A}</code>가 있는 레코드는 바깥이 표 데이터입니다. 「」 안쪽만
        바꾸고 바깥은 원문 바이트 그대로 둡니다.</p>
    </div>
    <div class="note rule">
      <h3>폰트 슬롯</h3>
      <p>16×16 슬롯 1,536칸 중 <b>1,242자</b>를 쓰고 있습니다. 새 음절은 약
        <b>260자</b>까지 더 넣을 수 있고, 그 이상은 저빈도 한자 슬롯을 덮어야 합니다.</p>
    </div>
  </div>
</section>

<footer>
  기계가 읽을 수 있는 같은 목록은 <code>records/untranslated.tsv</code>에 있습니다 —
  파일 · ID · 칸(byte) · 성격 · 원문 다섯 열입니다.
</footer>
</div>
"""

if __name__ == "__main__":
    raise SystemExit(main())
