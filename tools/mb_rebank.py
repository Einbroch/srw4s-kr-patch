#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M_BANKS 재뱅킹 재삽입기 (창 단위 토큰 검증 풀).

왜 재뱅킹인가
  포인터가 **뱅크 상대 u16**이라 테이블과 그 테이블이 가리키는 레코드는 같은 64KiB 창에
  있어야 한다. 원본은 뱅크가 꽉 찬 데다 정본 레코드끼리 겹쳐 있어 제자리 증량이 불가능하다.
  그래서 `테이블 + 그 테이블이 참조하는 모든 레코드`를 한 단위로 묶어 창에 다시 담는다.

왜 풀인가 (이게 없으면 파일이 493KB -> 664KB로 부푼다)
  단순 재배치는 원본이 갖고 있던 중첩을 전부 잃는다. 같은 창 안에서는
    - 완전히 같은 바이트열은 한 번만 두고
    - 어떤 레코드의 **토큰 경계**에서 시작해 끝까지 일치하면 그 안을 가리킨다(접미 공유).
  후보 위치를 토큰 시작점으로만 제한하는 게 핵심이다. 가변 길이 토큰이라 경계가 아닌
  곳에서 시작하면 파싱이 어긋난다. 각 레코드는 자기 종단 FF를 포함하므로 경계에서
  바이트가 일치하면 읽기 결과도 정확히 같다.

별칭(원본 접미 공유) 처리
  별칭도 그냥 자기 바이트열(별칭 시작 ~ 종단)을 가진 하나의 대상으로 넣는다.
  부모가 미번역이면 별칭 바이트열은 부모의 꼬리와 같으므로 접미 공유가 알아서 흡수한다.
  부모가 번역됐으면 대응 꼬리를 알 수 없으니 원문 바이트로 따로 남는다(원문 표시 유지).

레이아웃
  [61개 u32 헤더][창0][창1]...   각 창은 64KiB 경계 정렬, 창 안 = [테이블들][풀]
  헤더 엔트리 = 그 테이블의 새 파일 오프셋. 뱅크 베이스 = 오프셋 & ~0xFFFF.
"""
from __future__ import annotations
import hashlib, json, struct, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mb_codec import build_encoder, encode      # noqa: E402

SRC = ROOT / "extract" / "DAT" / "M_BANKS.BIN"
LEDGER = ROOT / "translation" / "mbanks_ledger.json"
OUT = ROOT / "build" / "M_BANKS_ko.BIN"
WIN = 0x10000
PREFIX = 4
ARITY = {0xF6: 0, 0xF7: 0, 0xF8: 1, 0xF9: 1, 0xFA: 0, 0xFB: 2, 0xFC: 2, 0xFD: 2, 0xFE: 1}


def tok_end(buf: bytes, start: int, limit: int):
    p = start
    while p < limit:
        b = buf[p]
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


def token_offsets(rec: bytes) -> list[int]:
    """레코드 안에서 토큰이 시작하는 오프셋들. 파싱이 어긋나면 빈 목록."""
    out, p = [], 0
    n = len(rec)
    while p < n:
        out.append(p)
        b = rec[p]
        if b == 0xFF:
            return out if p + 1 == n else []
        if b < 0xF0:
            p += 1
        elif b <= 0xF5:
            p += 2
        else:
            a = ARITY.get(b)
            if a is None:
                return []
            p += 1 + a
    return []


class Pool:
    """창 버퍼에 직접 덧붙이며 창 상대 오프셋으로 색인한다."""

    def __init__(self, buf: bytearray, lead: int = 0) -> None:
        self.buf = buf
        self.lead = lead
        self.index: dict[bytes, list[int]] = defaultdict(list)
        self.exact: dict[bytes, int] = {}
        self.reused = 0
        self.saved = 0

    def _register(self, at: int, rec: bytes) -> None:
        """at 은 창 상대 오프셋. buf 색인은 at-lead 로 본다."""
        for t in token_offsets(rec):
            # 키는 레코드 자신의 접미사에서 뽑는다(버퍼에서 읽으면 끝을 넘어간다).
            self.index[rec[t:t + PREFIX]].append(at + t)
        self.exact.setdefault(rec, at)

    def place(self, rec: bytes) -> int:
        hit = self.exact.get(rec)
        if hit is not None:
            self.reused += 1
            self.saved += len(rec)
            return hit
        for off in self.index.get(rec[:PREFIX], ()):
            if self.buf[off - self.lead:off - self.lead + len(rec)] == rec:
                self.exact[rec] = off
                self.reused += 1
                self.saved += len(rec)
                return off
        at = self.lead + len(self.buf)
        self.buf += rec
        self._register(at, rec)
        return at


def pack(units: list[dict], lead: int = 0) -> tuple[bytearray, dict, dict, Pool]:
    """단위 목록을 한 창으로 담아본다. (버퍼, 창상대 테이블오프셋, 창상대 배치, 풀)

    lead = 창 시작부터 buf 가 놓이는 지점까지의 바이트 수(창0의 헤더 등).
    """
    buf = bytearray()
    tbl_off = {}
    for u in units:
        tbl_off[u["tbl"]] = lead + len(buf)
        buf += bytes(0x200)
    pool = Pool(buf, lead)
    items: dict[int, bytes] = {}
    for u in units:
        items.update(u["items"])
    place = {}
    for t in sorted(items, key=lambda x: (-len(items[x]), x)):
        place[t] = pool.place(items[t])
    return buf, tbl_off, place, pool


def main() -> int:
    d = SRC.read_bytes()
    L = json.loads(LEDGER.read_text(encoding="utf-8"))
    enc = build_encoder()
    first = struct.unpack_from("<I", d, 0)[0]
    offsets = list(struct.unpack_from(f"<{first // 4}I", d, 0))

    canon = {r["offset"]: r for r in L["records"]}

    blob: dict[int, bytes] = {}
    ntr = 0
    identity = "--identity" in sys.argv
    for r in L["records"]:
        if r["ko"] and not identity:
            try:
                blob[r["offset"]] = encode(r["ko"], enc)
                ntr += 1
            except KeyError as e:
                print(f"FAIL: {r['id']} 인코딩 불가 {e.args[0]!r}")
                return 1
        else:
            blob[r["offset"]] = bytes.fromhex(r["raw_hex"])

    units = []
    for bi, off in enumerate(offsets):
        if not off or off + 0x200 > len(d):
            continue
        base = off & ~0xFFFF
        rels = list(struct.unpack_from("<256H", d, off))
        items: dict[int, bytes] = {}
        for rel in rels:
            t = base + rel      # rel==0 도 원본이 실제 대상으로 읽는다 (건너뛰면 회귀)
            if t in blob:
                items.setdefault(t, blob[t])
            else:
                e = tok_end(d, t, min(t + 0x400, len(d)))
                v = d[t:e] if e else d[t:t + 2]
                # 원본 파일 끝을 넘는 대상 = 원래도 죽은 슬롯. 길이 0으로 두면
                # 새 파일 EOF를 가리키게 되니 종단 하나를 준다(원본보다 안전).
                items.setdefault(t, v if v else bytes([0xFF]))
        units.append({"tbl": bi, "off": off, "base": base, "rels": rels, "items": items})

    for u in units:
        b, _, _, _ = pack([u])
        u["solo"] = len(b)
    big = max(u["solo"] for u in units)
    if big > WIN:
        print(f"FAIL: 단위 하나가 창을 넘는다 ({big} > {WIN})")
        return 1

    # 창 구성: 원래 뱅크가 같던 단위끼리 겹칠 확률이 높으니 그 순서로 채운다.
    rest = sorted(units, key=lambda x: (x["base"], x["tbl"]))
    wins: list[list[dict]] = []
    while rest:
        lead = first if not wins else 0
        cur: list[dict] = []
        left = []
        for u in rest:
            trial = cur + [u]
            if lead + len(pack(trial, lead)[0]) <= WIN:
                cur = trial
            else:
                left.append(u)
        if not cur:
            print("FAIL: 남은 단위를 어떤 창에도 못 넣는다")
            return 1
        wins.append(cur)
        rest = left

    out = bytearray(d[0:first])
    header = list(offsets)
    reused = saved = 0
    for wi, w in enumerate(wins):
        if wi:
            while len(out) % WIN:
                out.append(0)
        base = len(out) & ~0xFFFF      # 창0의 베이스는 0 — 헤더와 같은 64KiB를 쓴다
        lead = len(out) - base
        buf, tbl_off, place, pool = pack(w, lead)
        reused += pool.reused
        saved += pool.saved
        for u in w:
            tbl = [0] * 256
            for i, rel in enumerate(u["rels"]):
                tbl[i] = place[u["base"] + rel]
            struct.pack_into("<256H", buf, tbl_off[u["tbl"]] - lead, *tbl)
            header[u["tbl"]] = base + tbl_off[u["tbl"]]
        out += buf
    struct.pack_into(f"<{len(header)}I", out, 0, *header)

    OUT.parent.mkdir(exist_ok=True)
    dst = OUT.with_name("M_BANKS_identity.BIN") if identity else OUT
    dst.write_bytes(bytes(out))
    print(f"단위 {len(units)}개 -> 창 {len(wins)}개")
    print(f"역문 레코드 {ntr:,}")
    print(f"공유 재사용 {reused:,}회 / 절약 {saved:,}B")
    print(f"크기 {len(d):,} -> {len(out):,} B ({len(out)/WIN:.1f}창, {(len(out)+2047)//2048}섹터)")
    print(f"-> {dst.name}  sha {hashlib.sha256(bytes(out)).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
