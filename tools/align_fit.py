#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""위상 민감 앵커 앞 런의 advance/phase 정렬.

렌더러는 반칸 단위로 진행한다: low 글리프(<0x100)는 1, 전각 글리프는 1+phase를 먹고 phase를
토글한다. FC/F8 같은 앵커는 그 위상에 민감하다(도너 `third_align_overrides.py` 문서화).

역문 런은 원문 런과 (advance, 도달 phase)가 같아야 안전하다.
  * 짧으면 채운다 — 반각 공백 `0x000`(+1, 위상 불변)과 투명 전각 `0x3FF`(+1+phase, 위상 토글).
  * 길면 채울 방법이 없다. **빌드를 실패시킨다**(fail closed) — 조용히 창 밖으로 그리게 두지 않는다.
"""
from __future__ import annotations

LOW_SPACE = 0x000        # 빈 8x16 반각
BLANK_FW = 0x3FF         # 투명 전각 (원문 폰트의 전각 공백)


def sig(ids, phase: int = 0) -> tuple[int, int]:
    adv = 0
    for i in ids:
        if i < 0x100:
            adv += 1
        else:
            adv += 1 + phase
            phase ^= 1
    return adv, phase


def pad_to(ids: list[int], phase: int, target_adv: int, target_phase: int):
    """런 뒤에 붙일 패딩 글리프 ID 목록. 못 맞추면 None."""
    adv, ph = sig(ids, phase)
    if adv > target_adv:
        return None
    pad: list[int] = []
    if ph != target_phase:
        cost = 1 + ph                      # 전각 하나로 위상을 뒤집는다
        if adv + cost > target_adv:
            return None
        pad.append(BLANK_FW)
        adv += cost
        ph ^= 1
    if adv < target_adv:
        pad.extend([LOW_SPACE] * (target_adv - adv))   # 반각은 위상을 안 건드린다
        adv = target_adv
    return pad if (adv == target_adv and ph == target_phase) else None


def phase_fix(ids: list[int], phase: int, target_phase: int):
    """위상만 맞춘다.

    FC/F8 같은 앵커는 **절대 좌표를 인수로 싣는다**(예: `FC 281D`). 따라서 앞선 런의
    advance가 뒤 요소의 위치를 밀지 않는다 — 앵커에 정말 민감한 건 반칸 단위 **위상**뿐이다.
    폭까지 맞추려고 패딩하면 바이트만 크게 먹는다(실측 +77B로 슬롯 초과).
    """
    _, ph = sig(ids, phase)
    if ph == target_phase:
        return []
    return [BLANK_FW]          # 투명 전각 하나로 위상을 뒤집는다
