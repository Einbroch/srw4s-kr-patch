#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 재뱅킹 v4 — 표마다 자기 사본, 마스크 제거 훅 전용.

전제: `patch_mbanks_hook.py` 로 `base = header[bank] & 0xFFFF0000` 의 마스크를 없앤 상태.
      즉 `base = header[bank]` = **표가 놓인 자리**.

배치
  뱅크 하나 = `[표 0x200][그 표가 읽는 구간들]` 을 통째로 이어 붙인 독립 블록이다.
  표가 자기 블록 맨 앞에 있으므로 모든 레코드가 표 뒤에 오고 `rel >= 0x200` 이 보장된다.
  블록이 64KiB 를 넘지 않으면 `rel` 이 u16 에 담긴다(실측 최대 39,460 B).

왜 사본인가
  표끼리 구간을 공유하려면 공유 구간이 **모든 관련 표보다 뒤에** 있어야 하고, 그러면 창이
  64KiB 를 넘어 버린다(원본이 이미 64KiB 를 꽉 채워 쓰고 있다). 사본은 공간을 더 쓰지만
  제약이 단순하고, 종단까지만 보존하면 546,482 B(267섹터)로 디스크에 들어간다.

보존 범위
  각 포인터에서 **레코드 종단(FF)까지**. v2 에서 0x200 만 보존했다가 실패했는데, 원인은
  이어읽기가 아니라 **레코드 최대 길이가 1024 B** 여서였다(512 B 초과 레코드 521개).
  종단을 못 찾는 포인터(180개)는 안전하게 0x400 을 보존한다.
"""
from __future__ import annotations
import hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 2, 0xFD: 2, 0xFE: 1}
LIMIT = 0x10000

# **원본 배치를 그대로 보존해야 하는 뱅크.**
# 맵 스크립트는 레코드 사이를 `s16` 상대 오프셋으로 건너뛴다(MAP 0x801525E8 등).
# 런을 병합해 다시 채우면 레코드 간 거리가 바뀌어 그 점프가 엉뚱한 데로 간다 —
# 전함 발진에서 게임이 에러 트랩(무한 루프)에 빠졌다.
# 이 뱅크들은 원본 구간을 통째로 복사하고, 역문은 **원문 길이 안에서 제자리 치환**한다
# (남는 자리는 0으로 채운다 — 종결자 뒤라 화면에 안 나온다).
# 슬롯은 전부 같은 상수만큼 옮기므로 상대 거리가 보존된다.
KEEP_LAYOUT = {30}

# **슬롯이 아니라 스크립트 점프로만 도달하는 레코드.**
# 원장은 표 슬롯이 가리키는 것만 담으므로 이것들은 추출조차 안 됐고, 화면에는
# 일본어로 떴다(발진 대사). 배치 보존 뱅크 안에 있으니 원문 길이 안에서 제자리 치환한다.
KEEP_PATCH = {
    0x0CE39: "{C:05}「{C:06} 발진!」",
    0x0CE52: "{C:05}「{C:06} 고!」",
    0x0CFEB: "「{C:06} 가요!」",
    0x0CFF6: "「{C:06} 간다!」",
    0x0D001: "「{C:06} 갑니다!」",
    0x0D00F: "「{C:06}갈까」",
    0x0D018: "「{C:06} 갑니다」",
    0x0D024: "「{C:06}간다」",
    0x0D02D: "「{C:06} 발진!!」",
    0x0D058: "「{C:06} 가요!」",
    0x0D063: "「{C:06} 간다!」",
    0x0D06E: "「{C:06} 갑니다!」",
    0x0D07C: "「{C:06}갈까」",
    0x0D085: "「{C:06} 갑니다」",
    0x0D091: "「{C:06}간다」",
    0x0D09A: "「{C:06} 발진!!」",
}
INNER: dict[int, list[tuple[int, bool]]] = {}
ALIAS_TR: dict[int, tuple[bytes, int]] = {}
ALIAS_PARENT: dict[int, int] = {}
ALIAS_KO: dict[int, tuple[bytes, int]] = {}
TRANS: dict = {}
ENC: dict = {}


def tok_end(d: bytes, s: int):
    p, lim = s, min(s + 0x400, len(d))
    while p < lim:
        b = d[p]
        if b == 0xFF:
            return p + 1
        if b < 0xF0:
            p += 1
        elif b <= 0xF5:
            p += 2
        else:
            a = ARITY.get(b)
            if a is None:
                return None
            p += 1 + a
    return None


DEAD_ALIAS: dict = {}
try:
    import runpy as _rp
    DEAD_ALIAS = _rp.run_path(
        str(ROOT / "translation" / "mbanks_dead_alias.py"))["DEAD"]
except Exception:
    pass


def load_translations(d: bytes, targets: set[int]):
    """번역할 레코드의 새 바이트와, 레코드 **안쪽**을 가리키는 별칭 포인터 목록.

    별칭은 접미사 공유다 — 번역문으로 덮으면 그 포인터가 읽는 내용이 달라진다.
    예전에는 그런 레코드의 번역을 통째로 버렸는데(전체의 12.9%), 지금은 번역문을
    싣고 별칭에는 **원문 접미사 사본**을 따로 붙여 원래 내용을 그대로 읽게 한다.
    """
    from mb_codec import build_encoder, encode
    from mb_alias import ko_alias_offsets
    global ENC
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()
    out, inner, alias_tr, parent, alias_ko, skip, nal = {}, {}, {}, {}, {}, 0, 0
    for r in L["records"]:
        if not r["ko"]:
            continue
        t = r["offset"]
        raw = bytes.fromhex(r["raw_hex"])
        try:
            out[t] = (encode(r["ko"], enc), len(raw))
        except KeyError:
            skip += 1
            continue
        q = sorted(x for x in targets if t < x < t + len(raw))
        if q:
            # 번역해도 **앞부분이 그대로면** 그 안의 별칭은 같은 상대 위치로 보내면 된다.
            # (바이너리 앞머리 + 대사 꼬리로 된 레코드가 여기 해당한다 — 마징가 컷인 등)
            nb = out[t][0]
            cpl = 0
            while cpl < min(len(raw), len(nb)) and raw[cpl] == nb[cpl]:
                cpl += 1
            inner[t] = [(x, (x - t) <= cpl) for x in q]
            # 앞머리 **밖**이라도 `「`·{P}·{N} 같은 구조 경계에 붙은 별칭은
            # 역문의 같은 자리로 옮긴다 (화자 생략판·다음 문단판).
            kmap = ko_alias_offsets(r["jp"], r["ko"], enc)
            for x in q:
                rel = x - t
                parent[x] = t
                if rel > cpl and rel in kmap:
                    alias_ko[x] = (nb[kmap[rel]:], len(raw) - rel, kmap[rel])
                if rel <= cpl:
                    # 그 표 블록에 정본 시작이 없고 **별칭만** 있는 경우가 있다
                    # (H04:E0000 -> 0x05189). 그때도 역문을 읽게 하려면 따로 등록해야 한다.
                    alias_tr[x] = (nb[rel:], len(raw) - rel)
            nal += len(q)
    global ENC
    ENC = enc
    print(f"번역 적용 대상 {len(out)}개 / 인코딩 불가로 제외 {skip}")
    print(f"  별칭 포인터 {nal}개 ({len(inner)}개 레코드) -> 원문 접미사 사본으로 보존")
    print(f"  그중 {len(alias_ko)}개는 역문의 같은 구조 자리로 옮긴다")
    return out, inner, alias_tr, parent, alias_ko


def main() -> int:
    from mb_codec import encode
    d = SRC.read_bytes()
    first = struct.unpack_from("<I", d, 0)[0]
    offs = list(struct.unpack_from(f"<{first // 4}I", d, 0))
    live = [i for i, o in enumerate(offs) if o and o + 0x200 <= len(d)]

    targets = set()
    for bi in live:
        b0 = offs[bi] & 0xFFFF0000
        for rel in struct.unpack_from("<256H", d, offs[bi]):
            if b0 + rel < len(d):
                targets.add(b0 + rel)
    # 안 쓰는 표 칸이 만들어 낸 가짜 별칭은 뺀다
    # (translation/mbanks_dead_alias.py — 선언한 것만).
    if DEAD_ALIAS:
        n0 = len(targets)
        targets -= set(DEAD_ALIAS)
        if n0 != len(targets):
            print(f"  가짜 별칭 {n0 - len(targets)}개 제외 (선언 목록)")
    global TRANS, INNER, ALIAS_TR, ALIAS_PARENT, ALIAS_KO
    TRANS, INNER, ALIAS_TR, ALIAS_PARENT, ALIAS_KO = (
        load_translations(d, targets) if "--tr" in sys.argv else ({}, {}, {}, {}, {}))

    out = bytearray(d[0:first])
    header = list(offs)
    worst = 0
    for bi in live:
        base = offs[bi] & 0xFFFF0000
        rels = list(struct.unpack_from("<256H", d, offs[bi]))
        rs = []
        for rel in rels:
            t = base + rel
            if t >= len(d):
                continue
            e = tok_end(d, t)
            rs.append((t, e if e else min(t + 0x400, len(d))))
        rs.sort()
        runs: list[list[int]] = []
        for a, b in rs:
            if runs and a <= runs[-1][1]:
                runs[-1][1] = max(runs[-1][1], b)
            else:
                runs.append([a, b])
        if bi in KEEP_LAYOUT:
            lo = min(a for a, _b in rs)
            hi = max(b for _a, b in rs)
            blk = len(out)
            header[bi] = blk
            out += bytes(0x200)              # 표는 블록 맨 앞
            body = bytearray(d[lo:hi])
            for t, ko in KEEP_PATCH.items():
                if not (lo <= t < hi):
                    continue
                e = d.find(bytes([0xFF]), t) + 1
                nb = encode(ko, ENC)
                if len(nb) > e - t:
                    print(f"FAIL: 0x{t:X} 역문 {len(nb)}B > 원문 {e - t}B")
                    return 1
                body[t - lo:t - lo + (e - t)] = nb + bytes(e - t - len(nb))
            for t, (nb, olen) in TRANS.items():
                if lo <= t and t + olen <= hi:
                    if len(nb) > olen:
                        print(f"FAIL: 표{bi} 0x{t:X} 역문 {len(nb)}B > 원문 {olen}B "
                              f"(배치 보존 뱅크는 원문 안에 들어가야 한다)")
                        return 1
                    body[t - lo:t - lo + olen] = nb + bytes(olen - len(nb))
            out += body
            new = [0] * 256
            for k, rel in enumerate(rels):
                t = base + rel
                new[k] = (t - lo + 0x200) if lo <= t < hi else 0
            struct.pack_into("<256H", out, blk, *new)
            worst = max(worst, len(out) - blk)
            print(f"  표{bi}: 원본 배치 보존 ({hi - lo:,}B, 슬롯 상대거리 유지)")
            continue

        blk = len(out)
        header[bi] = blk
        out += bytes(0x200)                  # 표는 블록 맨 앞
        # 구간을 훑으며 번역 레코드는 새 바이트로 갈아 끼운다. 길이가 달라지면 뒤가 밀리는데,
        # 포인터는 어차피 전부 다시 계산하므로 문제되지 않는다.
        moved: dict[int, int] = {}           # 원본 오프셋 -> 새 위치
        for a, b in runs:
            q = a
            while q < b:
                moved[q] = len(out)
                at = ALIAS_TR.get(q)
                if at and q + at[1] <= b:
                    startpos = len(out)
                    out += at[0]            # 정본 시작이 이 블록에 없는 별칭
                    par = ALIAS_PARENT.get(q)
                    if par is not None:
                        pend = par + TRANS[par][1]
                        for q2, inpref in INNER.get(par, ()):
                            if not q < q2 < q + at[1]:
                                continue
                            if inpref:
                                moved[q2] = startpos + (q2 - q)
                            else:
                                k2 = ALIAS_KO.get(q2)
                                moved[q2] = len(out)
                                out += k2[0] if k2 else d[q2:pend]
                    q += at[1]
                    continue
                ak = ALIAS_KO.get(q)
                if ak and q + ak[1] <= b and q not in TRANS:
                    # 이 블록에는 정본 시작이 없고 **옮긴 별칭**만 있다
                    out += ak[0]
                    par = ALIAS_PARENT.get(q)
                    if par is not None and par in TRANS:
                        pend = par + TRANS[par][1]
                        for q2, _ip in INNER.get(par, ()):
                            if not q < q2 < q + ak[1]:
                                continue
                            k2 = ALIAS_KO.get(q2)
                            moved[q2] = len(out)
                            out += k2[0] if k2 else d[q2:pend]
                    q += ak[1]
                    continue
                tr = TRANS.get(q)
                if tr and q + tr[1] <= b:
                    startpos = len(out)
                    out += tr[0]
                    for q2, inpref in INNER.get(q, ()):
                        if inpref:
                            moved[q2] = startpos + (q2 - q)   # 안 바뀐 앞부분 안
                            continue
                        k2 = ALIAS_KO.get(q2)
                        if k2:
                            # 옮길 자리를 아는 별칭은 **방금 써 넣은 역문 안**을
                            # 가리킨다. 예전에는 같은 바이트를 한 벌 더 붙였다.
                            moved[q2] = startpos + k2[2]
                            continue
                        moved[q2] = len(out)                  # 원문 접미사 사본
                        out += d[q2:q + tr[1]]
                    q += tr[1]
                else:
                    out.append(d[q])
                    q += 1
        new = [0] * 256
        for k, rel in enumerate(rels):
            t = base + rel
            if True:
                at = moved.get(t)
                if at is not None:
                    v = at - blk
                    if not (0 <= v <= 0xFFFF):
                        print(f"FAIL: 표{bi} 슬롯{k} rel={v} 이 u16 범위 밖")
                        return 1
                    new[k] = v
                else:
                    new[k] = 0
        struct.pack_into("<256H", out, blk, *new)
        worst = max(worst, len(out) - blk)

    struct.pack_into(f"<{len(header)}I", out, 0, *header)
    dst = ROOT / "build" / ("M_BANKS_r4_ko.BIN" if TRANS else "M_BANKS_r4.BIN")
    dst.write_bytes(bytes(out))
    print(f"표 {len(live)}개, 표마다 독립 블록  최대 블록 {worst:,}B (한도 {LIMIT:,})")
    print(f"크기 {len(d):,} -> {len(out):,} B ({(len(out)+2047)//2048}섹터)")
    print(f"-> {dst.name}  sha {hashlib.sha256(bytes(out)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
