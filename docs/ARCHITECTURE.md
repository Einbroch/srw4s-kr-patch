# SLPS-00196 로더·데이터 구조 조사

기준 입력: `SLPS_001.96` SHA-256 `5966d606e2804afcafb86d52f2864590d17f2c27535ba2a35c5f9954a64184b6`

## PS-X EXE 배치

| 항목 | 값 |
|---|---:|
| 초기 PC | `0x800C130C` |
| payload 로드 주소 | `0x800C0000` |
| payload 크기 | `0x39000` |
| 초기 SP | `0x801FFFF0` |
| 파일 오프셋→RAM | `0x800C0000 + (file_offset - 0x800)` |

## CD 파일 인덱스

실행 파일 오프셋 `0x20C10`(RAM `0x800E0410`)에 37개 경로 포인터가 있다. `0x800C2BC0`의 초기화 루프는 37개(`slti ..., 0x25`) 경로를 검색해 RAM `0x80105DC0`의 28-byte 메타데이터 레코드를 채운다.

- `0x800C2F78`: 파일 인덱스, 목적지, 파일 내부 오프셋, 크기를 받는 부분/동기 읽기 루틴
- `0x800C3158`: 파일 인덱스와 목적지를 받는 전체 파일 동기 읽기 루틴
- `0x800C2D44`: 비동기 상태 기계형 읽기 루틴

| 인덱스 | 경로 | 인덱스 | 경로 |
|---:|---|---:|---|
| 0 | `MAP.LZB` | 19 | `DAT/M_FIELD.BIN` |
| 1 | `DAT/C_DEMOG.BIN` | 20 | `DAT/IP.BIN` |
| 2 | `DAT/C_MAPBG.BIN` | 21–26 | `DAT/SC_00.BIN`–`SC_05.BIN` |
| 3 | `DAT/C_PFACE.BIN` | 27 | `DAT/D_ANI00.BIN` |
| 4 | `DAT/C_ROBOT.BIN` | 28 | `DAT/STAYDAT.BIN` |
| 5 | `DAT/C_UNITG.BIN` | 29 | `VABLIST.BIN` |
| 6–17 | `DAT/D_DEDMES.BIN`–`D_WEAPON.BIN` | 30 | `SEQLIST.BIN` |
| 18 | `DAT/M_BANKS.BIN` | 31 | `BTT/BATTLE.LZB` |
|  |  | 32 | `BTT/M_BANKB.LZB` |
|  |  | 33–34 | `BTT/C_BBACK.BIN`, `C_BEFCT.BIN` |
|  |  | 35 | `MOVIE.LZB` |
|  |  | 36 | `DAT/C_ETC.BIN` |

정확한 전체 경로와 포인터는 `tools/analyze_structures.py --json`으로 재검증한다.

## 오버레이와 LZB

- 실행 파일의 LZB 해제 루틴은 RAM `0x800C345C`(파일 `0x3C5C`)에서 확인했다. 오버레이가 호출하는 `0x800C372C`는 같은 형식의 형제 진입점이다.
- `MAP.LZB` 해제물은 RAM `0x80110000` 기준으로 해석된다. 코드 시작 후보는 해제 오프셋 약 `0x2A08`이다.
- `BTT/BATTLE.LZB`도 RAM `0x80110000` 기준이며 코드 시작 후보는 약 `0x3FAC8`이다.
- `MOVIE.LZB`는 로컬 호출 목표로 볼 때 RAM `0x80106000` 기준 후보이며 코드 시작은 약 `0x71E8`이다.
- 이는 정적 주소 대응 증거다. 아직 무변경 재압축 왕복과 런타임 로드 검증은 통과하지 않았다.

## STAYDAT 상주 팩

`MAP` 오버레이는 파일 인덱스 28을 RAM `0x80020000`에 전체 로드한다. `STAYDAT.BIN` SHA-256은 `8321f0c2f1c2fe12b1ca2c9c9a7f7373804828eb1d660b580a6e13301d23b50e`이다. 아래 슬라이스는 별도 ISO 파일과 16/16 바이트 동일하다.

| STAY 오프셋 | RAM | 원본 파일 | 크기 |
|---:|---:|---|---:|
| `0x00000` | `0x80020000` | `D_PALET.BIN` | 58,184 |
| `0x0E800` | `0x8002E800` | `D_OBJCT.BIN` | 96,140 |
| `0x26000` | `0x80046000` | `D_ROBOT.BIN` | 13,884 |
| `0x29800` | `0x80049800` | `D_MOVE.BIN` | 3,854 |
| `0x2A800` | `0x8004A800` | `D_PILOT.BIN` | 9,656 |
| `0x2D000` | `0x8004D000` | `D_LEVEL.BIN` | 1,442 |
| `0x2D800` | `0x8004D800` | `D_EVENT.BIN` | 3,876 |
| `0x2E800` | `0x8004E800` | `D_WEAPON.BIN` | 11,680 |
| `0x31800` | `0x80051800` | `D_MAP.BIN` | 18,632 |
| `0x49800` | `0x80069800` | `D_NAMES.BIN` | 51,848 |
| `0x56800` | `0x80076800` | `D_DEDMES.BIN` | 1,166 |
| `0x57000` | `0x80077000` | `D_UNIT.BIN` | 5,387 |
| `0x58800` | `0x80078800` | `IP.BIN` | 16,511 |
| `0x62000` | `0x80082000` | `SC_04.BIN` | 1,204 |
| `0x63000` | `0x80083000` | `SC_05.BIN` | 5,449 |
| `0x64800` | `0x80084800` | `D_ANI00.BIN` | 15,414 |

정렬 패딩에는 개발 당시 문자열/잔여 데이터가 섞여 있다. 별도 파일과 일치하지 않는 패딩을 런타임 사용자 텍스트로 계산하지 않는다.

## 핵심 텍스트 구조

### D_NAMES.BIN

- 파일 시작 `0x48` bytes는 18개의 32-bit 절대 섹션 오프셋이다. 섹션 3은 null이다.
- 각 활성 섹션은 16-bit 절대 문자열 포인터 배열을 가리킨다. 섹션 5·9·10·16은 더 큰 포인터 배열의 중간을 가리키는 부분 배열이다.
- 중첩 경계를 반영한 총 엔트리는 4,090개다. 공유 포인터와 빈 문자열이 있어 고유 원문 수와는 다르다.
- 모든 엔트리는 범위 내 포인터와 토큰 인수를 건너뛴 구조적 `FF` 종단을 가진다. 308개 레코드는 글리프 꼬리/제어 인수 안에 실제 종단보다 이른 `FF`를 포함한다.
- `FF`는 종단이다. 두 소비 루틴으로 `00`–`EF` 단일 글리프와 `F0`–`F5 + trail` 확장 글리프 산식을 확정했다. `F6`–`FE`는 제어 디스패치이며 인수 길이와 의미가 남았다. 자세한 계약은 `ENCODING.md`에 있다.
- 원문 바이트 inventory는 `_work/analysis/dnames_raw_manifest.tsv`에 `D_NAMES:Sxx:Exxxx` 안정 ID로 저장했다. 교차 버전 문자표를 적용한 파생 일본어 보기는 `_work/analysis/dnames_decoded_candidate.tsv`다.

### M_BANKS.BIN

- 파일 SHA-256은 `13ad84638ccb47bab9c72b68512835a38659acba3eb96867520f13283d17ed22`이다.
- 첫 32-bit 값 `0xF4`는 61개 32-bit 엔트리로 된 헤더의 끝이자 첫 하위 구조의 시작이다.
- MAP 해제물 파일 오프셋 `0x4DB28`(RAM `0x80153EA8`)의 초기화 루틴은 헤더 `0xF4`바이트를 읽은 뒤 61개 헤더 엔트리 각각에서 정확히 `0x200`바이트를 캐시한다. 즉 각 하위 표는 가변 길이가 아니라 **256개의 16-bit 포인터**로 고정된다.
- MAP 해제물 파일 오프셋 `0x4DD00`(RAM `0x80154080`)의 소비자는 `(bank_index, slot_index, output_slot)`을 받는다. `header[bank] & 0xFFFF0000`에 캐시된 `u16[slot]`을 더한 파일 오프셋부터 정확히 `0x400`바이트를 읽는다.
- MAP 스크립트 인터프리터 파일 오프셋 `0xA130` 부근은 16-bit 값이 `0x9000`보다 작으면 다른 사전 소비자로 보내고, `0x9000` 이상이면 `bank = (selector - 0x9000) >> 8`, `slot = selector & 0xFF`로 분해해 위 `M_BANKS` 소비자를 호출한다. 따라서 안정 선택자는 `0x9000 + bank*0x100 + slot`이다.
- 따라서 16-bit 값은 64KiB 은행 기준 상대 주소지만, 레코드/읽기 창은 은행 경계를 넘어 연속될 수 있다. 현재 54개 토큰 종단 후보가 실제로 경계를 넘는다.
- 61개 헤더 중 56개가 non-null이므로 정적 런타임 슬롯 inventory는 `56 × 256 = 14,336`개다. 그중 14,105개는 `0x400` 읽기 창 안에서 토큰 인수를 건너뛴 구조적 `FF`를 만난다. 나머지는 파일 밖을 가리키는 미사용 후보 51개와, 파일 안이지만 읽기 창에서 종단이 없는 180개다.
- 이 14,336개는 **가능한 스트림 진입 슬롯**이지 모두 라이브 대사라는 뜻이 아니다. 소비자에서 역추적한 현재의 보수적 후보 집합은 아래 이벤트 VM 범위와 직접/수식 소비자를 합친 1,624개다.
- 원문/파생 후보 inventory는 `_work/analysis/mbanks_candidate_manifest.tsv`이며 `tools/decode_mbanks.py`로 재생성한다. `FF`가 `0x400` 안에 있는 슬롯만 파생 일본어 보기를 채운다.

### 이벤트 VM과 M_BANKS 라이브 후보

- MAP 해제물의 파일 오프셋과 런타임 주소 관계는 `runtime = file_offset + 0x80106380`이다. 이벤트 VM 명령 길이는 `MAP[0x274 + opcode*8]`의 u32, 핸들러는 `MAP[0x278 + opcode*8]`의 포인터다.
- `C4`–`CC` 핸들러는 16바이트 표시 레코드의 `+6`에 packed u16 메시지 값을 쓴다. 선택자 인수 위치는 `C4/C5/C6/C7/C9/CA/CB/CC`가 명령 인수 `+2`, `C8`이 인수 `+0`이다.
- 표시 소비자는 MAP `0xDC94`에서 레코드 `+6`을 읽고 `0xDCB8`에서 `raw & 0x7FFF`를 적용한다. 따라서 bit 15는 상태 플래그이며 실제 값은 `bank=(raw&0x7FFF)>>8`, `slot=raw&0xFF`다. MAP `0x4D164`에서 이 두 값을 `M_BANKS` 소비자로 넘긴다.
- 증명된 VM 루트는 `SC_00.BIN`(파일 인덱스 21 → RAM `0x801B0000` → 전역 `0x8015F340`), `SC_04.BIN`(STAYDAT `+0x62000` → `0x80082000` → 전역 `0x8015F350`), `SC_05.BIN`(STAYDAT `+0x63000` → `0x80083000` → 전역 `0x8015F354`)이다. `SC_01`–`SC_03`은 별도 적재 경로라 이 집합에 임의로 합치지 않았다.
- `SC_01`–`SC_03`(파일 인덱스 22–24)은 MAP 해제 오프셋 `0x161C8/0x16298/0x16368`(RAM `0x8011C548/0x8011C618/0x8011C6E8`)에서 stage별 파일 오프셋부터 `0x800`바이트를 임시 RAM `0x80010000`으로 읽은 뒤 `0x80080800/0x80081000/0x80081800`에 복사한다. opcode `60`의 source 1/2/3 분기는 전역 `0x8015F344/0x8015F348/0x8015F34C`을 통해 이 세 창으로 커서를 전환한다. 다만 각 파일의 80개 offset을 모두 도달 가능한 VM 루트로 가정한 시험은 유효 범위 밖 `M_BANKS` 선택자를 만들었으므로, stage/root 도달성을 증명하기 전에는 현재 1,624개 집합에 승격하지 않는다.
- 고정 루트 표는 각각 168/128/224 entries다. 현재 entry→fallthrough 순회는 1,584개의 고유 메시지 피연산자 위치와 1,550개의 고유 `M_BANKS` 대상을 찾았고, 이 중 6개 위치에서 bit 15 플래그가 켜져 있었다. 직접 소비 2개, MAP `0x4C668`의 bank 0 / slot `0x30–0x6F` 수식 64개, C3 난수 경로의 bank `0x3C` / slot `0x65–0x6C` 8개를 보수적으로 더해 총 1,624개가 된다.
- 텍스트 제어 `FB`의 두 인수는 little-endian selector다. 값이 `0x9000` 이상이면 다시 `M_BANKS`로 들어간다. 현재 1,624개 후보를 재귀 조사한 결과 정적 중첩 대상과 `FF` 동적 치환은 없어서 closure 깊이는 0이다.
- `_work/analysis/mbanks_live_selector_refs.tsv`는 명령/피연산자 위치·원본 SHA·루트 역참조를, `mbanks_live_closure.tsv`는 최종 후보·원문 해시·파생 일본어를 보존한다. `mbanks_live_selector_report.json`이 서명과 집계를 재검증한다.
- 이 결과는 **소비자 한정 entry/fallthrough 후보 집합**이다. `01` signed 상대 점프, `02` 절대 점프, `03` 반환 스택형 상대 호출, `04` 반환, `60` 동적 원천 전환을 정적으로 확인했다. 현재 SC_00 선형 과대근사에는 상대 점프 98곳·상대 호출 6곳·절대 점프 37곳이 나타나며, 상대 목표 104개 중 36개와 절대 목표 37개 전부가 SC_00 파일 밖으로 계산된다. 이는 미선택 루트/비도달 fallthrough가 섞였거나 다른 런타임 원천이 필요하다는 증거다. 목표를 임의로 따라가지 않고, 루트 도달성 및 다른 적재 원천을 연결할 때까지 전체 CFG를 열린 상태로 둔다. 따라서 1,624개를 최종 전체 라이브 대사라고 표현하지 않는다.

### 주 텍스트 글꼴

- MAP 전역 포인터가 가리키는 STAYDAT `0x36800`의 디스크립터에서 전체 글꼴 위치를 확정했다.
- 글꼴은 STAYDAT `0x36838–0x43837`에 연속 저장된 1,792글리프다. ID `000–0FF`는 8×16/16바이트, ID `100–6FF`는 16×16/32바이트다.
- 세 렌더러 분기의 포인터/stride와 실제 비트맵 렌더링을 모두 확인했다. 세부 해시와 한글 슬롯 제약은 `FONT.md`에 기록했다.

## 재현 명령

```powershell
python _work\tools\analyze_structures.py
python _work\tools\analyze_structures.py --json
python _work\tools\analyze_structures.py --dnames-manifest _work\analysis\dnames_raw_manifest.tsv
python _work\tools\decode_mbanks.py
python _work\tools\verify_text_roundtrip.py
python _work\tools\analyze_live_selectors.py
```

이 도구들은 원본과 추출 파일을 수정하지 않는다. 생성물은 `_work/analysis` 아래에만 쓴다.
