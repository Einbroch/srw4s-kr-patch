#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D_NAMES 재삽입 빌드.

레이아웃은 원본 규율을 그대로 지킨다:
  [18개 u32 헤더][S 테이블][S 문자열 풀][다음 S 테이블][그 풀]...
각 소유 섹션 테이블의 **0번 엔트리 포인터 = 그 테이블의 끝**이어야 한다
(`analyze_structures.dnames_sections`가 이 값으로 엔트리 수를 되찾는다). 그래서 0번 레코드는
공유하지 않고 항상 자기 섹션 풀 맨 앞에 새로 넣는다.

별칭 섹션(S05/S09/S10/S16)은 소유 테이블의 부분 구간이므로 헤더 값만 같은 상대 위치로 옮긴다.
"""
from __future__ import annotations
import os
import json, struct, sys, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_structures import dnames_sections     # noqa: E402
from text_codec import glyph_bytes, parse_record     # noqa: E402
from span_classify import charmap                   # noqa: E402
from pack_dnames import Pool                        # noqa: E402
from align_fit import sig, phase_fix                # noqa: E402

ANCHORS = {0xF8, 0xF9, 0xFB, 0xFC, 0xFD}   # 위상 민감 앵커

# 스크립트 VM이 레코드 종단을 넘어 이어 읽는 것으로 보이는 섹션 — **원본 물리 순서를 지킨다**.
# 재배치했더니 실기에서 panic 트랩에 걸렸고, 폰트만 패치한 빌드는 멀쩡했다(이분 탐색 확인).
# 나머지 섹션(이름·무장·지형 등)은 포인터표로만 접근하므로 재배치·공유해도 안전하다.
ORDERED_SECTIONS = {0, 1, 2}
# 이분 탐색용: SRW4S_ORDERED="0,1,2,13" 처럼 주면 그 집합으로 대체한다.
if os.environ.get("SRW4S_ORDERED"):
    ORDERED_SECTIONS = {int(x) for x in os.environ["SRW4S_ORDERED"].split(",") if x.strip()}
WIDE: list = []                            # 원문보다 넓어 못 맞춘 런 (실기 확인 대상)

SRC = ROOT / "extract" / "DAT" / "D_NAMES.BIN"
SLOT = 55296            # 다음 상주 blob(D_UNIT 0x80077000)까지의 거리 — 넘으면 그 blob을 덮는다
# D_DEDMES(원래 0x80076800)를 0x8007D000 으로 옮겨 2 KB 를 넘겨받았다 (relocate_dedmes.py)


def build_encoder() -> dict[str, int]:
    cm = charmap()
    enc: dict[str, int] = {}
    for gid, ch in sorted(cm.items()):
        if ch and ch not in enc:
            enc[ch] = gid
    enc[" "] = 0x000            # 빈 8x16 = 유일한 반각 공백 (HANDOFF 2026-08-23)
    enc["\u3000"] = 0x3FF       # 전각 공백
    alloc = json.loads((ROOT / "translation" / "glyph_alloc.json").read_text(encoding="utf-8"))
    for ch, hexid in alloc["hangul"].items():
        enc[ch] = int(hexid, 16)
    return enc


def main() -> int:
    data = SRC.read_bytes()
    secs = dnames_sections(data)
    live = [s for s in secs if s["start"] is not None]
    alias = {s["section"]: next(o["section"] for o in live
                                if o is not s and o["start"] < s["start"] < o["table_end"])
             for s in live
             if any(o is not s and o["start"] < s["start"] < o["table_end"] for o in live)}
    own = [s for s in live if s["section"] not in alias]
    own.sort(key=lambda s: s["start"])

    L = json.loads((ROOT / "translation" / "dnames_ledger.json").read_text(encoding="utf-8"))
    led = {r["id"]: r for r in L["records"]}
    enc = build_encoder()

    def rebuild(p: int, raw: bytes) -> bytes:
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

    def runs_of(rec: bytes):
        out, cur = [], []
        for t in parse_record(rec):
            if t.kind == "glyph":
                cur.append(t.glyph_id)
            else:
                out.append((cur, t.opcode if t.kind == "control" else None, t.raw))
                cur = []
        if cur:
            out.append((cur, None, b""))
        return out

    def align(old: bytes, new: bytes, rid: str) -> bytes:
        """스크립트 레코드의 런 advance/phase를 원문에 맞춘다. 못 맞추면 실패.

        **앵커(FC/FD/F8/FB...)가 하나도 없는 레코드는 대상이 아니다.** 이름·용어표는
        각자 자기 칸에 그려지고 한글이 원문보다 넓어도 된다(도너도 원문 최대 폭을 넘는
        한글 이름을 출고한다). 좌표로 그리는 스크립트에만 이 제약이 있다.
        """
        o, n = runs_of(old), runs_of(new)
        if not any(op in ANCHORS for _, op, _ in o):
            return new
        if len(o) != len(n):
            raise SystemExit(f"{rid}: 제어 토큰 수가 달라졌다 ({len(o)} -> {len(n)})")
        out = bytearray(); ph_o = ph_n = 0
        for (oi, oop, _), (ni, nop, nraw) in zip(o, n):
            ao, ph_o2 = sig(oi, ph_o)
            an, ph_n2 = sig(ni, ph_n)
            ids = list(ni)
            # 2026-08-23: 위상 패딩을 **끈다**. advance/phase 모델은 도너 엔진에서 가져온
            # 것이고 이 타깃에서 검증한 적이 없다. 켰더니 원본에 43개뿐이던 전각공백 글리프를
            # 94개 더 끼워 넣었고(S00/S01/S02/S13 집중), 1차 빌드에서 통과하던 시나리오 시작이
            # 하드 행(0 FPS)으로 죽었다. 원본에 없던 것을 넣는 변경이므로 먼저 되돌린다.
            # 폭 초과는 계속 경고로만 집계한다.
            if an > ao:
                WIDE.append((rid, oop, ao, an))
            for g in ids:
                out += glyph_bytes(g)
            out += nraw
            ph_o, ph_n = ph_o2, ph_n2
        return bytes(out)

    # 이분 탐색용: SRW4S_SKIP_TR="0,1,2" 면 그 섹션은 원문 그대로 둔다.
    # "all" 이면 전 섹션 원문 -> 산출물이 원본과 바이트 동일해야 한다(풀 순회기 항등 검사).
    _sk = os.environ.get("SRW4S_SKIP_TR", "")
    SKIP_TR = ({x["section"] for x in live} if _sk.strip() == "all"
               else {int(x) for x in _sk.split(",") if x.strip()})

    built = {}
    for s in live:
        skip = s["section"] in SKIP_TR
        for st in s["strings"]:
            p_ = st["pointer"]
            if p_ in built:
                continue
            old_ = st["raw"] + bytes([0xFF])
            if skip:
                built[p_] = old_
                continue
            new_ = rebuild(p_, st["raw"])
            built[p_] = new_ if new_ == old_ else align(old_, new_, f"DN:{p_:04X}")

    out = bytearray(72)
    pool = Pool(out)
    new_start, remap = {}, {}
    tables: list[tuple[int, list[int]]] = []
    pending: list[tuple[int, dict]] = []
    deferred: set[int] = set()
    head_pos: dict[int, int] = {}

    for s in own:
        i = s["section"]
        # **섹션 표는 u16 배열이라 짝수 주소여야 한다.**
        # 홀수면 런타임의 `lhu` 가 정렬 예외를 내고 게임이 예외 벡터로 튄다
        # (2026-08-24 실기: 로드 화면에서 pc=0x80000080). 원본은 18개 전부 짝수다.
        if len(out) % 2:
            out.append(0)
        new_start[i] = len(out)
        out += bytes(2 * s["count"])              # 테이블 자리만 잡고 뒤에 채운다
        # 2026-08-23: **원본 물리 순서를 그대로 지킨다.** 재배치(긴 것부터 + 접미사 공유)를
        # 하면 레코드 인접성이 깨진다. 스크립트 VM이 한 레코드의 종단을 넘어 다음 레코드로
        # 이어 읽는 것으로 보이며, 순서를 바꾸자 실기에서 panic 트랩에 걸렸다
        # (폰트만 패치한 빌드는 멀쩡 -> 원인이 D_NAMES 재배치임을 이분 탐색으로 확인).
        # 저장된 포인터도 코드 상수도 없었다 — 깨진 것은 **순서**다.
        if i in ORDERED_SECTIONS:
            # 스크립트 섹션: 원본 풀을 **바이트 단위로 훑는다.**
            # 레코드는 재인코딩본으로 바꾸되, 포인터가 가리키지 않는 사이 조각은
            # 원본 그대로 옮긴다. 그 조각들은 죽은 여백이 아니라 VM 이 레코드 종단을
            # 넘어 이어 읽는 실제 스크립트다 (2026-08-23 실기: 버렸더니 정신 메뉴에서
            # panic 트랩 0x800C3A00, 스트림 포인터가 조각이 있어야 할 자리를 가리켰다).
            tbl_end = s["table_end"]
            later = [t["start"] for t in live if t["start"] > tbl_end]
            pool_end = min(later) if later else len(data)
            origlen = {st["pointer"]: len(st["raw"]) + 1 for st in s["strings"]}
            starts = sorted(q for q in {st["pointer"] for st in s["strings"]}
                            if tbl_end <= q < pool_end)
            cur, si = tbl_end, 0
            while cur < pool_end:
                if si < len(starts) and starts[si] == cur:
                    q = starts[si]
                    si += 1
                    if q not in remap:
                        remap[q] = pool.append(built[q])
                    cur += origlen[q]
                else:
                    nxt = starts[si] if si < len(starts) else pool_end
                    if nxt <= cur:
                        raise SystemExit(f"S{i:02d}: 풀 순회가 진행하지 않는다 @{cur:#06x}")
                    # 미참조 조각도 공유 색인에 넣는다. 읽기 전용이고 바이트가 같으면
                    # 어디서 읽든 결과가 같으므로, 다른 섹션이 이 안을 가리켜도 안전하다.
                    at = len(out)
                    chunk = data[cur:nxt]
                    out += chunk
                    k = 0
                    for j, b in enumerate(chunk):
                        if b == 0xFF:                      # 조각을 레코드 단위로 쪼개 등록
                            sub = bytes(chunk[k:j + 1])
                            if sub:
                                pool.register_only(at + k, sub)
                            k = j + 1
                    cur = nxt
        else:
            # 이름·용어표: 테이블로만 접근하므로 재배치·공유 가능.
            # 표 바로 뒤에 붙여야 하는 것만 여기서 붙이고 나머지는 뒤로 미룬다.
            #   * 머리 레코드: 0번 엔트리 포인터 = 그 테이블의 끝이어야 한다.
            #   * 이 섹션을 감싸는 **별칭 섹션의 0번 레코드**: 별칭의 0번 포인터가 멀리 가면
            #     섹션 경계 판정이 "별칭이 뒤 섹션들을 감싼다"로 오인된다(S16 사례).
            head = s["strings"][0]["pointer"]
            head_pos[i] = pool.append(built[head])
            remap.setdefault(head, head_pos[i])
            for a, o in alias.items():
                if o != i:
                    continue
                k = (secs[a]["start"] - s["start"]) // 2
                if 0 <= k < len(s["strings"]):
                    aq = s["strings"][k]["pointer"]
                    if aq not in remap:
                        remap[aq] = pool.append(built[aq])
            deferred |= {st["pointer"] for st in s["strings"][1:]} - {head}
        pending.append((new_start[i], s))

    # 나머지는 **섹션을 가리지 않고 한꺼번에** 긴 것부터 배치한다.
    # 섹션별로 나눠 넣으면 뒤 섹션의 더 긴 레코드에 흡수될 기회를 잃는다
    # (포인터는 파일 절대 u16 이라 어느 섹션의 풀에 있든 상관없다).
    for q in sorted(deferred, key=lambda x: -len(built[x])):
        if q not in remap:
            remap[q] = pool.place(built[q])

    for start, s in pending:
        i = s["section"]
        hp = head_pos.get(i)
        hq = s["strings"][0]["pointer"]
        tables.append((start, [hp if (hp is not None and st["pointer"] == hq)
                               else remap[st["pointer"]] for st in s["strings"]]))

    for i, owner in alias.items():
        new_start[i] = new_start[owner] + (secs[i]["start"] - secs[owner]["start"])

    for start, ptrs in tables:
        for k, p in enumerate(ptrs):
            struct.pack_into("<H", out, start + 2 * k, p)
    for i, s in enumerate(secs):
        struct.pack_into("<I", out, 4 * i, new_start.get(i, 0) if s["start"] is not None else 0)

    if WIDE:
        print(f"[경고] 원문보다 넓어 정렬 못 한 런 {len(WIDE)}건 / 레코드 {len({w[0] for w in WIDE})}개 "
              f"— translation/_wide_runs.json 참조 (실기 확인 대상)")
        (ROOT / "translation" / "_wide_runs.json").write_text(
            json.dumps([[a, (f"{b:02X}" if b is not None else None), c, d] for a, b, c, d in WIDE],
                       ensure_ascii=False, indent=0), encoding="utf-8")
    odd = [i for i, v in enumerate(struct.unpack_from("<18I", out, 0)) if v and v % 2]
    if odd:
        print(f"FAIL: 섹션 표가 홀수 주소다 {odd} — 런타임 lhu 가 정렬 예외를 낸다")
        return 1
    print(f"새 파일 {len(out):,}B   슬롯 {SLOT:,}   여유 {SLOT - len(out):+,}")
    print(f"레코드 {len(built)}개 중 공유 재사용 {pool.reused}회 / 절약 {pool.shared_bytes:,}B")
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build" / "D_NAMES_ko.BIN").write_bytes(out)
    json.dump({f"0x{k:04X}": f"0x{v:04X}" for k, v in sorted(remap.items())},
              open(ROOT / "build" / "dnames_remap.json", "w"), indent=0)
    print("build/D_NAMES_ko.BIN sha:", hashlib.sha256(out).hexdigest()[:16])
    return 0 if len(out) <= SLOT else 1


if __name__ == "__main__":
    raise SystemExit(main())
