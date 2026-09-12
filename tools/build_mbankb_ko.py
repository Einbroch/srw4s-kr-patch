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
import hashlib, json, re, runpy, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode    # noqa: E402
import lzb, lzb_encode                        # noqa: E402
import mbankb_href as mbankb_href_mod          # noqa: E402

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
# **실측으로 좁힌 창.** 이 자리는 BATTLE 오버레이의 전투 애니메이션 명령 스트림이라
# u16 한계(65,535)까지 다 쓰면 안 된다. `D:/srw4s_ko/extscan.lua` 로 128 B 조각마다
# 읽기 BP 를 걸고 **LZB 해제기(0x800C3600..0x800C3B00)와 BIOS 읽기를 걸러낸** 뒤
# 여러 기체로 전투해 본 결과, 게임이 실제로 읽은 조각은 7개뿐이고 가장 큰 빈 구간이
# 블롭 55,865..60,473 (4,608 B) 이었다. 그 안에서만 쓴다.
#   (초판 측정은 해제기 읽기를 못 걸러 76조각 전부 "읽힘"으로 나왔다.)
# 2026-09-06 — 교집합 창(55,865..59,449) + 미러링으로 넓혀 봤더니 빌드 sha 가
# 스프라이트가 사라졌던 f80a5808 과 **바이트 동일**하게 나왔다. 두 측정이 안전이라
# 했는데 실기는 아니었다는 뜻이므로 되돌린다. `growroom` 은 무장한 **뒤의 쓰기**만
# 보므로, 그 RAM 에 이미 남의 데이터가 올라와 있고 게임이 **읽기만** 하면 못 잡는다.
EXT_END  = 60473

# 재배치가 쓸 블롭 여유. 확장 구간을 안 쓰기로 했으므로 여기서 다 감당해야 한다.
# 늘리면 압축본이 커진다 — 17섹터(34,816 B) 예산 안에 드는지 빌드가 알려 준다.
RELOC_RESERVE = int(os.environ.get('SRW4S_MB_RESERVE', '1200'))

# 2차 해제본(RAM 0x801A6878) 뒤 여유. **프로브로 쟀다**(D:/srw4s_ko/bloblimit.lua,
# 2026-09-09): 블롭 끝 뒤 10 KB 에 쓰기 BP 를 걸고 전투를 돌렸더니 **base+65,198
# 조각(512 B)에서 처음** 남이 썼다. 그 조각은 정적 할당표의 버퍼 0x801B6800
# (= base+65,416) 을 품는다 — 실측과 정적 분석이 같은 자리를 가리킨다.
# 그래서 예전에 "57,896 이 벽"이라 한 것은 **틀렸다**. 그때 RELOC_RESERVE 를 줄여
# 크기를 바꿨는데 그러면 어떤 레코드가 어디 놓이는지도 같이 바뀐다 — 크기와 내용을
# 한꺼번에 흔들고 크기 탓을 했다.
# 다만 할당표에는 0x801B5800(= base+61,320) 도 있고 프로브가 돈 화면에서만 안 쓰였다.
# 그래서 상한은 그 앞으로 보수적으로 잡는다.
MAX_BLOB = int(os.environ.get('SRW4S_MB_MAXBLOB', '61320'))
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
    _reref = []      # repoint 가 쓴 (u16 오프셋, delta)
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

        # --- 표 밖 이웃끼리 바이트 주고받기 (총 길이 보존) ---
        # 표 밖 레코드는 진입점이 아니라 **경유지**다. VM 이 앞쪽 진입점에서 흘러와
        # 종단(0xFF)을 세며 지나간다(실기 dropsrc4). 그래서 이웃들의 **총 바이트**와
        # **종단 개수**만 지키면 경계는 옮겨도 된다 — 구간 밖 오프셋이 하나도 안 변한다.
        # `HIDDEN_PAIR`(2개) 는 `HIDDEN_GROUP`(N개) 의 특수한 경우다.
        _mod = runpy.run_path(str(ROOT / "translation" / "mbankb_relocate_ko.py"))
        _pair = _mod.get("HIDDEN_PAIR", [])
        _groups = [[(a, ka), (b, kb)] for a, ka, b, kb in _pair]
        _groups += [list(g) for g in _mod.get("HIDDEN_GROUP", [])]
        if _groups:
            from build_mbankb_ledger import nslots
            _by = {r["id"]: r for r in H["records"]}
            _hdr = list(struct.unpack_from("<61I", bytes(data), 0))
            _tbls = [o for o in _hdr if o and o + 0x200 <= len(data)]
            for _g in _groups:
                _nm = "/".join(i for i, _ in _g)
                _rs = [_by.get(i) for i, _ in _g]
                if any(r is None for r in _rs):
                    print(f"FAIL 묶음 {_nm}: 원장에 없다")
                    return 1
                _brk = [(x["id"], y["id"]) for x, y in zip(_rs, _rs[1:])
                        if x["end"] != y["offset"]]
                if _brk:
                    print(f"FAIL 묶음 {_nm}: 붙어 있지 않다 {_brk}")
                    return 1
                _lo, _hi = _rs[0]["offset"], _rs[-1]["end"]
                _bs = [encode(k, enc) for _, k in _g]
                if sum(len(x) for x in _bs) != _hi - _lo:
                    print(f"FAIL 묶음 {_nm}: 합계 "
                          f"{'+'.join(str(len(x)) for x in _bs)} != {_hi - _lo} B")
                    return 1
                # 새 시작 자리 (경계가 움직인 레코드를 알아야 점프를 보정한다)
                _starts, _p = {}, _lo
                for _r, _bb in zip(_rs, _bs):
                    _starts[_r["offset"]] = _p
                    _p += len(_bb)
                # 게이트 1 — 슬롯. **표 길이는 데이터로 구한다**: 256/400 고정으로 읽으면
                #   표 뒤 레코드 바이트를 포인터로 오해해 가짜가 잡힌다
                #   (2026-09-12: 0x0CC1A[392] 가 그랬다) → [[table-length-from-data]]
                _ptr = []
                for _t in _tbls:
                    _b0 = _t & ~0xFFFF
                    for _k in range(nslots(bytes(data), _t)):
                        _v = struct.unpack_from("<H", bytes(data), _t + 2 * _k)[0]
                        if _lo <= _b0 + _v < _hi:
                            _ptr.append(f"슬롯 {_t:#07x}[{_k}]")
                # 게이트 2 — 점프. 레코드 **시작**을 가리키면 s16 을 보정해 따라가게 한다.
                #   **중간**을 가리키면 따라갈 근거가 없으므로 실패시킨다.
                _fix = []
                _q = 0
                while _q < len(data) - 3:
                    if data[_q] == 0xFC and data[_q + 1] in (6, 7):
                        _tg = _q + 2 + struct.unpack_from("<h", bytes(data), _q + 2)[0]
                        if _lo <= _tg < _hi:
                            if _tg in _starts:
                                if _starts[_tg] != _tg:
                                    _fix.append((_q, _tg, _starts[_tg]))
                            else:
                                _ptr.append(f"점프 {_q:#07x} -> 레코드 중간 {_tg:#07x}")
                        _q += 4
                    else:
                        _q += 1
                if _ptr:
                    print(f"FAIL 묶음 {_nm}: 구간을 가리키는 것이 있다 {_ptr[:6]}")
                    return 1
                # 게이트 3 — **`{C:01}{A}` 자기상대 참조**. 표 밖 대사 1,686개 중
                #   1,437개(85%)가 이 표로**만** 닿는다(tools/mbankb_href.py).
                #   슬롯도 점프도 없다고 안심하면 안 된다 — 2026-09-12 에 BH:0356A /
                #   BH:042BA 묶음을 이 검사 없이 넣었다가 실기에서 코우지 피격 대사가
                #   `코우지세!」` 로 깨졌다(옛 자리에서 읽음). 자리가 옮겨진 레코드는
                #   참조를 **전부 새 자리로 돌린다**.
                import mbankb_href as _href
                _inside = [_o for _o, _n2 in _starts.items() if _o != _n2
                           for _a in _href.refs_to(bytes(data), _o) if _lo <= _a < _hi]
                if _inside:
                    print(f"FAIL 묶음 {_nm}: 참조 u16 이 구간 안에 있다 "
                          f"{[f'{x:#07x}' for x in _inside[:4]]}")
                    return 1
                _rp = 0
                for _o, _n2 in sorted(_starts.items()):
                    if _o == _n2:
                        continue
                    try:
                        _rp += _href.repoint(data, _o, _n2)
                    except ValueError as _e:
                        print(f"FAIL 묶음 {_nm}: 참조 재지정 불가 — {_e}")
                        return 1
                data[_lo:_hi] = b"".join(_bs)
                for _q, _old, _new in _fix:
                    _d = _new - (_q + 2)
                    if not (-32768 <= _d <= 32767):
                        print(f"FAIL 묶음 {_nm}: 점프 {_q:#07x} 보정이 s16 밖 ({_d})")
                        return 1
                    struct.pack_into("<h", data, _q + 2, _d)
                print(f"표 밖 묶음 교체: {_nm} = "
                      f"{'+'.join(str(len(x)) for x in _bs)} = {_hi - _lo}B "
                      f"(0x{_lo:05X}..0x{_hi:05X}) / 점프 보정 {len(_fix)}곳"
                      f" / 자기상대 참조 재지정 {_rp}곳")
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
    # 길이가 **같은** 치환만 한다. 늘리면 다른 진입 경로가 어긋난다
    # (v0.99e/f 결함 → [[verify-each-entry-path]]).
    for _jp, _ko in (("一矢", "카즈"), ("ギャリソン", "개리 "), ("洸", "광")):
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

    # --- 이름 접두를 **블롭 뒤로** 옮겨 늘린다 ---
    # M_BANKB 는 RAM 에 두 벌 올라오고, 레코드 id 의 **비트 15** 로 어느 벌을 읽을지
    # 갈린다(0x8015A7B8):
    #     비트15=0 -> 0x80146EEC, base = *(0x801A50E8)  = 2차 해제본(LZB 해제물)
    #     비트15=1 -> 0x80146EC0, base = *(0x80163B74)  = BATTLE 오버레이 안 사본
    # 재배치된 무기 이름 대사는 오버레이 사본으로 읽혀서 확장 구간이 보이지만,
    # 이름 항목은 2차 해제본으로 읽혀 **확장 구간이 안 보인다**(2026-09-05 실측 2회:
    # 확장 위·아래 둘 다 잡글자). 2차 해제본은 LZB 해제물 그 자체이므로,
    # **블롭을 키우면** 거기에 자리가 생긴다. 게임은 dest/+0x10000/+0x20000 로
    # 64 KB 슬롯을 잡아 두므로 65,535 까지 안전하고, 슬롯이 u16 이라 한계도 같다.
    if not NOEXT:
        from mbankb_jumpfix import move_and_grow as _mag, targets as _tg2
        from mbankb_reloc import _nslots as _ns5
        GROW_MOVE = [
            # (레코드 id, 옮길 접두 바이트 수, [(레코드내 오프셋, 원문 B, 새 이름)])
            # 접두만 옮긴다 — 뒤쪽은 키 레코드 런(BB:0ABC1)이거나 슬롯이 가리키는
            # 다른 항목(BB:0AA2D)이라 한 바이트도 움직이면 안 된다.
            ("BB:0ABC1", 64, [(19, 5, "개리슨"), (36, 2, "아키라"),
                              (48, 4, "카즈야"), (56, 4, "카즈야")]),
            ("BB:0AA2D", 68, [(54, 4, "카즈야")]),
        ]
        for _rid, _split, _names in GROW_MOVE:
            _r = _byid[_rid]
            _pre = bytes(data[_r["offset"]:_r["offset"] + _split])
            _at = len(data)
            _new, _remap, _grown = _mag(_pre, _r["offset"], _at, _names, encode, enc)
            _new += bytes([0xFF])
            if _at + len(_new) > 65535:
                print(f"FAIL {_rid}: 블롭이 u16 한계를 넘는다")
                return 1
            _a, _b = _tg2(_pre, _r["offset"]), _tg2(_new, _at)
            if _a != _b:
                print(f"FAIL {_rid}: 접두 이동 후 점프 대상이 달라졌다")
                print("  전", [hex(x) for x in _a]); print("  후", [hex(x) for x in _b])
                return 1
            data += _new
            for _i in range(_r["offset"], _r["offset"] + _split):
                data[_i] = 0xFF
            _hdr6 = list(struct.unpack_from("<61I", bytes(data), 0))
            _mvd = 0
            for _off in [o for o in _hdr6 if o and o + 0x200 <= len(data)]:
                for _k in range(_ns5(bytes(data), _off)):
                    _v = struct.unpack_from("<H", data, _off + 2 * _k)[0]
                    if _v in _remap:
                        struct.pack_into("<H", data, _off + 2 * _k, _remap[_v])
                        _mvd += 1
            print(f"이름 접두 {_rid}: 0x{_r['offset']:05X}+{_split}B -> 0x{_at:05X} "
                  f"({_split}B -> {len(_new)}B, +{_grown}) / 점프 {len(_a)}개 대상 그대로 "
                  f"/ 슬롯 {_mvd}개 재연결")
        print(f"  블롭 {len(orig):,} -> {len(data):,} B (u16 한계 65,535)")

    # --- 레코드 재배치 ---
    reloc = ROOT / "translation" / "mbankb_relocate_ko.py"
    if reloc.exists() and NOEXT:
        from mbankb_reloc import relocate
        _rl = runpy.run_path(str(reloc))
        FULL, WHOLE = _rl["FULL"], _rl.get("WHOLE", {})
        COPY = _rl.get("COPY", ())
        allrecs = list(doc["records"])
        _h = ROOT / "translation" / "mbankb_hidden_ledger.json"
        if _h.exists():
            allrecs += json.loads(_h.read_text(encoding="utf-8"))["records"]
        mv, nofit = relocate(data, doc["records"], allrecs, FULL, enc, encode, WHOLE,
                             COPY=COPY)
        print(f"레코드 재배치(확장 없음): {mv}개 / 자리 없음 {len(nofit)}개")
    elif reloc.exists():
        from mbankb_reloc import relocate
        _rl = runpy.run_path(str(reloc))
        FULL, WHOLE = _rl["FULL"], _rl.get("WHOLE", {})
        COPY = _rl.get("COPY", ())
        allrecs = list(doc["records"])
        hid = ROOT / "translation" / "mbankb_hidden_ledger.json"
        if hid.exists():
            allrecs += json.loads(hid.read_text(encoding="utf-8"))["records"]
        # --- COPY 레코드 몫만큼 블롭을 미리 키운다 ---
        # 사본을 **확장 구간에 두면 안 된다.** 확장은 BATTLE 오버레이 사본
        # (비트15=1)에만 있는데([[mbankb-two-copies]]), 어느 사본을 읽을지는 표가
        # 아니라 **호출 경로**가 정한다. 블롭은 두 사본에 다 있으므로 어느 경로로
        # 와도 안전하다 — 이름 접두를 블롭 확장으로 옮긴 것이 실기에서 통과했다.
        # 여유를 조금 더 두는 것은 공짜다(압축 뒤 몇 바이트).
        # 재배치가 쓸 자리를 **블롭 안에** 미리 확보한다.
        # 확장 구간은 안 쓴다(EXT_OK_TABLES 가 비었다) — 그 자리는 호출 경로에 따라
        # 안 보이고, 안 보이면 초기화 안 된 RAM 을 글자로 읽는다.
        # u16 슬롯 한계 65,535 와 압축 예산 34,816 B(17섹터) 안에서만 키운다.
        _need = sum(len(encode(WHOLE[i], enc)) for i in COPY if i in WHOLE)
        _grow = _need + RELOC_RESERVE
        if len(data) + _grow > 65535:
            print(f"FAIL 블롭을 {_grow} B 키우면 u16 한계를 넘는다")
            return 1
        data += bytearray([0xFF]) * _grow
        print(f"  재배치용으로 블롭에 {_grow:,} B 확보 (COPY {_need} + 여유 {RELOC_RESERVE})")

        # 블롭 뒤 BATTLE 오버레이 구간을 이어 붙여 확장 버퍼를 만든다.
        # 표 슬롯이 u16 이라 블롭 시작 +65,535 까지가 한계다.
        blob = len(data)
        battle, _ = lzb.decompress((ROOT / "extract" / "BTT" / "BATTLE.LZB").read_bytes())
        battle = bytes(battle)
        # 오버레이 쪽 오프셋은 **원래 블롭 크기** 기준이다. 블롭이 자란 만큼 밀어서 잘라야
        # 확장 구간의 블롭 오프셋과 오버레이 오프셋이 맞는다.
        tail = battle[BATTLE_OFF + (blob - len(orig)): BATTLE_OFF + (EXT_END - len(orig))]
        buf = bytearray(data) + bytearray(tail)

        # --- 이름 접두를 확장 구간으로 옮겨 늘린다 ---
        # 레코드를 **통째로** 옮기면 안 된다. BB:0ABC1 의 뒤 14 B 는 키 레코드 런의
        # #0(키 0x0F03)이고, 런은 슬롯도 점프도 없이 **키 훑기**로만 닿기 때문에
        # 0x0AC01 에서 한 바이트도 움직이면 안 된다(tools/verify_mb_keyrun.py).
        # 그래서 마지막 {C:07} 까지의 **접두만** 옮기고 런 부분은 제자리에 둔다.
        # 비운 자리는 0xFF(빈 레코드)로 채워 모든 바이트가 레코드 경계로 남게 한다.
        from mbankb_jumpfix import move_and_grow as _mag, targets as _tg2
        from mbankb_reloc import _nslots as _ns5
        # 2026-09-05 **보류.** 접두 이동 자체는 데이터 불변식을 다 지킨다 —
        # 점프 19개 대상 그대로, 슬롯 18개 재연결, 키 런 454개 일치, 비운 자리 FF.
        # 그런데 실기에서 공격 대사가 대사·음성 없이 잡글자로 나온다. 확장 구간의
        # **위쪽(0x0FF6E)과 아래쪽(0x0DA39) 둘 다** 같은 식으로 깨졌다. 자리 문제가
        # 아니라 **이름 레코드 경로에서는 확장 구간이 안 보인다**는 뜻이다.
        # 레코드 찾기 코드(0x80146EEC)의 베이스가 `*(0x801A50E8)` = M_BANKB 2차
        # 해제본(0x801A6878, 55,353 B)이고, 확장 바이트는 BATTLE 오버레이 안의
        # 1차 사본(0x80107B8C) 뒤에만 있다. 2차 해제본에는 그 자리가 없다.
        # 블롭 안(표 끝 0x0A1AC 뒤)에는 빈자리가 132 B 뿐이고 145 B 가 필요해 안 된다.
        # => 이 두 레코드는 **같은 길이 치환**만 쓴다 (카즈 / 개리␠ / 광).
        PREFIX_MOVE: list = []
        # 확장 구간의 **아래쪽**(EXT_LO=0x0DA39 부터)에 놓는다. 위쪽(0x0FF6E 근처)에
        # 놨더니 공격 대사가 깨졌다(2026-09-05 실측: 대사·음성 없이 잡글자).
        # 아래쪽은 재배치 레코드 10여 개가 이미 쓰고 있고 실기에서 정상이다.
        EXT_CUR = EXT_LO
        # 직전 배포본 바이트를 다시 만들어 Expected Write 기준으로 쓰려고 둔 스위치.
        if os.environ.get("SRW4S_MB_NOPREFIX") == "1":
            PREFIX_MOVE = []
        for _rid, _split, _names in PREFIX_MOVE:
            _r = _byid[_rid]
            _pre = bytes(buf[_r["offset"]:_r["offset"] + _split])
            _sz = _split + sum(len(encode(k, enc)) - 1 - o for _, o, k in _names) + 1
            _at = EXT_CUR
            if _at + _sz > EXT_END:
                print(f"FAIL {_rid}: 확장 구간에 자리가 없다")
                return 1
            _new, _remap, _grown = _mag(_pre, _r["offset"], _at, _names, encode, enc)
            _new += bytes([0xFF])
            assert len(_new) == _sz, (len(_new), _sz)
            _a, _b = _tg2(_pre, _r["offset"]), _tg2(_new, _at)
            if _a != _b:
                print(f"FAIL {_rid}: 접두 이동 후 점프 대상이 달라졌다")
                print("  전", [hex(x) for x in _a]); print("  후", [hex(x) for x in _b])
                return 1
            buf[_at:_at + len(_new)] = _new
            # 비운 자리 채우기 — 런(_split 이후)은 절대 건드리지 않는다.
            for _i in range(_r["offset"], _r["offset"] + _split):
                buf[_i] = 0xFF
            _hdr5 = list(struct.unpack_from("<61I", bytes(buf), 0))
            _mvd = 0
            for _off in [o for o in _hdr5 if o and o + 0x200 <= blob]:
                for _k in range(_ns5(bytes(buf[:blob]), _off)):
                    _v = struct.unpack_from("<H", buf, _off + 2 * _k)[0]
                    if _v in _remap:
                        struct.pack_into("<H", buf, _off + 2 * _k, _remap[_v])
                        _mvd += 1
            EXT_CUR = _at + len(_new)
            print(f"이름 접두 {_rid}: 0x{_r['offset']:05X}+{_split}B -> 0x{_at:05X} "
                  f"({_split}B -> {len(_new)}B, +{_grown}) / 점프 {len(_a)}개 대상 그대로 "
                  f"/ 슬롯 {_mvd}개 재연결")

        # 2026-09-06 **오버레이 확장 구간 사용 중단.**
        # 그 자리는 BATTLE 오버레이의 **전투 애니메이션 명령 스트림**이다. 260 B 만
        # 쓸 때는 티가 안 났는데, 83건 복원으로 1,234 B 를 덮자 점보트3 합체 후
        # 피격에서 **로봇 스프라이트가 사라졌다**(실기). 예전 읽기 BP 측정이
        # "전투 중 한 번도 안 읽힘" 이라 했지만 그건 한 기체 한 전투였다.
        # 재배치는 블롭 안 빈자리만 쓴다. 이름 접두는 블롭을 키운 자리(비트15=0
        # 경로, 실기 확인)에 그대로 둔다.
        mv, nofit = relocate(buf, doc["records"], allrecs, FULL, enc, encode, WHOLE,
                             COPY=COPY,
                             ext=(EXT_CUR, EXT_END, blob))
        extbytes = bytearray(buf[blob:])
        # --- 재배치 레코드는 **두 사본 모두**에서 보여야 한다 ---
        # M_BANKB 는 RAM 에 두 벌 올라오고 레코드 id 의 비트 15 가 어느 벌을 읽을지
        # 고른다(0x8015A7B8, [[mbankb-two-copies]]). 확장 구간은 BATTLE 오버레이
        # 사본(비트15=1)에만 있고 LZB 2차 해제본(비트15=0)에는 없다.
        # 표 0x09FB8 처럼 비트15=0 으로 읽히는 표의 레코드를 확장 구간에만 두면
        # 게임이 쓰레기를 읽는다 — 2026-09-06 실기에서 **멈춤**으로 나타났다
        # (점보트3 합체 후 피격). 그래서 쓰인 자리까지 **블롭도 같이 키워**
        # 같은 바이트를 두 사본에 둔다. 슬롯이 u16 이라 65,535 까지 안전하다.
        extbytes = bytearray(buf[blob:])
        # 창 **밖**을 한 바이트라도 건드리면 실패시킨다. 그 밖은 게임이 읽는
        # 애니메이션 데이터다(실측: 조각 #36~ 이후가 pc=0x80149E9C 에서 읽힌다).
        _out = [blob + i for i, (a, b) in enumerate(zip(tail, extbytes))
                if a != b and not (EXT_LO <= blob + i < EXT_END)]
        if _out:
            print(f"FAIL 확장 창 밖을 건드렸다: {len(_out)}곳 예 {[hex(x) for x in _out[:5]]}")
            return 1
        # 재배치 레코드는 **두 사본 모두**에서 보여야 한다([[mbankb-two-copies]]).
        # 확장 구간은 오버레이 사본(비트15=1)에만 있으므로, 쓰인 자리까지 블롭도
        # 같이 키워 같은 바이트를 2차 해제본(비트15=0)에도 둔다.
        # 미러링 금지. 블롭을 57,127 B 로 키운 빌드에서 스프라이트가 사라졌고,
        # 격리 시험(56,503 B)은 해당 스테이지를 지나쳐 검증할 수 없었다.
        # **실기로 확인된 한도는 55,498 B(이름 접두)뿐이다.** 그 위는 근거가 없다.
        data[:] = buf[:blob]

        # --- 표 밖 대사를 옮겨서 늘린다 ---
        # 칸이 모자란 표 밖 레코드를 **블롭 끝에 새로 놓고**, 그걸 가리키던
        # `{C:01}{A}` 상대 오프셋 표의 참조를 전부 새 자리로 돌린다.
        # 기존 레코드 경계는 하나도 안 움직인다 — 경계를 옮겼다가 실기에서 깨진
        # 전례가 있다([[exhaustive-is-not-complete]]).
        # 게이트: 목록에 **폰트에 없는 글자**가 있으면 여기서 다 알려 주고 멈춘다.
        # 안 그러면 encode 가 첫 글자 하나만 KeyError 로 던져 하나씩 고치게 된다.
        # (한글은 할당된 것만 있다 — `깟` 처럼 흔해 보여도 없을 수 있다.)
        _missing = []
        for _d, _lbl in ((_rl.get("FULL", {}), "FULL"),
                         (_rl.get("HIDDEN_MOVE", {}), "HIDDEN_MOVE")):
            for _k, _v in _d.items():
                for _c in set(re.sub(r"\{[^}]*\}", "", _v)):
                    if _c not in enc:
                        _missing.append((_lbl, _k, _c))
        if _missing:
            for _lbl, _k, _c in _missing[:12]:
                print(f"FAIL {_lbl} {_k}: 폰트에 없는 글자 '{_c}'")
            return 1

        _mv = _rl.get("HIDDEN_MOVE", {})
        _moved, _nofit_reach = [], []
        # 블롭 안의 빈 구멍 — 사정거리 밖 레코드를 여기에 놓는다.
        _cov = bytearray(len(orig))
        for _rr in list(doc["records"]) + json.loads(
                (ROOT / "translation" / "mbankb_hidden_ledger.json")
                .read_text(encoding="utf-8"))["records"]:
            for _k in range(_rr["offset"], min(_rr["end"], len(orig))):
                _cov[_k] = 1
        for _a, _b in mbankb_href_mod.slot_spans(orig):
            for _k in range(_a, min(_b, len(orig))):
                _cov[_k] = 1
        _reftargets = {_t for _s2, _v2 in mbankb_href_mod.tables(bytes(data))
                       for _a2, _vv2, _t in _v2}
        _freeholes, _k = [], 0
        while _k < len(orig):
            if not _cov[_k]:
                _j = _k
                while _j < len(orig) and not _cov[_j]:
                    _j += 1
                if _j - _k >= 8:
                    _freeholes.append((_k, _j - _k))
                _k = _j
            else:
                _k += 1
        # 상한. 예전엔 「간헐 결함이 무서워서」 34 로 묶어 뒀는데, 그 결함의 정체가
        # 밝혀졌다 — `{C:01}{A}` 오프셋이 **s16** 이라 32,767 을 넘기면 게임이 음수로
        # 읽어 블롭 앞으로 튕긴다(2026-09-12 확정). 이제 사정거리 검사와 재연결 게이트가
        # 그걸 기계적으로 막으므로, 이 숫자는 「생각보다 많이 옮기고 있지 않은가」를
        # 알려 주는 눈금일 뿐이다. 늘릴 때는 실기 확인을 함께 한다.
        _floor = int(os.environ.get("SRW4S_MB_MOVE_FLOOR", "37"))
        if len(_mv) > _floor:
            print(f"FAIL 참조 이동 {len(_mv)}건 > 런타임 PASS floor {_floor}건 "
                  f"(QA 표준 8.3.1). SRW4S_MB_MOVE_FLOOR 로 명시적으로 올리세요")
            return 1
        if _mv:
            import mbankb_href
            # 원장 둘 다 뒤진다 — 표 밖(BH:)뿐 아니라 표 안(BB:) 레코드도
            # `{C:01}{A}` 참조로 닿는 경우가 있다(BB:0D0A7 은 슬롯 8개 + 참조 1곳).
            _hid2 = json.loads((ROOT / "translation" /
                                "mbankb_hidden_ledger.json").read_text(encoding="utf-8"))
            _hby = {r["id"]: r for r in _hid2["records"]}
            _hby.update({r["id"]: r for r in doc["records"]})
            # **사정거리가 빠듯한 것부터** 구멍을 준다. 그냥 사전 순으로 주면
            # 여유 있는 레코드가 좋은 구멍을 먼저 차지해, 정작 빠듯한 것이 밀려난다
            # (2026-09-12: BH:0631C 이 1,313 B 차이로 밀렸다).
            def _reach_key(_it):
                _r0 = _hby.get(_it[0])
                if not _r0:
                    return (1 << 30)
                _rf = mbankb_href.refs_to(bytes(data), _r0["offset"])
                return mbankb_href.reach(_rf)[1] if _rf else (1 << 30)

            for _rid, _ko in sorted(_mv.items(), key=_reach_key):
                _r = _hby.get(_rid)
                if not _r:
                    print(f"FAIL 표밖 이동 {_rid}: 원장에 없다")
                    return 1
                _nb = encode(_ko, enc)
                _at = len(data)
                # **s16 사정거리 검사.** 참조는 자기 위치 기준 s16 이라 32,767 까지만
                # 앞을 볼 수 있다. 블롭 끝이 멀어지면 앞쪽 참조가 못 닿고, 그러면
                # 게임이 음수로 읽어 블롭 **앞으로** 튕겨 나간다
                # (2026-09-10 실측: 스테이지 14 닥터 헬/브로큰 백작 공격 시 멈춤).
                _refs = mbankb_href.refs_to(bytes(data), _r["offset"])
                if not _refs:
                    print(f"FAIL 표밖 이동 {_rid}: 가리키는 참조가 없다")
                    return 1
                _lo, _hi = mbankb_href.reach(_refs)
                if _at > _hi:
                    # 블롭 끝이 사정거리 밖이면 **가까운 빈 구멍**에 놓는다.
                    # 구멍 = 원장이 안 덮고 슬롯표도 아닌 자리 중, 재배치가 아직
                    # 안 건드린 곳(원본과 바이트가 같으면 안 쓴 것이다).
                    _spot = None
                    for _hi2, (_ha, _hn) in enumerate(_freeholes):
                        if _hn < len(_nb) or not (_lo < _ha <= _hi):
                            continue
                        if bytes(data[_ha:_ha + _hn]) != orig[_ha:_ha + _hn]:
                            continue
                        # **이미 남이 가리키는 자리는 안 된다.** 원장이 안 덮는 구멍이어도
                        # 참조 대상일 수 있다(중간 별칭 등). 그러면 내 레코드가 그 참조에도
                        # 걸려 엉뚱한 대사가 뜬다 — 최종 검사가 참조 수 불일치로 잡아낸다.
                        if any(_ha <= _t < _ha + len(_nb) for _t in _reftargets):
                            continue
                        _spot = (_hi2, _ha, _hn)
                        break
                    if _spot is None:
                        _nofit_reach.append((_rid, _at - _hi, _ko))
                        continue
                    _i, _ha, _hn = _spot
                    _at = _ha
                    data[_ha:_ha + len(_nb)] = _nb
                    _freeholes[_i] = (_ha + len(_nb), _hn - len(_nb))
                    try:
                        _n = mbankb_href.repoint(data, _r["offset"], _at)
                    except ValueError as e:
                        print(f"FAIL 표밖 이동 {_rid}: {e}")
                        return 1
                    _moved.append((_rid, _r["offset"], _at, _nb, _n))
                    for _ra in _refs:
                        _reref.append((_ra, _at - _ra))
                    print(f"표 밖 이동(구멍): {_rid} 0x{_r['offset']:05X}"
                          f" -> 0x{_at:05X}({len(_nb)}B) / 참조 {_n}곳  {_ko}")
                    continue
                data += _nb
                try:
                    _n = mbankb_href.repoint(data, _r["offset"], _at)
                except ValueError as e:
                    print(f"FAIL 표밖 이동 {_rid}: {e}")
                    return 1
                if _n == 0:
                    print(f"FAIL 표밖 이동 {_rid}: 가리키는 참조가 없다")
                    return 1
                # 게이트: 새 자리에서 읽으면 정말 그 역문인가
                _end = data.find(bytes([0xFF]), _at) + 1
                if bytes(data[_at:_end]) != _nb:
                    print(f"FAIL 표밖 이동 {_rid}: 새 자리 내용이 다르다")
                    return 1
                _moved.append((_rid, _r["offset"], _at, _nb, _n))
                for _ra in _refs:
                    _reref.append((_ra, _at - _ra))
                print(f"표 밖 이동: {_rid} 0x{_r['offset']:05X}({_r['end']-_r['offset']}B)"
                      f" -> 0x{_at:05X}({len(_nb)}B) / 참조 {_n}곳 재연결  {_ko}")

            # 게이트: **전부 붙인 뒤 다시 본다.** 붙이는 순간의 검사는 그 뒤에 일어나는
            # 덮어쓰기를 못 잡는다 — repoint 는 매번 블롭 전체를 다시 훑으므로 나중 항목이
            # 앞 항목의 바이트를 건드릴 수 있다. 옛 자리를 가리키는 참조가 남았는지,
            # 새 자리의 내용이 그대로인지, 참조 수가 맞는지 셋 다 확인한다.
            _bad = []
            for _rid, _old, _at, _nb, _n in _moved:
                if bytes(data[_at:_at + len(_nb)]) != _nb:
                    _bad.append(f"{_rid}: 새 자리 0x{_at:05X} 내용이 나중에 덮였다")
                _left = mbankb_href.refs_to(bytes(data), _old)
                if _left:
                    _bad.append(f"{_rid}: 옛 자리 0x{_old:05X} 를 가리키는 참조 {len(_left)}곳 남음")
                _now = mbankb_href.refs_to(bytes(data), _at)
                if len(_now) != _n:
                    _bad.append(f"{_rid}: 새 자리 참조 {len(_now)}곳 (재연결한 {_n}곳과 다름)")
            if _bad:
                for _m in _bad[:12]:
                    print("FAIL 표 밖 이동 최종 검사 — " + _m)
                return 1
            if _nofit_reach:
                print(f"  s16 사정거리 밖이라 못 옮긴 것 {len(_nofit_reach)}건:")
                for _rid, _over, _ko in _nofit_reach[:10]:
                    print(f"     {_rid}  {_over} B 초과  {_ko}")
            print(f"  표 밖 이동 최종 검사 통과: {len(_moved)}건 / "
                  f"참조 {sum(m[4] for m in _moved)}곳")

        used = sum(1 for i, (a, b) in enumerate(zip(tail, extbytes)) if a != b)
        # BATTLE 오버레이의 확장 구간은 **원래 블롭 크기(55,353)** 기준으로 놓인다.
        # 블롭을 키우면 len(data) 가 커지지만 오버레이 쪽 오프셋은 그대로여야 하므로,
        # 앞부분(블롭이 자란 만큼)은 오버레이 원본 바이트를 그대로 채워 넣는다.
        # 그래야 build_battle_ko.py 의 "읽히는 앞 512 B" 검사가 유지된다.
        _head = battle[BATTLE_OFF:BATTLE_OFF + (blob - len(orig))]
        OUT_EXT.write_bytes(_head + extbytes)
        print(f"레코드 재배치: {mv}개" + (f" / 자리 없음 {len(nofit)}개" if nofit else ""))
        if nofit:
            # 무엇이 못 들어갔는지 보여 준다 — RELOC_RESERVE 를 얼마나 더 줄지 판단용
            for _i in nofit[:12]:
                _r = _byid.get(_i)
                _q = (_r["jp"] if _r else "")[:44]
                print(f"     {_i}  {_q}")
        print(f"  확장 구간 {EXT_LO:,}..{EXT_END:,} (BATTLE 0x{BATTLE_OFF:X}~) 에 {used:,} B 사용"
              f" / 여유 {EXT_END - EXT_LO - used:,} B")
        print(f"  블롭도 {blob:,} -> {len(data):,} B 로 키워 두 사본에 같이 둔다")
        # 게이트: **2차 해제본은 고정 버퍼에 풀린다.** 넘기면 뒤를 덮어 게임이 멈춘다.
        # 한계는 프로브 실측이다(MAX_BLOB 주석 참조) — 이분법으로 얻은 57,896 은
        # 크기와 내용을 같이 흔든 잘못된 결론이었다. u16 한계(65,535)와 압축 예산을
        # 통과해도 여기서 걸린다.
        if len(data) > MAX_BLOB:
            print(f"FAIL 블롭 {len(data):,} B > 상한 {MAX_BLOB:,} B "
                  f"(실측 안전선). RELOC_RESERVE 를 줄이거나 항목을 덜어내세요")
            return 1

    # 게이트: **재연결한 참조는 전부 s16 안이어야 한다.**
    # 블롭 전체를 훑는 방식은 못 쓴다 — 한글은 2바이트 코드가 0xEF~0xF5 로 시작해서
    # u16 으로 읽으면 항상 32,767 을 넘고, 레코드 본문 안의 `{C:01}{A}` 도 표로 잡힌다.
    # 그래서 **repoint 가 실제로 쓴 자리만** 본다 (2026-09-10: 전수 스캔이 오탐 178건).
    _ovf = [(a, d) for a, d in _reref if d > mbankb_href_mod.S16MAX]
    if _ovf:
        print(f"FAIL 재연결한 참조 {len(_ovf)}건이 s16 범위(32,767)를 넘었다")
        for _a, _d in _ovf[:10]:
            print(f"     u16@{_a} delta {_d}  (s16 으로 {_d - 0x10000})")
        return 1

    data = bytes(data)
    assert len(data) >= len(orig), "크기가 줄었다"
    changed = sum(1 for a, b in zip(data, orig) if a != b)
    (ROOT / "build" / ("M_BANKB_ko_noext.dec" if NOEXT else "M_BANKB_ko.dec")).write_bytes(data)

    # 키 레코드 런은 **키 훑기**로 닿는다. 시작 오프셋이 밀리면 화면에 색인
    # 바이트가 글자로 찍힌다 — v0.99e/f 가 이걸로 깨졌다.
    # [2026-09-12 정정] "슬롯도 점프도 안 가리킨다" 는 틀렸다 — `{C:07}` 점프가
    #   런 0x0AC01 의 0x0C8F8·0x0C908 을 가리킨다. 선언된 이동
    #   (KEYRUN_SHIFT)은 봐주고 레코드 수·키 순서는 그대로 강제한다.
    from verify_mb_keyrun import check as _keyrun_check
    _nrun, _nrec, _bad, _mv = _keyrun_check(bytes(orig), data)
    if _bad:
        print(f"FAIL 키 런 {_nrun}개({_nrec:,}레코드)가 원본과 어긋났다")
        for _m in _bad[:10]:
            print("   ", _m)
        return 1
    if _mv:
        print(f"  선언된 자리 이동 {len(_mv)}건 허용: {', '.join(_mv)}")
    print(f"키 런 {_nrun}개 / 레코드 {_nrec:,}개: 키 순서 원본과 일치")

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
    # 이 빌드는 **환경변수로만** 조절한다(SRW4S_MB_NOEXT / _RESERVE / _MAXBLOB /
    # _AUTOMOVE / _AUTOFULL / _SHORT). 인자를 받는 곳이 없어서 `--noext` 같은 것을
    # 붙이면 조용히 무시되고, 겉보기엔 성공한 채 **낡은 M_BANKB_ko_noext.dec 로
    # C_BEFCT 가 빌드된다**(2026-09-09 실측: 하루치 텍스트가 사본에 안 실렸다).
    # 그래서 모르는 인자는 받지 않고 여기서 멈춘다.
    if sys.argv[1:]:
        print("FAIL 이 빌드는 인자를 받지 않는다: " + " ".join(sys.argv[1:]))
        print("     확장 구간 없이 빌드하려면  SRW4S_MB_NOEXT=1 python tools/build_mbankb_ko.py")
        raise SystemExit(2)
    raise SystemExit(main())
