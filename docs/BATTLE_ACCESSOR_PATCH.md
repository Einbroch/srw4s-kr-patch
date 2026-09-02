# BATTLE D_NAMES 접근자 패치 — 적용·검증 완료

기준일: 2026-08-23  
상태: **패치 적용·실기 검증 통과 / 뱅킹 실사용은 STAYDAT 재배치가 선행되어야 함**

## 왜 필요했나

같은 `D_NAMES`를 두 오버레이가 **다른 규약**으로 읽었다.

| | MAP `0x80154828` | BATTLE `0x80146EC0` (원본) |
|---|---|---|
| 문자열 베이스 | `base + (header[sec] & 0xFFFF0000)` | `base` |
| 창 | 섹션별 64KiB 뱅킹 | 단일 64KiB 평탄 |

BATTLE 쪽이 평탄해서 `D_NAMES` 전체가 65,536 B로 묶여 있었다. 번역 실측 증가율 1.575배로는
들어가지 않는다(`REINSERTION.md` §1). BATTLE을 MAP에 맞춰 뱅킹하게 고쳤다.

## 무엇을 했나

뱅킹 계약을 지키는 최소 구현이 13워드인데 원본 자리는 11워드뿐이라 트램폴린을 썼다.

```
0x80146EC0   j    0x80164FB8      ; $ra 보존 -> 본체의 jr $ra가 원 호출자로 복귀
0x80146EC4   nop                  ; branch delay slot
             (이하 9워드는 사장, 원본 그대로 둠)

0x80164FB8   lui  $v0, 0x8016
0x80164FBC   lw   $v0, 0x3b74($v0)   ; base
0x80164FC0   sll  $a0, $a0, 2        ; load delay slot
0x80164FC4   addu $a0, $a0, $v0      ; &header[sec]
0x80164FC8   lw   $v1, ($a0)         ; header
0x80164FCC   sll  $a1, $a1, 1        ; load delay slot / entry*2
0x80164FD0   addu $v0, $v0, $v1      ; table = base + header
0x80164FD4   andi $v1, $v1, 0xffff   ; low = header & 0xFFFF
0x80164FD8   addu $a1, $a1, $v0      ; &table[entry]
0x80164FDC   subu $v0, $v0, $v1      ; strbase = table - low = base + (header & 0xFFFF0000)
0x80164FE0   lhu  $v1, ($a1)         ; u16 pointer
0x80164FE4   jr   $ra
0x80164FE8   addu $v0, $v0, $v1      ; branch delay slot / return strbase + pointer
```

`header & 0xFFFF0000 == header - (header & 0xFFFF)`이므로 MAP과 의미가 같다.

본체 자리 `0x80164FB8`은 BATTLE 해제물의 4바이트 정렬된 99바이트 0-run이고 정적 참조가 0건이다.

### 안전장치

- **부분집합 인코더를 신뢰하지 않는다.** `tools/mips_asm.py`가 만든 워드를 capstone으로 되읽어
  기대한 어셈블리와 문자열 비교한다(`assemble_checked`). 불일치면 빌드가 실패한다.
- **load-delay 검사**: `lw`/`lhu` 바로 다음 명령이 그 목적 레지스터를 쓰면 실패시킨다.
- **Expected Write 2건**: 원본 11워드가 정확히 그 명령인지, 본체 자리가 정말 0인지.
- **`j` 대상이 같은 256MiB 영역인지** 확인한다.
- 재압축 후 해제 왕복이 패치본과 바이트 동일한지 확인한다.

## 디스크 반영

`BATTLE.LZB` 재압축본은 `195,867 B`로 원본 `195,439 B`보다 크지만 원래 할당된 **96섹터
(196,608 B) 안에 741 B 여유를 남기고 들어간다**. LBA는 그대로 두고 ISO 디렉터리 레코드의
data length(LE/BE 양쪽)만 갱신했다 — `tools/patch_image_resize.py`.

이 도구는 **무변경 왕복이 원본 이미지와 SHA-256 바이트 동일**함을 먼저 확인하고 썼다.

## 실기 검증 (emucap Mednafen)

1. 패치 이미지가 부팅되고 1화 세이브스테이트에서 정상 진행한다.
2. RAM `0x80164FB8`의 52바이트가 `build/BATTLE_ko.dec`와 **바이트 동일**하고, 디스어셈블이
   의도한 13워드와 일치한다.
3. `0x80164FB8`에 exec 브레이크포인트를 걸자 전투 중 **반복 히트**했다.
   레지스터에 `a0=7`(= 파일럿 약칭 섹션), `a1=200/231`(엔트리)로 들어온다.
4. 전투 전 화면·전투 애니메이션·유닛 목록에서 기체명·파일럿명·무기명이 **패치 전과 동일하게**
   표시된다. 모든 헤더가 아직 `< 0x10000`이라 `& 0xFFFF0000== 0`이므로 동작이 같아야 하고,
   실제로 같았다 — 순수 회귀 시험 통과.

증거: `analysis/emulator/PASS_battle_accessor.png`, `analysis/battle_accessor_patch.json`,
세이브스테이트 `D:\srw4s_poc\state_battle_accessor.mcs`.

### 덤으로 닫힌 게이트 — 재압축 LZB 런타임 소비

이 이미지는 **우리 인코더가 만든 LZB 스트림**을 담고 있고, 게임이 그것을 읽어 해제해
실행했다(전투가 정상 동작). `RUNTIME_CHECKS.md` §4의 "인코더 출력의 런타임 소비"가 닫혔다.
해제기 쪽은 이미 RAM 대조로 확인돼 있었으므로 **LZB 왕복 전 구간이 실기로 증명**됐다.

## 남은 것 — 뱅킹을 실제로 쓰려면

엔진은 이제 뱅킹을 받아들이지만 **데이터를 놓을 자리가 없다.**

- `D_NAMES` 베이스는 `0x80069800`이므로 창 0/1/2는 `0x80069800`·`0x80079800`·`0x80089800`이다.
- 세 창 모두 STAYDAT 안이고, **512 B 이상 0-run이 한 곳도 없다.**
- STAYDAT 전체로 넓혀도 256 B 이상 0-run은 2곳 1,289 B(0.3%)뿐이다. 사실상 빈틈 없이 packed.
- STAYDAT 바로 위 RAM(`0x800A0000`)은 사용 중이라 파일을 그냥 키울 수도 없다.

따라서 다음 단계는 **STAYDAT 재배치**다. 창 0–2가 차지할 192 KiB 구간을 `D_NAMES` 전용으로
비우고, 그 안에 있던 다른 슬라이스(`D_DEDMES`·`D_UNIT`·`IP`·`SC_04/05`·`D_ANI00`과 미확인
영역들)를 옮긴 뒤 각자의 베이스 표 항목을 갱신해야 한다. 베이스 표는
MAP `0x8015F2E8~`(그리고 BATTLE의 사본)이며 슬롯당 u32 하나다.
