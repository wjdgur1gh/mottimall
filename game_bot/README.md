# game_bot — 휴대폰 게임 자동 플레이 (ADB + 화면 인식)

PC 에 USB 로 연결한 안드로이드 휴대폰의 화면을 1초마다 캡처해서, 미리 잘라 둔 **버튼 이미지(템플릿)** 가
보이면 그 자리를 터치하는 방식의 자동화 도구입니다. 게임 앱을 고치거나 루팅하지 않고, 사람이 손가락으로
하는 것과 같은 터치 입력만 보냅니다. 어떤 화면에서 무엇을 누를지는 **YAML 시나리오 파일** 로 정의합니다.

```
휴대폰(USB) ──adb screencap──▶ PC: OpenCV 로 버튼 찾기 ──adb input tap──▶ 휴대폰
```

기본 제공 시나리오: `scenarios/cheonji.yaml` — **천지명장전** (`com.yunbu.xgz.free.kr`) 반복 전투 뼈대.
다른 게임에도 `scenarios/example.yaml` 을 복사해서 그대로 쓸 수 있습니다.

> **주의**
> - 대부분의 게임 이용약관은 매크로·자동화 프로그램을 금지하며, 적발되면 계정이 제재될 수 있습니다. 본인 계정에 대한 책임은 본인에게 있습니다.
> - 결제·아이템 판매·삭제처럼 되돌릴 수 없는 버튼이 있는 화면은 자동화하지 마세요. `idle_limit`, `stop_after`, 패배 감지 `stop` 같은 안전장치를 꼭 켜 두세요.
> - 휴대폰 화면이 켜져 있고 게임이 맨 앞에 떠 있어야 합니다 (개발자 옵션 → "충전 중 화면 켜짐 유지").

---

## 1. 준비 (한 번만)

1. **ADB(platform-tools) 설치**
   https://developer.android.com/tools/releases/platform-tools 에서 "SDK Platform-Tools for Windows" 를 받아 압축을 풀고,
   `platform-tools` 폴더를 `C:\platform-tools` 로 옮깁니다. (다른 곳에 두었다면 환경변수 `ADB_PATH` 에 `adb.exe` 전체 경로를 넣거나 `--adb` 옵션으로 지정)
2. **휴대폰 USB 디버깅 켜기**
   설정 → 휴대전화 정보 → 소프트웨어 정보 → **빌드 번호를 7번 연타** → 개발자 옵션이 생김 → **USB 디버깅** ON.
   같은 화면의 **"충전 중 화면 켜짐 유지"** 도 ON 추천.
3. **USB 연결** 후 휴대폰에 뜨는 "USB 디버깅을 허용하시겠습니까?" 에서 **항상 허용**.
   (삼성은 USB 연결 모드를 "파일 전송" 으로 두면 인식이 잘 됩니다. 인식이 안 되면 제조사 USB 드라이버 설치.)
4. 저장소 루트에서 **`gamebot.bat devices`** 를 실행합니다. 처음 한 번은 가상환경과 OpenCV 를 자동 설치합니다 (1~2분).
   아래처럼 `device` 가 나오면 성공입니다.
   ```
   시리얼                  상태          설명
   R3CN90XXXXX             device        product:... model:SM_S911N ...  ← 정상 — 사용 가능
   ```
   `unauthorized` 면 3번의 허용 창을 아직 누르지 않은 것, `offline` 이면 케이블을 다시 꽂으세요.

**무선으로 쓰기(선택):** USB 로 연결된 상태에서 `C:\platform-tools\adb tcpip 5555` 를 한 번 실행하고 케이블을 뺀 뒤
`gamebot.bat connect 192.168.0.XX:5555` (휴대폰 Wi-Fi IP). 휴대폰을 재부팅하면 다시 USB 로 `tcpip` 를 해야 합니다.

Mac/Linux 에서는 `pip install -e ".[game]"` 후 `gamebot ...` 또는 `python -m game_bot ...` 으로 똑같이 씁니다.

---

## 2. 5분 빠른 시작 (천지명장전)

```bat
gamebot.bat devices                                   :: 1) 휴대폰 인식 확인
gamebot.bat screenshot                                :: 2) 화면 캡처가 되는지 확인 (game_bot\screenshots\ 에 저장)
gamebot.bat pick -o game_bot\templates\cheonji        :: 3) 버튼 이미지 잘라내기 (아래 설명)
gamebot.bat check game_bot\scenarios\cheonji.yaml     :: 4) 빠진 템플릿이 있는지 검사
gamebot.bat run game_bot\scenarios\cheonji.yaml --dry-run -v   :: 5) 터치 없이 "무엇을 인식했는지" 만 출력
gamebot.bat run game_bot\scenarios\cheonji.yaml       :: 6) 실제 실행. Ctrl+C 로 중단
```

**3) 템플릿 잘라내기 (`pick`)** — 휴대폰 화면이 PC 창으로 뜹니다.
게임에서 해당 화면(예: 팝업이 떠 있는 상태)으로 이동한 뒤 창에서 **r** 을 눌러 다시 캡처하고,
버튼을 **드래그로 감싼 뒤 s** → 콘솔에 파일 이름 입력(예: `close`) → `game_bot\templates\cheonji\close.png` 저장.
저장 직후 시나리오에 붙여 넣을 YAML 조각도 출력됩니다. 창을 **클릭** 하면 그 지점의 좌표와 색이 콘솔에 찍히므로 고정 좌표 탭이나 `pixel` 조건에 쓸 수 있습니다.

천지명장전 시나리오가 필요로 하는 템플릿 목록과 각 템플릿을 어떤 화면에서 잘라야 하는지는
**[templates/cheonji/README.md](templates/cheonji/README.md)** 에 표로 정리되어 있습니다.

**5) dry-run** 에서 `▶ 팝업 닫기(X)  [close.png @(540, 1210) score=0.93]` 처럼 규칙이 맞을 때마다 한 줄씩 나옵니다.
`-v` 를 붙이면 맞지 않은 규칙의 사유(`✗ 확인 버튼 (confirm.png 없음)`)도 보입니다.
게임 화면을 이리저리 옮겨 보면서 **원하는 화면에서 원하는 규칙이 뜨는지, 엉뚱한 규칙이 뜨지 않는지** 확인한 뒤 실제 실행으로 넘어가세요.

---

## 3. 시나리오 파일 문법

```yaml
name: 천지명장전 반복 전투
package: com.yunbu.xgz.free.kr   # 선택. run 시작 시 이 앱을 띄움
templates_dir: ../templates/cheonji   # 템플릿 폴더 (이 yaml 파일 기준 상대경로)
interval: 1.0        # 루프 간격(초)
screen: [1080, 2400] # 선택. 템플릿을 캡처한 해상도. 다른 해상도 기기에서 돌릴 때 좌표/템플릿을 자동 배율
stop_after: 7200     # 선택. N초 후 종료
idle_limit: 180      # 선택. 어떤 규칙도 N루프 연속 안 맞으면 종료
device: R3CN90XXXXX  # 선택. 기기 시리얼 (여러 대일 때)

rules:
  - name: 팝업 닫기            # 규칙 이름 (중복 불가, 로그에 표시)
    priority: 100              # 높을수록 먼저 검사. 같은 루프에서는 맞는 규칙 "하나만" 실행
    cooldown: 2                # 실행 후 N초 동안 다시 실행하지 않음
    max_runs: 5                # 총 N회만 실행
    enabled: true
    when: { image: close.png, threshold: 0.85 }
    do:
      - tap: match
      - wait: 0.5
```

매 루프: 화면 캡처 → `priority` 높은 순으로 규칙의 `when` 검사 → **처음 맞는 규칙 하나** 의 `do` 를 위에서부터 실행 → `interval` 만큼 대기.

### 조건 (`when`)

| 문법 | 의미 |
|---|---|
| `when: close.png` | 축약형. 아래 `image` 와 같음 |
| `when: { image: close.png, threshold: 0.85, region: [x, y, w, h], grayscale: true }` | 템플릿이 화면에 보이면 참. `threshold` 0~1 (기본 0.8), `region` 은 그 영역 안에서만 탐색, `grayscale` 은 색 무시 |
| `when: { pixel: [x, y], color: "#ff0000", tolerance: 20 }` | 그 좌표의 색이 지정 색과 ±tolerance 안이면 참 (HP 게이지, 켜짐/꺼짐 표시 등) |
| `when: always` | 항상 참 (낮은 priority 의 "기본 동작" 용) |
| `when: { all: [조건, 조건, ...] }` | 모두 참 |
| `when: { any: [조건, 조건, ...] }` | 하나라도 참 |
| `when: { not: 조건 }` | 조건이 거짓이면 참 |

`image` 조건이 맞으면 그 위치가 **match** 로 기억되어 `tap: match` 에서 쓰입니다. `all` 에서는 첫 번째 `image` 의 위치입니다.

### 동작 (`do`)

| 문법 | 의미 |
|---|---|
| `- tap: match` | 방금 매칭된 템플릿의 중심을 탭 |
| `- tap: [540, 1200]` | 고정 좌표 탭 |
| `- tap: { at: match, offset: [0, -30], times: 3, interval: 0.2 }` | 오프셋/연타 |
| `- long_press: match` / `- long_press: { x: 100, y: 200, duration_ms: 1000 }` | 길게 누르기 |
| `- swipe: [x1, y1, x2, y2, 300]` | 스와이프 (마지막은 ms) |
| `- key: BACK` | 키 입력 (BACK, HOME, ENTER, 키코드 숫자) |
| `- text: abc123` | 영문/숫자 입력 (한글 불가) |
| `- wait: 1.5` | 대기(초) |
| `- wait_for: { image: in_battle.png, timeout: 20, interval: 0.5, on_timeout: abort }` | 조건이 참이 될 때까지 대기. 성공하면 그 위치가 새 `match` 가 됨. 타임아웃 시 `abort`(기본) 는 이 규칙의 남은 동작 취소, `continue` 는 계속 |
| `- wait_gone: close.png` | 조건이 거짓이 될 때까지 대기 (옵션 동일) |
| `- log: "메시지"` | 로그 출력 |
| `- launch: com.yunbu.xgz.free.kr` / `- stop_app: ...` | 앱 실행 / 강제 종료 |
| `- screenshot: ../screenshots/defeat_%Y%m%d_%H%M%S.png` | 스크린샷 저장 (날짜 서식 가능) |
| `- stop: 사유` 또는 `- stop` | 봇 종료 |

---

## 4. 템플릿 잘 만드는 요령

- 버튼의 **글자/아이콘이 꽉 차게**, 테두리까지. 주변 배경을 많이 포함하면 배경이 바뀔 때 점수가 떨어집니다.
- **매번 바뀌는 부분(숫자, 게이지, 타이머, 반투명 위의 글자)은 피하기.**
- 템플릿 하나가 **그 화면에서만** 보이는지 확인. 예: `in_battle.png` 는 전투 밖에서 절대 보이지 않는 UI 여야 합니다.
- 점수 확인: `gamebot.bat find game_bot\templates\cheonji\close.png` → 현재 화면에서 최고 점수와 위치. `--mark out.png` 로 표시 이미지 저장.
  보통 같은 화면이면 0.95 이상, 다른 화면이면 0.6 이하가 나옵니다. 그 사이면 `threshold` 를 조정하거나 템플릿을 다시 잘라 보세요.
- `region` 으로 탐색 범위를 제한하면 **속도가 빨라지고 오인식이 줄어듭니다** (`pick` 에서 드래그하면 region 값이 출력됨).
- **해상도가 다른 기기**에서 돌릴 때는 시나리오에 `screen: [템플릿을 만든 기기의 가로, 세로]` 를 적으면 배율을 자동 적용합니다 (`gamebot.bat size` 로 확인). 비율(16:9 vs 20:9)이 다르면 고정 좌표는 어긋날 수 있으니 가능하면 `tap: match` 를 쓰세요.

---

## 5. 디버깅

| 하고 싶은 것 | 방법 |
|---|---|
| 터치 없이 인식만 보기 | `run ... --dry-run -v` |
| 어떤 규칙이 왜 안 맞는지 | `-v` 를 붙이면 `✗ 규칙명 (템플릿 없음)` 로그 |
| 템플릿 점수/위치 눈으로 확인 | `find 템플릿.png --mark out.png` 또는 `find 템플릿.png --image 스크린샷.png` |
| 규칙이 맞은 순간의 화면 모아 보기 | `run ... --debug-dir game_bot\debug` (매칭 사각형이 그려진 PNG 저장) |
| 로그 파일로 남기기 | `--log game_bot\bot.log` (예: `gamebot.bat --log game_bot\bot.log run ...`) |
| 한 루프만 실행 | `run ... --once` |
| 수동으로 터치 테스트 | `tap 540 1200`, `swipe 540 1500 540 800`, `key BACK` |
| 원격으로 도움 받기 | `screenshot` 으로 저장한 PNG 와 `--debug-dir` 결과를 Claude 대화에 올리면, 그 이미지를 보고 템플릿 영역·좌표·threshold 를 잡아 줄 수 있습니다 |

---

## 6. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `adb 를 찾을 수 없습니다` | 1번 설치 확인. `C:\platform-tools\adb.exe` 가 있는지, 또는 `set ADB_PATH=경로\adb.exe` |
| `devices` 에 아무것도 없음 | 케이블(충전 전용 케이블은 데이터 전송 불가), USB 디버깅 ON, USB 모드 "파일 전송", 제조사 드라이버 |
| 상태 `unauthorized` | 휴대폰 화면의 "USB 디버깅 허용" 창에서 항상 허용. 개발자 옵션 → "USB 디버깅 권한 취소" 후 재연결하면 창이 다시 뜸 |
| 상태 `offline` | 케이블 재연결, `C:\platform-tools\adb kill-server` 후 재시도 |
| 스크린샷이 검은 화면 | 앱이 캡처를 막는 경우(보안 앱, 일부 DRM). 게임은 드물지만 그런 앱은 이 방식으로 자동화 불가 |
| 매칭은 되는데 탭이 안 먹힘 | 다른 해상도 템플릿을 `screen` 없이 사용 → `size` 로 확인 후 `screen` 추가. 또는 결과창이 "아무 곳 탭" 이 아니라 특정 버튼만 받는 경우 → 그 버튼 템플릿으로 |
| 점수가 0.6~0.8 에서 들락날락 | 애니메이션/반투명 위에 있는 버튼. 템플릿을 더 작게(글자만) 자르거나 `grayscale: true`, threshold 0.75 |
| 엉뚱한 버튼을 누름 | 템플릿이 너무 작거나 단순(예: 원 하나). 더 특징적인 부분 포함, `region` 제한, threshold 상향 |
| 봇이 멈춰 있음 | 알려지지 않은 화면(이벤트 팝업 등). 그 화면을 `screenshot` → `pick` 으로 닫기 버튼 템플릿 추가 |
| 화면이 꺼짐 | 개발자 옵션 "충전 중 화면 켜짐 유지" 또는 `tap` 대신 `key: WAKEUP` 규칙 |
| 한글 폴더 경로에서 이미지 오류 | 지원함. 그래도 문제가 되면 저장소를 `C:\mottimall` 처럼 영문 경로로 |

---

## 7. 다른 게임에 적용하기

1. `scenarios/example.yaml` 을 복사해 `scenarios/<게임>.yaml` 로 만들고 `templates_dir: ../templates/<게임>` 으로 바꿉니다.
2. `gamebot.bat app` 으로 현재 앱 패키지명을 확인해 `package:` 에 적습니다.
3. `pick -o game_bot\templates\<게임>` 으로 닫기·확인·시작 버튼부터 잘라 넣고, 규칙을 하나씩 늘려 갑니다.
4. 항상 `--dry-run -v` 로 확인 후 실제 실행.

---

## 8. 명령 요약 (`gamebot.bat <명령> --help` 로 옵션 확인)

| 명령 | 설명 |
|---|---|
| `devices` | 연결된 기기와 상태 |
| `connect 192.168.0.10:5555` | 무선 ADB 연결 |
| `screenshot [-o 파일]` | 화면 캡처 저장 |
| `size` | 화면 해상도 |
| `tap x y` / `swipe x1 y1 x2 y2 [--ms]` / `key KEY` / `text 문자` | 수동 입력 |
| `app [--launch 패키지 | --stop 패키지]` | 현재 앱 보기 / 실행 / 종료 |
| `pick [--image 파일] [-o 폴더]` | GUI 로 좌표 찍기 · 템플릿 잘라 저장 |
| `crop 스크린샷.png x y w h -o 템플릿.png` | 파일에서 영역 잘라 저장 (GUI 없이) |
| `find 템플릿.png [--image 파일] [--threshold] [--region x,y,w,h] [--all] [--mark out.png]` | 매칭 점수/위치 확인 |
| `check 시나리오.yaml` | 문법·템플릿 검사 (기기 불필요) |
| `run 시나리오.yaml [--dry-run] [--once] [--max-loops N] [--interval 초] [--debug-dir 폴더]` | 실행 |

공통 옵션: `-s 시리얼`, `--adb 경로`, `-v`, `--log 파일`.

### 코드 구성

| 파일 | 역할 |
|---|---|
| `adb.py` | adb 실행 파일 호출: 기기 목록, 스크린샷(PNG → numpy), tap/swipe/key/text, 앱 실행 |
| `vision.py` | OpenCV 템플릿 매칭(`find_template`, `find_all`), 픽셀 색, 이미지 입출력(한글 경로 지원) |
| `scenario.py` | YAML → `Scenario`/`Rule`/조건/동작 객체. 문법 오류를 한국어로 안내 |
| `engine.py` | 캡처 → 규칙 평가 → 동작 실행 루프, cooldown/max_runs/idle_limit/stop_after, 해상도 배율 |
| `pick.py` | 좌표 찍기 / 템플릿 잘라내기 GUI |
| `cli.py` | 명령줄 |
| `../tests/test_game_bot_*.py` | 합성 이미지와 가짜 기기로 매칭·파싱·엔진 동작을 검증 (`pytest tests -k game_bot`) |
