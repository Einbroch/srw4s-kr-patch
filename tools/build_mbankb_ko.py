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
import os
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

# --- 블롭 밖 확장 구간 ---
# 표 슬롯이 u16 이라 블롭 시작(RAM 0x80107B8C)에서 65,535 까지 가리킬 수 있다.
# 해제물은 55,353 B 뿐이고 그 뒤는 BATTLE 오버레이 이미지다. 실기 읽기 BP 로
# 0x801155C5 이후는 전투 중 한 번도 안 읽히는 걸 확인했다(readbp.lua, 43조각 중
# 읽힌 건 M_BANKB 끝에 붙은 첫 조각 하나뿐, 그것도 커널 적재 루틴이었다).
# 그 첫 512 B 는 여백으로 비켜 둔다.
EXT_LO   = 55353 + 512                         # 블롭 기준 오프셋 (RAM 0x801155C5)
EXT_END  = 65535                               # u16 한계
BATTLE_OFF = 0x801153C5 - 0x80106380           # 블롭 끝의 BATTLE 오버레이 오프셋
OUT_EXT = ROOT / "build" / "MBANKB_EXT.bin"    # 확장 구간 바이트 (BATTLE 에 써 넣는다)

# 확장 구간은 **BATTLE 오버레이에만** 있다. C_BEFCT 안의 세 번째 사본은 블롭 시작
# 주소가 같지만 그 뒤는 자기 컨테이너의 산 데이터라 쓸 수 없다(2026-09-04 회귀).
# 그래서 C_BEFCT 용으로는 확장을 끈 판을 따로 만든다 — 뱅크 표는 파일마다 따로이므로
# 두 사본이 서로 다른 배치를 가져도 된다. 전투는 온전한 이름, 맵은 줄인 이름이 나온다.
NOEXT = os.environ.get("SRW4S_MB_NOEXT") == "1"
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

    # --- 전투 화자 이름: 늘리고 **점프 s16 을 보정한다** ---
    # 자세한 근거는 tools/mbankb_jumpfix.py 머리말.
    from mbankb_jumpfix import grow_names, targets
    NAME_GROW = [
        # (레코드 시작, 레코드 끝, [(레코드내 오프셋, 원문 바이트수, 새 이름)], 새 꼬리)
        # **마지막 이름만** 늘릴 수 있다. 호출자는 이름 자리로 고정 오프셋으로
        # 진입하므로, 앞 이름을 늘리면 뒤 이름의 진입점이 밀려 앞 점프의 오프셋
        # 바이트가 글자로 찍힌다(2026-09-05 실측: `とF카즈야「…」`).
        # 이름은 [오프셋, 원문 바이트수, 새 이름]. 꼬리 대사를 줄여 레코드 길이를 맞춘다.
        # 洸 -> 아키라 는 +4 라 이 레코드에는 자리가 없다(꼬리가 「엣」 이 한계).
        # 2026-09-05 **전면 보류.** 이름을 늘리면 슬롯·점프를 다 맞춰도 인접 대사의
        #   진입이 어긋난다. `카즈야Lケ「안맞아!」` 처럼 `{C:0F}` 뒤 색인 2바이트가
        #   글자로 찍힌다. v0.99e/f 에 이 결함이 들어간 채 배포됐다.
        #   슬롯(뱅크 표)과 점프(s16) 말고 **세 번째로 위치에 의존하는 것**이 있다.
        #   그것을 찾기 전에는 길이를 바꾸지 않는다 — 같은 길이 치환만 안전하다
        #   (효마·반죠는 그래서 유지).
    ]
    _byid = {r["id"]: r for r in doc["records"]}
    for rid, names, tail in NAME_GROW:
        r = _byid[rid]
        old = bytes(data[r["offset"]:r["end"]])
        _hdr = list(struct.unpack_from("<61I", bytes(data), 0))
        from mbankb_reloc import _nslots as _ns3
        _sl = []
        for _off in [o for o in _hdr if o and o + 0x200 <= len(data)]:
            for _k in range(_ns3(bytes(data), _off)):
                _sl.append((_off, _k, struct.unpack_from("<H", data, _off + 2 * _k)[0]))
        new, grown = grow_names(old, names, tail, encode, enc,
                                slots=_sl, rec_off=r["offset"], data=data)
        if len(new) != len(old):
            print(f"FAIL {rid}: 길이 {len(old)} -> {len(new)}")
            return 1
        a, b = targets(old, r["offset"]), targets(new, r["offset"])
        if a != b:
            print(f"FAIL {rid}: 점프 대상이 달라졌다")
            print("  전", [hex(x) for x in a])
            print("  후", [hex(x) for x in b])
            return 1
        data[r["offset"]:r["end"]] = new
        print(f"화자 이름 {rid}: {len(names)}개 늘림(+{grown}B) / 점프 {len(a)}개 대상 그대로")

    # --- (보류) 길이 불변 제자리 치환 ---
    # 이 표는 이름뿐 아니라 초상화/CLUT 인덱스까지 담고 항목의 **위치가 곧 의미**다.
    # 늘리려고 세 번 시도해 세 번 다 깨졌다(확장 구간으로 이동 -> 글자 쓰레기,
    # 블롭 안에서 확장 -> 대사 사라짐 + 초상화 깨짐). 그래서 **원문과 같은 바이트 수**로만
    # 바꾼다. `一矢`(4 B)에는 한글 2자(4 B)가 들어간다 — `카즈`.
    # 반각(1바이트) 글리프로 3자를 넣는 길도 막혔다: 0x01~0xEF 240칸이 전부 쓰이고 있다.
    # 2026-09-05 — `카즈` 로 넣었다가 사용자 판단으로 원문 유지. 두 자로 자른 이름보다
    #   일본어 원문이 낫다고 봤다. 맵 대사에서는 `카즈야` 로 제대로 나온다.
    #   다시 넣으려면 아래 튜플에 ("一矢", "카즈") 를 넣으면 된다 (길이가 같아야 한다).
    for _jp, _ko in ():
        _pj, _pk = encode(_jp, enc)[:-1], encode(_ko, enc)[:-1]
        assert len(_pj) == len(_pk), (_jp, _ko)
        _n = 0
        _i = 0
        while True:
            _i = bytes(data).find(_pj, _i)
            if _i < 0:
                break
            data[_i:_i + len(_pk)] = _pk
            _n += 1
            _i += len(_pk)
        if _n:
            print(f"이름표 제자리 치환: {_jp} -> {_ko}  {_n}곳 ({len(_pj)}B 그대로)")

    # --- (보류) 이름표 확장 ---
    # 이름표는 2차 해제본(0x801A6878)에서 읽히므로 확장 구간에 놓으면 안 된다.
    if os.environ.get("SRW4S_MB_NOEXT") != "1":
        from mbankb_nametable import run as nt_run, verify as nt_verify, rec_end as nt_end
        from mbankb_reloc import _nslots as _ns2
        recs2 = {r["id"]: r for r in doc["records"]}
        hdr2 = list(struct.unpack_from("<61I", bytes(data), 0))
        slots2, cov = [], bytearray(len(data))
        for i in range(244):
            cov[i] = 1
        for off in [o for o in hdr2 if o and o + 0x200 <= len(data)]:
            for k in range(_ns2(bytes(data), off)):
                v = struct.unpack_from("<H", data, off + 2 * k)[0]
                slots2.append((off, k, v))
                cov[off + 2 * k] = cov[off + 2 * k + 1] = 1
        _hid = ROOT / "translation" / "mbankb_hidden_ledger.json"
        _all = list(doc["records"])
        if _hid.exists():
            _all += json.loads(_hid.read_text(encoding="utf-8"))["records"]
        for r in _all:
            for j in range(r["offset"], min(r["end"], len(data))):
                cov[j] = 1
        for _t, _k, v in slots2:
            if v < len(data):
                for j in range(v, nt_end(bytes(data), v)):
                    cov[j] = 1
        holes, i = [], 0
        while i < len(cov):
            if not cov[i]:
                k = i
                while k < len(cov) and not cov[k]:
                    k += 1
                holes.append([i, k - i])
                i = k
            else:
                i += 1
        holes.sort(key=lambda h: -h[1])
        # 2026-09-05 되돌림 — **이 표는 길이를 못 바꾼다.**
        #   블롭 안에서 늘리고 안쪽 슬롯 27개를 이동 전/후 바이트열로 직접 대조해
        #   통과했는데도, 실기에서 전투 대사가 통째로 비고 **초상화까지 깨졌다**.
        #   초상화가 깨진다는 건 이 표가 이름만이 아니라 초상화/CLUT 인덱스도 담고
        #   있고, **항목의 위치 자체가 의미**라는 뜻이다(슬롯이 아니라 순번으로 읽는다).
        #   바이트를 한 개라도 끼워 넣으면 그 뒤 항목이 전부 어긋난다.
        #   -> 이름을 바꾸려면 **원문과 정확히 같은 바이트 수**여야 한다. `一矢`(4 B)에는
        #      한글 2자(4 B)만 들어간다.
        PLAN: list = []
        snap = bytes(data)
        ok2, bad2, chk2 = nt_run(data, slots2, recs2, PLAN, holes, encode, enc)
        errs = nt_verify(snap, bytes(data), chk2,
                         [(encode("一矢", enc)[:-1], encode("카즈야", enc)[:-1])])
        if bad2 or errs:
            for e in (bad2 + errs)[:6]:
                print("FAIL 이름표:", e)
            return 1
        print(f"이름표 {ok2}개 확장 / 슬롯 {len(chk2)}개 재연결 / 이동 전후 직접 대조 통과")

    # --- 블롭을 키워 이름 레코드를 옮긴다 ---
    # 2차 해제본은 64 KB 슬롯에 들어가고(코드: dest / dest+0x10000 / dest+0x20000)
    # M_BANKB 는 55,353 B 만 쓴다. 남는 10,183 B 는 u16 슬롯 한계와 거의 일치한다.
    # 거기로 레코드를 옮기면 꼬리 대사를 깎지 않고 이름을 온전히 넣을 수 있다.
    # C_BEFCT(맵 경로)는 이 확장을 쓰지 않으므로 무확장판을 따로 만든다.
    if os.environ.get("SRW4S_MB_NOEXT") != "1":
        from mbankb_jumpfix import move_and_grow, targets as _tg
        # 2026-09-05 보류 — 블롭을 55,440 B 로 키우고 이 레코드를 옮겼더니, 점프 124개
        #   대상 전부 일치·슬롯 전부 정상인데도 적 턴 피격 대사가
        #   `카즈야Fケ「우옷!!」` 처럼 떴다(= `{C:0F}` 뒤 색인 2바이트가 글자로 찍힘).
        #   데이터 불변식은 다 지켜졌으므로 원인이 데이터 밖에 있다 — 블롭 크기 자체를
        #   전제하는 코드가 어딘가 있는 것으로 보인다. 규명 전까지 확장은 쓰지 않는다.
        MOVE_GROW: list = []
        # --- 단일 변수 시험: **블롭만 키우고 레코드는 그대로** ---
        # 지난 시도엔 (a) 블롭 확장 (b) 레코드 이동 이 섞여 있었다. 어느 쪽이 화면을
        # 깨뜨렸는지 가르려면 (a) 만 해 본다. 아무 데도 안 쓰이는 0 을 뒤에 붙여
        # 해제물 크기만 늘린다. 이게 멀쩡하면 원인은 (b) 다.
        _pad = int(os.environ.get("SRW4S_MB_PAD", "0"))
        if _pad:
            data += bytes(_pad)
            print(f"블롭 크기 시험: {len(orig):,} -> {len(data):,} B (0 {_pad}B 덧붙임)")
        BLOB_MAX = 65535                     # u16 슬롯 한계
        for rid, names in MOVE_GROW:
            r = _byid[rid]
            old = bytes(data[r["offset"]:r["end"]])
            at = len(data)
            new, remap, grown = move_and_grow(old, r["offset"], at, names, encode, enc)
            if at + len(new) > BLOB_MAX:
                print(f"FAIL {rid}: 확장이 u16 한계를 넘는다 ({at + len(new)} > {BLOB_MAX})")
                return 1
            data += new
            a, b = _tg(old, r["offset"]), _tg(new, at)
            if a != b:
                print(f"FAIL {rid}: 점프 대상이 달라졌다")
                print("  전", [hex(x) for x in a]); print("  후", [hex(x) for x in b])
                return 1
            hdr3 = list(struct.unpack_from("<61I", bytes(data), 0))
            from mbankb_reloc import _nslots as _ns4
            moved = 0
            for off in [o for o in hdr3 if o and o + 0x200 <= len(data)]:
                for k in range(_ns4(bytes(data), off)):
                    v = struct.unpack_from("<H", data, off + 2 * k)[0]
                    if v in remap:
                        struct.pack_into("<H", data, off + 2 * k, remap[v])
                        moved += 1
            print(f"이름 레코드 {rid}: 0x{r['offset']:05X} -> 0x{at:05X} "
                  f"({len(old)}B -> {len(new)}B, +{grown}) / 점프 {len(a)}개 대상 그대로 "
                  f"/ 슬롯 {moved}개 재연결")
        print(f"  블롭 {len(orig):,} -> {len(data):,} B (u16 한계 {BLOB_MAX:,})")

    # --- 레코드 재배치 ---
    reloc = ROOT / "translation" / "mbankb_relocate_ko.py"
    if reloc.exists() and NOEXT:
        from mbankb_reloc import relocate
        _rl = runpy.run_path(str(reloc))
        FULL, WHOLE = _rl["FULL"], _rl.get("WHOLE", {})
        allrecs = list(doc["records"])
        _h = ROOT / "translation" / "mbankb_hidden_ledger.json"
        if _h.exists():
            allrecs += json.loads(_h.read_text(encoding="utf-8"))["records"]
        mv, nofit = relocate(data, doc["records"], allrecs, FULL, enc, encode, WHOLE)
        print(f"레코드 재배치(확장 없음): {mv}개 / 자리 없음 {len(nofit)}개")
    elif reloc.exists():
        from mbankb_reloc import relocate
        _rl = runpy.run_path(str(reloc))
        FULL, WHOLE = _rl["FULL"], _rl.get("WHOLE", {})
        allrecs = list(doc["records"])
        hid = ROOT / "translation" / "mbankb_hidden_ledger.json"
        if hid.exists():
            allrecs += json.loads(hid.read_text(encoding="utf-8"))["records"]
        # 블롭 뒤 BATTLE 오버레이 구간을 이어 붙여 확장 버퍼를 만든다.
        # 표 슬롯이 u16 이라 블롭 시작 +65,535 까지가 한계다.
        blob = len(data)
        battle, _ = lzb.decompress((ROOT / "extract" / "BTT" / "BATTLE.LZB").read_bytes())
        battle = bytes(battle)
        # 오버레이 쪽 오프셋은 **원래 블롭 크기** 기준이다. 블롭이 자란 만큼 밀어서 잘라야
        # 확장 구간의 블롭 오프셋과 오버레이 오프셋이 맞는다.
        tail = battle[BATTLE_OFF + (blob - len(orig)): BATTLE_OFF + (EXT_END - len(orig))]
        buf = bytearray(data) + bytearray(tail)
        mv, nofit = relocate(buf, doc["records"], allrecs, FULL, enc, encode, WHOLE,
                             ext=(EXT_LO, EXT_END, blob))
        data[:] = buf[:blob]
        extbytes = bytearray(buf[blob:])

        used = sum(1 for i, (a, b) in enumerate(zip(tail, extbytes)) if a != b)
        # BATTLE 오버레이의 확장 구간은 **원래 블롭 크기(55,353)** 기준으로 놓인다.
        # 블롭을 키우면 len(data) 가 커지지만 오버레이 쪽 오프셋은 그대로여야 하므로,
        # 앞부분(블롭이 자란 만큼)은 오버레이 원본 바이트를 그대로 채워 넣는다.
        # 그래야 build_battle_ko.py 의 "읽히는 앞 512 B" 검사가 유지된다.
        _head = battle[BATTLE_OFF:BATTLE_OFF + (blob - len(orig))]
        OUT_EXT.write_bytes(_head + extbytes)
        print(f"레코드 재배치: {mv}개" + (f" / 자리 없음 {len(nofit)}개" if nofit else ""))
        print(f"  확장 구간 {EXT_LO:,}..{EXT_END:,} (BATTLE 0x{BATTLE_OFF:X}~) 에 {used:,} B 사용"
              f" / 여유 {EXT_END - EXT_LO - used:,} B")

    data = bytes(data)
    assert len(data) >= len(orig), "크기가 줄었다"
    changed = sum(1 for a, b in zip(data, orig) if a != b)
    (ROOT / "build" / ("M_BANKB_ko_noext.dec" if NOEXT else "M_BANKB_ko.dec")).write_bytes(data)

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
    if not NOEXT:
        OUT.write_bytes(comp)

    budget = SECTORS * 2048
    print(f"레코드 {n}건 교체 / 바뀐 바이트 {changed:,} / 해제물 {len(data):,} B (원본과 동일)")
    print(f"압축 {len(comp):,} B  (원본 {len(raw_lzb):,} / {SECTORS}섹터 예산 {budget:,})"
          f"  -> {'들어감' if len(comp) <= budget else '초과! 재배치 필요'}")
    print(f"-> {OUT.relative_to(ROOT)}  sha {hashlib.sha256(comp).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
