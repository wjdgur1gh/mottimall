# 윈도우 설치 가이드 (Git 없이, 더블클릭으로)

## 1. Python 설치 (한 번만)

1. https://www.python.org/downloads/windows/ 에서 **Python 3.12** 의 "Windows installer (64-bit)" 를 받습니다.
2. 설치 첫 화면 **맨 아래 "Add python.exe to PATH" 체크** 후 Install Now.
3. 설치가 끝나면 열려 있던 PowerShell/명령 프롬프트 창을 **모두 닫습니다** (새 창부터 PATH 가 적용됩니다).

확인: 새 PowerShell 창에서 `python --version` 을 치면 `Python 3.12.x` 가 나와야 합니다.
`python` 을 쳤을 때 Microsoft Store 가 열리면 설치가 안 된 것입니다. 1~3 을 다시 하세요.

## 2. 코드 받기 (Git 불필요)

1. 브라우저에서 아래 주소를 열면 ZIP 이 내려받아집니다 (GitHub 로그인 필요할 수 있음).
   `https://github.com/wjdgur1gh/mottimall/archive/refs/heads/claude/korean-stock-day-trading-program-upnl65.zip`
   또는 GitHub 저장소 페이지에서 브랜치를 `claude/korean-stock-day-trading-program-upnl65` 로 바꾼 뒤 **Code → Download ZIP**.
2. ZIP 을 풀면 `mottimall-claude-korean-stock-day-trading-program-upnl65` 폴더가 나옵니다.
3. 그 폴더를 `C:\Users\<사용자명>\mottimall` 로 옮기고 이름을 `mottimall` 로 바꿉니다. 안에 `setup.bat`, `run.bat`, `pullback_trader` 폴더가 보여야 합니다.

## 3. 설치 실행

탐색기에서 `C:\Users\<사용자명>\mottimall\setup.bat` 을 **더블클릭**합니다.
가상환경 생성 → 패키지 설치 → 설정 파일 복사 → 샘플 데이터로 스윙 스캔까지 자동으로 돌고, 주문표가 출력되면 성공입니다.

PowerShell 에서 하려면:
```powershell
cd C:\Users\<사용자명>\mottimall
.\setup.bat
```
(PowerShell 은 현재 폴더의 파일을 실행할 때 앞에 `.\` 를 붙여야 합니다.)

## 4. 실행

항상 `run.bat` 뒤에 명령을 붙입니다. 가상환경 활성화(`activate`)는 필요 없습니다.

```powershell
cd C:\Users\<사용자명>\mottimall
.\run.bat scan --mode swing --provider csv --csv-dir data/sample --date 2026-10-08   # 샘플
.\run.bat hts --mode swing                                                          # HTS 세팅 시트
.\run.bat scan --mode swing --provider naver                                        # 실데이터 스윙 스캔 (장 마감 후)
.\run.bat live --mode day --provider naver --broker sheet --poll 60                 # 데이트레이딩 장중 루프
.\run.bat backtest --mode swing --provider naver --start 2025-10-01 --end 2026-10-10
```

`config\config.yaml` 에서 `risk.account_equity`(계좌 자산), `cost.commission_pct`(수수료율), `data.provider: naver` 를 바꿔 두면 `--provider` 를 매번 안 써도 됩니다. 결과 파일은 `output\` 폴더에 쌓입니다.

## 5. 자주 나는 오류

| 증상 | 원인/해결 |
|---|---|
| `git : 'git' 용어가 ... 인식되지 않습니다` | Git 이 없어도 됩니다. 2번처럼 ZIP 으로 받으세요. |
| `py : 'py' 용어가 ... 인식되지 않습니다` | Python 미설치 또는 PATH 미체크. 1번 다시. |
| `.venv\Scripts\activate : '.venv' 모듈을 로드할 수 없습니다` | PowerShell 은 `.\.venv\Scripts\Activate.ps1` 로 써야 하지만, `run.bat` 을 쓰면 활성화 자체가 필요 없습니다. |
| `이 시스템에서 스크립트를 실행할 수 없으므로 ...Activate.ps1` | PowerShell 실행 정책. `run.bat` 사용 또는 관리자 PowerShell 에서 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| `pip install` 에서 빨간 오류 | 인터넷 연결 확인. 회사망이면 프록시 때문에 실패할 수 있음. |
| 한글이 깨져 보임 | `run.bat` 은 UTF-8 로 맞춰 둡니다. 다른 터미널이면 `chcp 65001` 입력. |
| `pullback` 명령을 못 찾음 | 가상환경을 활성화하지 않은 상태. `run.bat` 을 쓰거나 `.\.venv\Scripts\pullback.exe` 로 실행. |
| naver 데이터 오류 (HTTP 4xx/5xx, JSON 오류) | 비공식 API 변경 가능성. 오류 메시지를 복사해 알려 주세요. 임시로 `--provider pykrx`(`pip install pykrx`) 사용. |
