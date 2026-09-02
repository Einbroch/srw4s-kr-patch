#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BTT/M_BANKB.LZB 한국어판 — **자리에서만** 바꾼다.

이 파일은 RAM 에서 자랄 수 없다. BATTLE 오버레이가 남긴 구멍
(RAM 0x80107A80..0x8011A980, 77,568 B)에 [268 B 표][M_BANKB 55,353 B]
[런타임 표 21,947 B] 가 **빈틈 없이** 들어차 있다(실기 RAM 덤프로 확인).
그래서 역문은 원본 레코드 길이 이하여야 하고, 남는 자리는 종단 FF 앞에
공백 글리프로 메워 **레코드 길이·파일 크기를 그대로 둔다**.
포인터를 하나도 안 건드리므로 표·주소 계산이 전부 그대로다.
"""
from __future__ import annotations
import hashlib, json, runpy, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode    # noqa: E402
import lzb, lzb_encode                        # noqa: E402

SRC = ROOT / "extract" / "BTT" / "M_BANKB.LZB"
LEDGER = ROOT / "translation" / "mbankb_ledger.json"
OUT_DEC = ROOT / "build" / "M_BANKB_ko.dec"
OUT = ROOT / "build" / "M_BANKB_ko.LZB"
SECTORS = 17                                   # 원본이 차지한 섹터 수
ARITY_TOK = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0,
             0xFB: 2, 0xFC: 1, 0xFD: 2, 0xFE: 1}


def main() -> int:
    raw_lzb = SRC.read_bytes()
    dec, _ = lzb.decompress(raw_lzb)
    data = bytearray(dec)
    orig = bytes(dec)

    doc = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()

    n, bad = 0, []
    for r in doc["records"]:
        if not r["ko"]:
            continue
        total = r["end"] - r["offset"]
        b = encode(r["ko"], enc)
        if len(b) != total:
            bad.append((r["id"], len(b), total))
            continue
        data[r["offset"]:r["end"]] = b
        n += 1

    if bad:
        for rid, got, want in bad:
            print(f"FAIL 길이 불일치 {rid}: {got} != {want}")
        return 1

    # --- 사본 전파 ---
    # M_BANKB 안에는 같은 대사가 **두 벌씩** 들어 있다(앞뒤 제어 토큰만 다르다).
    # 원장이 잡은 한 벌만 바꾸면 게임은 나머지 한 벌을 읽어 일본어가 그대로 나온다
    # (2026-08-31 실기: 컷인·데모셀렉트 둘 다 일본어).
    # 그래서 「」 안쪽 **글자 바이트열**을 키로 삼아 남은 사본까지 함께 바꾼다.
    SPACE = encode(" ", enc)[:-1]

    def quote(markup):
        i, j = markup.rfind("「"), markup.rfind("」")
        return markup[i + 1:j] if 0 <= i < j else None

    prop, skip, short = 0, 0, 0
    for r in doc["records"]:
        if not r["ko"]:
            continue
        qj, qk = quote(r["jp"]), quote(r["ko"])
        if qj is None or qk is None:
            continue
        try:
            bj, bk = encode(qj, enc)[:-1], encode(qk, enc)[:-1]
        except Exception:
            continue
        if len(bj) < 8 or len(bk) > len(bj):
            short += 1
            continue
        bk = bk + SPACE * ((len(bj) - len(bk)) // len(SPACE))
        if len(bk) != len(bj):
            short += 1
            continue
        i = orig.find(bj)
        while i >= 0:
            if bytes(data[i:i + len(bj)]) == bj:      # 아직 손 안 댄 자리만
                data[i:i + len(bj)] = bk
                prop += 1
            else:
                skip += 1
            i = orig.find(bj, i + 1)
    print(f"사본 전파 {prop}건 / 이미 바뀐 자리 {skip}건 / 길이 안 맞아 건너뜀 {short}건")

    # --- 전투 텍스트 풀 ---
    # 같은 전투 대사가 STAYDAT 꼬리에도, M_BANKB 에도 들어 있다. 원장이 못 잡은
    # 자리가 남으면 그 한 벌 때문에 화면이 일본어로 나온다(글꼴 사본과 같은 유형).
    # 길이는 못 키우므로 STAYDAT 와 **같은 짧은 역문**을 쓰고 공백으로 메운다.
    import runpy
    Q = dict(runpy.run_path(str(ROOT / "translation" / "staydat_battle_ko.py"))["Q"])
    # 전투 표의 짧은 대사(`あまいなっ!` 6B 등)는 위 사본 전파의 8바이트 하한에 걸린다.
    # 여기서 바이트열로 직접 바꾼다.
    Q.update(runpy.run_path(str(ROOT / "translation" / "mbankb_battle_ko.py"))["Q"])
    pool, missed = 0, []
    for qj, qk in Q.items():
        bj, bk = encode(qj, enc)[:-1], encode(qk, enc)[:-1]
        if len(bk) > len(bj):
            print(f"FAIL 예산 초과 {len(bj)}B -> {len(bk)}B: {qj[:30]!r}")
            return 1
        bk = bk + SPACE * ((len(bj) - len(bk)) // len(SPACE))
        if len(bk) != len(bj):
            missed.append(qj)
            continue
        i = data.find(bj)
        while i >= 0:
            data[i:i + len(bj)] = bk
            pool += 1
            i = data.find(bj, i + len(bj))
    print(f"전투 텍스트 풀: {pool}곳 교체"
          + (f" / 공백 정렬 안 맞아 건너뜀 {len(missed)}종" if missed else ""))

    # --- 표 밖 전투 대사 ---
    # 뱅크 표에서 도달하지 않는 구간에 파일럿 전투 대사가 1,686개 들어 있다
    # (공격 구호·피격·회피·격추). 게임은 다른 경로로 색인한다.
    # 자리는 고정이므로 원문 바이트 수 안에서 바꾸고 공백으로 메운다.
    hid = ROOT / "translation" / "mbankb_hidden_ledger.json"
    if hid.exists():
        H = json.loads(hid.read_text(encoding="utf-8"))
        hn, hbad = 0, []
        for r in H["records"]:
            if not r["ko"]:
                continue
            want = r["end"] - r["offset"]
            b = encode(r["ko"], enc)
            if len(b) > want:
                hbad.append((r["id"], len(b), want)); continue
            b = b[:-1] + SPACE * (want - len(b)) + b[-1:]
            if len(b) != want:
                hbad.append((r["id"], len(b), want)); continue
            # 이 자리는 표 밖 원장이 정본이다. 앞선 풀 단계가 같은 대사를
            # 이미 바꿔 놨을 수 있으므로(`あまいなっ!` 등) 덮어쓰기를 허용한다.
            data[r["offset"]:r["end"]] = b
            hn += 1
        if hbad:
            for rid, got, wantn in hbad[:8]:
                print(f"FAIL 표밖 {rid}: {got}B != {wantn}B")
            return 1
        print(f"표 밖 전투 대사: {hn}개 교체")

    # --- 레코드 재배치 ---
    reloc = ROOT / "translation" / "mbankb_relocate_ko.py"
    if reloc.exists():
        from mbankb_reloc import relocate
        _rl = runpy.run_path(str(reloc))
        FULL, WHOLE = _rl["FULL"], _rl.get("WHOLE", {})
        allrecs = list(doc["records"])
        hid = ROOT / "translation" / "mbankb_hidden_ledger.json"
        if hid.exists():
            allrecs += json.loads(hid.read_text(encoding="utf-8"))["records"]
        mv, nofit = relocate(data, doc["records"], allrecs, FULL, enc, encode, WHOLE)
        print(f"레코드 재배치: {mv}개" + (f" / 자리 없음 {len(nofit)}개" if nofit else ""))

    data = bytes(data)
    assert len(data) == len(orig), "크기가 바뀌었다"
    changed = sum(1 for a, b in zip(data, orig) if a != b)
    OUT_DEC.write_bytes(data)

    comp = lzb_encode.compress(data)
    back, _ = lzb.decompress(comp)
    if bytes(back) != data:
        print("FAIL: 재압축 왕복 불일치")
        return 1
    # 번역이 늘수록 압축본이 작아져 **섹터 수가 줄어든다**(17 -> 16).
    # 그러면 제자리 교체가 거부되고 재배치 게이트가 필요해진다.
    # LZB 는 종단 표시로 끝나므로 뒤에 0을 붙여도 무해하다 — 원본 크기까지 채워
    # 17섹터를 유지한다.
    if len(comp) < len(raw_lzb):
        comp = comp + bytes(len(raw_lzb) - len(comp))
    OUT.write_bytes(comp)

    budget = SECTORS * 2048
    print(f"레코드 {n}건 교체 / 바뀐 바이트 {changed:,} / 해제물 {len(data):,} B (원본과 동일)")
    print(f"압축 {len(comp):,} B  (원본 {len(raw_lzb):,} / {SECTORS}섹터 예산 {budget:,})"
          f"  -> {'들어감' if len(comp) <= budget else '초과! 재배치 필요'}")
    print(f"-> {OUT.relative_to(ROOT)}  sha {hashlib.sha256(comp).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
