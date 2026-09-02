# 가시성 PoC — 통과

기준일: 2026-08-22  
결론: **한글 글리프가 게임 자신의 렌더 경로로 화면에 정상 출력된다. 크기 보존 raw 섹터 패치 이미지가 부팅·구동된다.**

## 무엇을 증명했나

| 항목 | 결과 | 증거 |
|---|---|---|
| STAYDAT 글꼴 은행 계약 (`0x37838`, 32B/글리프, 좌16+우16 MSB-first) | 통과 | 주입한 한글이 원본 한자 자리에 정확히 렌더 |
| 글리프 ID 경로 `F0–F5 + trail` → mid bank | 통과 | ID `0x100–0x2FF` 전량 치환이 모든 화면에 반영 |
| 소비 화면 범위 | 통과 | 주인공 설정 / 이름 입력 헤더 / 대사창 / 맵 명령 메뉴 / 유닛 목록 / 정신 커맨드 창 — 전부 같은 글꼴 |
| 크기 보존 in-place raw 섹터 교체 + EDC/ECC 재계산 | 통과 | 무변경 왕복이 원본과 **SHA-256 바이트 동일**, 패치본 정상 부팅 |
| 8×16 low bank(`0x000–0x0EF`) 무손상 | 통과 | 히라가나·가타카나·ASCII가 원본 그대로 표시 |

미증명(다음 게이트로 이월): 재인코딩한 **문자열**의 화면 표시. 패치한 14개 `D_NAMES` 레코드(지형·시나리오 제목·파일럿명)는
1화에서 화면에 나오지 않았다. 바이트 수준으로는 패치 이미지에서 재추출해 전량 일치를 확인했다.

## 빌드 내용

- 글꼴: `reference/srwcb-korean-patch/font/hangul_galmuri14_ksx1001_16x16.bin`(갈무리14, OFL)을 SRW4S 배치로 변환해
  ID `0x100–0x2FF`(512자)에 주입. 변환 규칙은 `tools/hangul_font.py`.
- 문자열: `D_NAMES` 14개 레코드를 원본 길이 이내로 재인코딩(`tools/build_poc.py`).
  STAYDAT 상주 사본(`+0x49800`)과 별도 `DAT/D_NAMES.BIN` **양쪽**에 동일 적용.
- 이미지: `tools/patch_image.py` — Expected Write(대상 LBA의 현재 사용자 데이터가 원본 추출본과 일치) 확인 후
  사용자 데이터만 덮고 EDC/ECC 재계산. sync/header/subheader는 건드리지 않는다.

산출물: `build/poc/` (Track 1 패치본 + 원본 오디오 트랙 2·3 + cue).  
재현: `analysis/poc_build_report.json`의 글리프 할당표·문자열 바이트·SHA-256.

## 증거 파일

- `analysis/emulator/PASS_glyph_visibility.png` — 주인공 설정 화면(`能人公設定` 자리에 한글)
- `analysis/emulator/poc_r3.png` — 대사창(M_BANKS 경로)
- `analysis/emulator/poc_w1.png` — 맵 명령 메뉴
- `analysis/emulator/poc_x1.png` — 유닛 목록

## 런타임 검증 환경

emucap의 Mednafen 어댑터는 이 호스트에 빌드돼 있지 않다(Windows 빌드는 상류 문서상 BETA·비자명).
대신 사용자 PC의 DuckStation(`C:\Users\blari\Desktop\Duck Station`, BIOS `SCPH1001.BIN`)을 쓴다.

- `tools/ds_drive.py` — 새로 띄우기, `tools/ds_ctl.py` — 떠 있는 창에 붙어 키 입력·캡처.
- **함정**: 방향키는 Windows 확장 키다. `keybd_event`에 `KEYEVENTF_EXTENDEDKEY`(0x0001)를 주지 않으면
  스캔코드가 숫자패드로 잡혀 DuckStation의 `Keyboard/Up` 바인딩에 도달하지 않는다. 처음엔 커서가 전혀
  움직이지 않아 게임 입력 문제로 오인했다.
- 확인 버튼은 ○(설정상 `L` 키)다. ✕는 취소다.
- 1화 맵 진입 지점 세이브스테이트: `C:\Users\blari\Documents\DuckStation\savestates\SLPS-00196_1.sav`
  (F1 로드). 같은 시리얼이면 이후 패치 빌드에서도 재사용해 긴 초기 설정을 건너뛴다.
