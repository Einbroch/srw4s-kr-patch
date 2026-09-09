#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SRW4S 한글화 에디터 — 게임을 켜지 않고 검수한다.

왜 만드나
  화면에 뜬 문자열 하나를 고치려면 매번 (1) 어느 레코드인지 원장 넷을 뒤지고
  (2) 예산에 맞는지 바이트·픽셀을 재고 (3) 게임을 켜서 눈으로 확인했다.
  게다가 16x16 비트맵은 **육안 판독이 믿을 수 없다** — `이름`을 `0틑`로 오독해
  멀쩡한 빌드를 세 번 "깨졌다"고 잘못 진단한 적이 있다(render_expected.py 머리말).

무엇을 하나
  * 검색      원장 넷(M_BANKS / M_BANKB / 표 밖 / D_NAMES)을 한 번에 훑는다
  * 검사      바이트 예산, 줄당 296px, 쪽당 3줄, 폰트에 없는 글자를 즉시 알려 준다
  * 미리보기  **패치된 실제 글꼴**로 대사창을 그린다 (게임을 안 켜도 된다)
  * 사본      같은 문자열이 어디에 또 있는지 보여 준다 — 한 벌만 고쳐 반쪽만
              바뀌는 사고가 이 프로젝트에서 되풀이됐다
  * 저장      원장 JSON 에 되쓴다 (빌드·배포는 기존 CLI 그대로)

실행
  python tools/editor.py     ->  http://127.0.0.1:8765
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mb_codec import build_encoder, encode                  # noqa: E402
import mb_layout                                            # noqa: E402
from mb_layout import atoms, atom_px                        # noqa: E402
from span_classify import charmap                           # noqa: E402

STAY = ROOT / "build" / "STAYDAT_ko.BIN"
LOW, MID = 0x36838, 0x37838
PORT = 8765

LEDGERS = {
    "M_BANKS": ROOT / "translation" / "mbanks_ledger.json",
    "M_BANKB": ROOT / "translation" / "mbankb_ledger.json",
    "표밖":     ROOT / "translation" / "mbankb_hidden_ledger.json",
}
DNAMES = ROOT / "translation" / "dnames_ledger.json"

ENC = build_encoder()
_docs: dict = {}
_dn = None
_font = None
_full: set = set()


def reloc_set():
    """재배치되는 M_BANKB 레코드 — **일본어 원문**으로 키를 잡는다."""
    global _full
    if _full:
        return _full
    sys.path.insert(0, str(ROOT / "translation"))
    try:
        import mbankb_relocate_ko as M
        _full = set(M.FULL)
    except Exception:
        _full = set()
    return _full


def caps(file, rec, sp=None):
    """(바이트 상한, 줄 폭, 줄 수). 상한 None = 빌드가 재배치하니 자유.

    바이트 규칙은 빌드가 실제로 하는 일을 그대로 따른다:
      * M_BANKS  — mb_rebank4 가 뱅크를 통째로 다시 싸므로 레코드별 상한이 없다
      * M_BANKB  — 제자리에 쓴다. 단 mbankb_relocate_ko.FULL 에 있는 원문은 옮겨진다
      * D_NAMES  — reinsert_dnames 가 구역 **풀**에 다시 담는다. 스팬별 상한이 아니라
                   풀 용량이 제약이라 여기서는 상한을 걸지 않는다. 조판도 마찬가지 —
                   이름은 대사창이 아니라 메뉴·상태창에 그려져 296px 규약이 안 맞는다.
    (end-offset 을 무조건 상한으로 보면 M_BANKS 8,817건, D_NAMES 2,000건 이상이
     멀쩡한데도 초과로 잡힌다. None = 확인된 한도가 없다는 뜻이고, 재지 않는다.)
    """
    if sp is not None:
        return None, None, None
    if True:
        jp, owners = rec.get("jp") or "", rec.get("owners") or ()
        cap = None if file == "M_BANKS" else (
            None if jp in reloc_set() else rec["end"] - rec["offset"])
    px, lines = mb_layout.budget(jp, ENC, owners)
    return cap, px, lines


def load():
    global _dn
    for name, path in LEDGERS.items():
        if path.exists():
            _docs[name] = json.loads(path.read_text(encoding="utf-8"))
    if DNAMES.exists():
        _dn = json.loads(DNAMES.read_text(encoding="utf-8"))


def dn_records():
    if not _dn:
        return []
    return _dn["records"] if isinstance(_dn, dict) else _dn


def font_enc():
    """render_expected.py 와 같은 규칙 — 문자표 + 한글 할당."""
    global _font
    if _font is not None:
        return _font
    enc = {}
    for gid, ch in sorted(charmap().items()):
        if ch and ch not in enc:
            enc[ch] = gid
    enc[" "] = 0x000
    p = ROOT / "translation" / "glyph_alloc.json"
    if p.exists():
        for ch, h in json.loads(p.read_text(encoding="utf-8"))["hangul"].items():
            enc[ch] = int(h, 16)
    _font = enc
    return enc


# ---------------- 검사 ----------------

def check(markup, cap=None, px_cap=None, line_cap=None):
    """cap/px_cap/line_cap 이 None 이면 그 한도는 **확인된 바 없다** — 재지 않는다.
    근거 없는 한도로 경고를 띄우면 진짜 문제가 묻힌다."""
    out = {"errors": [], "warn": [], "lines": [], "bytes": None,
           "cap": cap, "px_cap": px_cap, "line_cap": line_cap}
    plain = re.sub(r"\{[^}]*\}", "", markup)
    missing = sorted({c for c in plain if c not in ENC})
    if missing:
        out["errors"].append("폰트에 없는 글자: " + " ".join(missing))
        return out
    try:
        used = len(encode(markup, ENC))
    except KeyError as e:
        out["errors"].append("인코딩 실패: %s" % e)
        return out
    out["bytes"] = used
    if cap is not None:
        if used > cap:
            out["errors"].append("칸을 넘음: %d B > %d B (%d B 넘침) — 재배치 목록에 "
                                 "넣거나 줄여야 한다" % (used, cap, used - cap))
        elif used < cap:
            out["warn"].append("여유 %d B" % (cap - used))
    for pi, page in enumerate(markup.split("{P}")):
        rows = page.split("{N}")
        if line_cap and len(rows) > line_cap:
            out["errors"].append("%d쪽이 %d줄 — 한 쪽은 %d줄까지"
                                 % (pi + 1, len(rows), line_cap))
        for li, line in enumerate(rows):
            # 꼬리 공백은 빼고 잰다. 레코드를 칸에 맞추려 넣은 패딩이라 아무것도
            # 그리지 않는데, 그대로 세면 멀쩡한 대사가 조판 초과로 잡힌다
            # (BB:076F3 이 56px 넘침으로 잘못 걸렸다). 바이트에는 그대로 센다.
            w = sum(atom_px(a, ENC) for a in atoms(line.rstrip(" ")))
            out["lines"].append({"page": pi, "line": li, "px": w})
            if px_cap and w > px_cap:
                out["errors"].append("%d쪽 %d줄이 %dpx — 한도 %dpx (%dpx 넘침)"
                                     % (pi + 1, li + 1, w, px_cap, w - px_cap))
    return out


# ---------------- 미리보기 ----------------

def render_png(markup, scale=3, cap=None):
    from PIL import Image
    if not STAY.exists():
        raise FileNotFoundError("STAYDAT_ko.BIN 이 없다 — 먼저 빌드하세요")
    stay = STAY.read_bytes()
    enc = font_enc()
    rows = []
    for page in markup.split("{P}"):
        rows += page.split("{N}")
    rows = rows[:12] or [""]
    # 한도보다 넓게 그리고 한도 자리에 세로선을 긋는다 — 넘친 만큼이 눈에 보인다.
    cap = cap or mb_layout.LINE_PX
    W, H = cap + 128, 16 * len(rows)
    img = Image.new("RGB", (W, H), (0, 0, 0))
    px = img.load()
    for y in range(H):
        px[cap, y] = (200, 60, 60)
    for y in range(H):
        for x in range(cap + 1, W):
            if (x + y) % 8 == 0:
                px[x, y] = (48, 20, 20)
    for ri, line in enumerate(rows):
        x = 0
        for a in atoms(line):
            if a.startswith("{"):
                continue
            gid = enc.get(a)
            if gid is None:
                x += 16
                continue
            if gid < 0x100:
                off, w, n = LOW + gid * 16, 8, 16
            else:
                off, w, n = MID + (gid - 0x100) * 32, 16, 32
            # 글리프는 **열 단위**다: 0..15 = 왼쪽 8px, 16..31 = 오른쪽 8px.
            # 줄당 2바이트로 읽으면 글자가 위아래로 쪼개진다(render_expected.py 와 동일).
            cell = stay[off:off + n]
            for y in range(16):
                for k in range(8):
                    if y < len(cell) and (cell[y] >> (7 - k)) & 1:
                        xx = x + k
                        if 0 <= xx < W:
                            px[xx, ri * 16 + y] = (255, 255, 255) if xx < cap                                 else (255, 120, 120)
                    if w == 16 and 16 + y < len(cell) and (cell[16 + y] >> (7 - k)) & 1:
                        xx = x + 8 + k
                        if 0 <= xx < W:
                            px[xx, ri * 16 + y] = (255, 255, 255) if xx < cap                                 else (255, 120, 120)
            x += w
            if x >= W:
                break
    img = img.resize((W * scale, H * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------------- 검색 ----------------

def _rank(q, jp, ko):
    """짧고 정확히 맞는 것부터. 원장 순서대로 자르면 뒤에 오는 D_NAMES 가
    앞 원장 히트에 밀려 아예 안 보인다 — 이름·무기를 못 찾던 원인."""
    best = 9
    for t in (ko, jp):
        if not t or q not in t:
            continue
        best = min(best, 0 if t == q else 1 if t.startswith(q) else 2)
    return (best, len(ko or jp or ""))


def search(q, limit=60):
    if not q:
        return []
    hits = []
    for name, doc in _docs.items():
        for r in doc["records"]:
            jp, ko = r.get("jp") or "", r.get("ko") or ""
            if q in jp or q in ko:
                cap, px, ln = caps(name, r)
                hits.append({"file": name, "id": r["id"], "cap": cap,
                             "px_cap": px, "line_cap": ln, "jp": jp, "ko": ko,
                             "_k": _rank(q, jp, ko)})
    for r in dn_records():
        for i, sp in enumerate(r.get("spans") or []):
            jp, ko = sp.get("jp") or "", sp.get("ko") or ""
            if q in jp or q in ko:
                cap, px, ln = caps("D_NAMES", r, sp)
                hits.append({"file": "D_NAMES", "id": "%s#%d" % (r["id"], i),
                             "cap": cap, "px_cap": px, "line_cap": ln,
                             "jp": jp, "ko": ko, "_k": _rank(q, jp, ko)})
    hits.sort(key=lambda h: h["_k"])
    for h in hits:
        del h["_k"]
    return hits[:limit]


KANA2 = re.compile(r"[ぁ-ゟ゠-ヺー-ヿｦ-ﾝ]{2,}")
HANGUL = re.compile(r"[가-힣]")


def _quoted(t):
    """대사가 사는 「」 안쪽만. {C:0F} 뒤 두 글자는 화자 이름 바이트이지 본문이 아니다."""
    t = re.sub(r"\{C:0F\}..", "", t)
    t = re.sub(r"\{[^}]*\}", "", t)
    return " ".join(re.findall(r"「([^」]*)」", t))


def issues(kind, limit=300):
    """남은 문제를 갈래별로 모은다 — 검색어를 짐작하지 않아도 되게.

    `live: False` 레코드는 뺀다. 그건 화면에 안 뜨는 u16 표인데 글자로 보인다
    (M_BANKS 9,070개 중 7,484개). 넣으면 미번역이 98건으로 부풀어 못 쓴다.
    """
    out = []
    for name, doc in _docs.items():
        for r in doc["records"]:
            if r.get("live") is False:
                continue
            jp, ko = r.get("jp") or "", r.get("ko") or ""
            cap, px, ln = caps(name, r)
            hit = None
            if kind == "untranslated":
                hit = "역문 없음" if jp and not ko else None
            elif not ko:
                pass
            elif kind == "partial":
                if HANGUL.search(ko) and KANA2.search(_quoted(ko)):
                    hit = "대사 안에 일본어가 남았다"
            else:
                for e in check(ko, cap, px, ln)["errors"]:
                    over = "칸을 넘음" in e
                    if (kind == "cap") == over:
                        hit = e
                        break
            if hit:
                out.append({"file": name, "id": r["id"], "cap": cap, "px_cap": px,
                            "line_cap": ln, "jp": jp, "ko": ko, "why": hit})
    # 한글이 있는 것 = 사람이 손댈 대사. 한글이 하나도 없으면 전투 이름 점프표
    # 같은 데이터라 목록 뒤로 보낸다. 그 다음은 짧은 것부터 — 표 노이즈가 섞인
    # 수천 자짜리가 맨 위에 오면 목록을 못 읽는다.
    # D_NAMES 도 반드시 훑는다 — **고정 칸이 있는 유일한 곳**이라 넘치면 조용히
    # 잘린다([[name-field-byte-cap]]). 처음엔 원장 셋만 봐서 칸 넘침이 0건으로
    # 나왔는데, 정작 칸 제한은 여기에만 있었다.
    for r in dn_records():
        for i, sp in enumerate(r.get("spans") or []):
            jp, ko = sp.get("jp") or "", sp.get("ko") or ""
            cap, px, ln = caps("D_NAMES", r, sp)
            hit = None
            if kind == "untranslated":
                # D_NAMES 미번역 541건 중 521건이 `竜+`·`SS`·`枚チ` 같은 표 조각이다
                # (글리프로 디코드된 칸이지 글이 아니다). 일본어 글처럼 보이는 것만 남긴다.
                hit = ("역문 없음" if jp and not ko
                       and len(jp) >= 3 and KANA2.search(jp) else None)
            elif not ko:
                pass
            elif kind == "partial":
                if HANGUL.search(ko) and KANA2.search(ko):
                    hit = "이름에 일본어가 남았다"
            else:
                for e in check(ko, cap, px, ln)["errors"]:
                    if (kind == "cap") == ("칸을 넘음" in e):
                        hit = e
                        break
            if hit:
                out.append({"file": "D_NAMES", "id": "%s#%d" % (r["id"], i),
                            "cap": cap, "px_cap": px, "line_cap": ln,
                            "jp": jp, "ko": ko, "why": hit})
    out.sort(key=lambda h: (not HANGUL.search(h["ko"] or ""), len(h["ko"] or h["jp"])))
    return out[:limit]


def copies(text):
    out = []
    if not text:
        return out
    for name, doc in _docs.items():
        for r in doc["records"]:
            if text in (r.get("ko") or "") or text in (r.get("jp") or ""):
                out.append({"file": name, "id": r["id"], "cap": caps(name, r)[0],
                            "ko": r.get("ko") or ""})
    for r in dn_records():
        for i, sp in enumerate(r.get("spans") or []):
            if text in (sp.get("ko") or "") or text in (sp.get("jp") or ""):
                out.append({"file": "D_NAMES", "id": "%s#%d" % (r["id"], i),
                            "cap": sp["end"] - sp["start"], "ko": sp.get("ko") or ""})
    return out


_backed = set()


def _backup(path):
    """서버를 켠 뒤 그 원장을 처음 건드릴 때 한 번만 사본을 남긴다.

    원장은 빌드의 정본이다. 프로젝트 관례(`*.pre-*.json`)를 그대로 따른다.
    """
    if path in _backed:
        return
    bak = path.with_suffix(".pre-editor.json")
    if not bak.exists():
        bak.write_bytes(path.read_bytes())
    _backed.add(path)


def save(file, rid, ko):
    if file == "D_NAMES":
        base, _, idx = rid.partition("#")
        for r in dn_records():
            if r["id"] == base:
                _backup(DNAMES)
                r["spans"][int(idx)]["ko"] = ko
                DNAMES.write_text(json.dumps(_dn, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
                return True
        return False
    doc = _docs.get(file)
    if not doc:
        return False
    for r in doc["records"]:
        if r["id"] == rid:
            _backup(LEDGERS[file])
            r["ko"] = ko
            LEDGERS[file].write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
            return True
    return False


# ---------------- 화면 ----------------

PAGE = """<!doctype html><meta charset="utf-8"><title>SRW4S 한글화 에디터</title>
<style>
:root{--bg:#141a17;--fg:#dfe8e2;--dim:#7f8f86;--line:#2b3a33;--ok:#7fd18a;--bad:#ef6b6b;--warn:#e2c063}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 "Malgun Gothic",system-ui,sans-serif}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center}
header strong{white-space:nowrap}nav{display:flex;gap:6px}nav button{padding:6px 11px;font-size:12.5px;white-space:nowrap}
input,textarea{background:#0e1512;color:var(--fg);border:1px solid var(--line);border-radius:6px;
 padding:8px 10px;font:inherit;width:100%}
textarea{font-family:Consolas,monospace;min-height:96px;resize:vertical}
main{display:grid;grid-template-columns:minmax(320px,40%) 1fr;height:calc(100vh - 54px)}
#list{overflow:auto;border-right:1px solid var(--line)}
#pane{overflow:auto;padding:16px 20px}
.row{padding:9px 14px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover{background:#1b2420}.row.sel{background:#20302a}
.meta,.jp{color:var(--dim);font-size:12.5px}
.tag{display:inline-block;padding:1px 8px;border:1px solid var(--line);border-radius:99px;
 font-size:11px;color:var(--dim);margin-right:6px}
.err{color:var(--bad)}.warn{color:var(--warn)}.ok{color:var(--ok)}
.bar{height:6px;background:#0e1512;border-radius:99px;overflow:hidden;margin:6px 0}
.bar i{display:block;height:100%;background:var(--ok)}.bar i.over{background:var(--bad)}
h3{margin:20px 0 8px;font-size:12px;color:var(--dim);letter-spacing:.08em;text-transform:uppercase}
button{background:#22302a;color:var(--fg);border:1px solid var(--line);border-radius:6px;
 padding:8px 15px;font:inherit;cursor:pointer}button:hover{background:#2b3d35}
img{image-rendering:pixelated;background:#0b3a1e;border:2px solid #4a7a5e;border-radius:4px;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:400}
</style>
<header><strong>SRW4S 한글화 에디터</strong>
<input id="q" placeholder="일본어 또는 한국어로 검색   예: 브레스트 / 南無三 / 아뿔싸" autofocus>
<nav><button onclick="iss('untranslated')">미번역</button>
<button onclick="iss('partial')">덜 번역</button>
<button onclick="iss('layout')">조판 넘침</button>
<button onclick="iss('cap')">칸 넘침</button>
<button onclick="j('/api/reload').then(function(r){$('#q').placeholder=
 '원장 다시 읽음 — 항목 '+r.n+'개'})">다시 읽기</button></nav></header>
<main><div id="list"></div><div id="pane"><p class="meta">왼쪽에서 레코드를 고르세요.</p></div></main>
<script>
var cur=null,t=null;
function $(s){return document.querySelector(s)}
function cut(s){s=s||'';return s.length>110?s.slice(0,110)+' …':s}
function esc(s){return (s||"").replace(/[<>&]/g,function(c){
 return {"<":"&lt;",">":"&gt;","&":"&amp;"}[c]})}
function j(u,o){return fetch(u,o).then(function(r){return r.json()})}
$("#q").oninput=function(e){var v=e.target.value;clearTimeout(t);
 t=setTimeout(function(){run(v)},220)};
function iss(kind){
 $("#q").value="";
 j("/api/issues?kind="+kind).then(function(rows){paint(rows,kind)})}
function run(q){
 if(!q){$("#list").innerHTML="";return}
 j("/api/search?q="+encodeURIComponent(q)).then(function(rows){paint(rows,null)})}
function paint(rows,kind){
 if(!rows.length){$("#list").innerHTML='<div class="row meta">해당 없음 — 남은 문제가 '+
  '없습니다</div>';return}
  $("#list").innerHTML=rows.map(function(r,i){
   return '<div class="row" data-i="'+i+'"><div><span class="tag">'+r.file+
    '</span><span class="tag">'+r.id+'</span>'+
    (r.cap!=null?'<span class="tag">칸 '+r.cap+' B</span>':
     '<span class="tag">재배치</span>')+'</div><div>'+
    (esc(cut(r.ko))||'<span class="meta">(역문 없음)</span>')+'</div><div class="jp">'+
    esc(cut(r.jp))+'</div>'+(r.why?'<div class="warn">'+esc(r.why)+'</div>':'')+
    '</div>'}).join("");
  var els=document.querySelectorAll(".row");
  for(var k=0;k<els.length;k++)(function(el){el.onclick=function(){
   for(var m=0;m<els.length;m++)els[m].classList.remove("sel");
   el.classList.add("sel");open(rows[+el.dataset.i])}})(els[k]);}
function open(r){
 cur=r;
 $("#pane").innerHTML='<div><span class="tag">'+r.file+'</span><span class="tag">'+r.id+
  '</span>'+(r.cap!=null?'<span class="tag">칸 '+r.cap+' B</span>':
  '<span class="tag">재배치 — 바이트 자유</span>')+
  '<span class="tag">'+r.px_cap+'px x '+r.line_cap+'줄</span>'+
  (r.why?'<span class="tag" style="color:#e2c063">'+esc(r.why)+'</span>':'')+
  '</div><h3>원문</h3><div class="jp">'+esc(r.jp)+
  '</div><h3>역문</h3><textarea id="ko">'+esc(r.ko)+'</textarea><div id="chk"></div>'+
  '<h3>미리보기 — 패치된 실제 글꼴</h3><img id="pv" alt="">'+
  '<h3>같은 문자열이 있는 곳</h3><div id="cp"></div>'+
  '<p style="margin-top:18px"><button onclick="doSave()">원장에 저장</button> '+
  '<span id="msg" class="meta"></span></p>';
 $("#ko").oninput=function(){clearTimeout(t);t=setTimeout(check,200)};
 check()}
function check(){
 var ko=$("#ko").value;
 j("/api/check",{method:"POST",body:JSON.stringify({ko:ko,cap:cur.cap,
   px_cap:cur.px_cap,line_cap:cur.line_cap})})
 .then(function(c){
  var h="";
  if(c.cap!=null&&c.bytes!=null){
   var pct=Math.min(100,c.bytes/c.cap*100),over=c.bytes>c.cap;
   h+='<div class="bar"><i class="'+(over?"over":"")+'" style="width:'+pct+'%"></i></div>'+
      '<div class="meta">'+c.bytes+" / "+c.cap+" B</div>"}
  else if(c.bytes!=null)h+='<div class="meta">'+c.bytes+" B — 재배치되므로 상한 없음</div>";
  (c.lines||[]).forEach(function(l){h+='<div class="meta">'+(l.page+1)+"쪽 "+(l.line+1)+
   '줄 — <span class="'+(l.px>c.px_cap?"err":"ok")+'">'+l.px+"px</span> / "+
   c.px_cap+"px</div>"});
  (c.errors||[]).forEach(function(m){h+='<div class="err">✗ '+esc(m)+"</div>"});
  (c.warn||[]).forEach(function(m){h+='<div class="warn">· '+esc(m)+"</div>"});
  if(!(c.errors||[]).length)h+='<div class="ok">✓ 예산·조판 이상 없음</div>';
  $("#chk").innerHTML=h;
  $("#pv").src="/api/preview.png?scale=2&cap="+cur.px_cap+"&text="+
   encodeURIComponent(ko)+"&_="+Date.now();
  var m=ko.match(/「([^」]*)」/),q=m?m[1]:"";
  j("/api/copies?text="+encodeURIComponent(q)).then(function(cp){
   $("#cp").innerHTML=cp.length<2?'<span class="meta">다른 사본 없음</span>':
    '<table><tr><th>파일</th><th>레코드</th><th>예산</th><th>역문</th></tr>'+
    cp.map(function(x){return "<tr><td>"+x.file+"</td><td>"+x.id+"</td><td>"+
     (x.cap==null?"재배치":x.cap+" B")+"</td><td>"+esc(x.ko)+"</td></tr>"}).join("")+
    "</table>"})})}
function doSave(){
 j("/api/save",{method:"POST",body:JSON.stringify(
  {file:cur.file,id:cur.id,ko:$("#ko").value})}).then(function(r){
  $("#msg").textContent=r.ok?"저장했습니다 — 빌드는 기존 CLI 로":"저장 실패";
  cur.ko=$("#ko").value})}
</script>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        if u.path == "/api/search":
            return self._json(search(qs.get("q", [""])[0]))
        if u.path == "/api/reload":
            # batch.py 같은 CLI 로 원장을 고친 뒤 서버를 다시 안 켜도 되게
            _docs.clear()
            load()
            n = sum(len(d["records"]) for d in _docs.values())
            n += sum(len(r.get("spans") or []) for r in dn_records())
            return self._json({"n": n})
        if u.path == "/api/issues":
            return self._json(issues(qs.get("kind", ["untranslated"])[0]))
        if u.path == "/api/copies":
            return self._json(copies(qs.get("text", [""])[0]))
        if u.path == "/api/preview.png":
            try:
                png = render_png(qs.get("text", [""])[0],
                                 int(qs.get("scale", ["3"])[0]),
                                 int(qs.get("cap", ["0"])[0]) or None)
            except Exception:
                self.send_response(204)
                self.end_headers()
                return
            return self._send(200, "image/png", png)
        self._send(404, "text/plain; charset=utf-8", "없음".encode("utf-8"))

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/check":
            return self._json(check(body.get("ko", ""), body.get("cap"),
                                    body.get("px_cap"), body.get("line_cap")))
        if u.path == "/api/save":
            return self._json({"ok": save(body.get("file", ""), body.get("id", ""),
                                          body.get("ko", ""))})
        self._json({})


if __name__ == "__main__":
    load()
    n = sum(len(d["records"]) for d in _docs.values())
    n += sum(len(r.get("spans") or []) for r in dn_records())
    print("원장 %d개 / 항목 %s개 적재" % (len(_docs) + 1, format(n, ",")))
    print("http://127.0.0.1:%d   (Ctrl+C 로 종료)" % PORT)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
