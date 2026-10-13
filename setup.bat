@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if defined PY (
  %PY% -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
  if errorlevel 1 set "PY="
)
if not defined PY (
  echo [오류] Python 3.10 이상이 설치되어 있지 않습니다.
  echo   1^) https://www.python.org/downloads/windows/ 에서 Python 3.12 설치 프로그램 다운로드
  echo   2^) 설치 첫 화면 아래의 "Add python.exe to PATH" 를 반드시 체크
  echo   3^) 설치가 끝나면 이 창을 닫고 setup.bat 을 다시 실행
  pause
  exit /b 1
)

echo [1/4] 가상환경 생성 (.venv)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo [오류] 가상환경 생성에 실패했습니다.
  pause
  exit /b 1
)
set "VPY=.venv\Scripts\python.exe"

echo [2/4] 패키지 설치 (인터넷 필요)
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -e ".[dev]"
if errorlevel 1 (
  echo [오류] 패키지 설치 실패. 인터넷 연결을 확인한 뒤 다시 실행하세요.
  pause
  exit /b 1
)

echo [3/4] 설정 파일 준비
if not exist "config\config.yaml" copy "config\config.example.yaml" "config\config.yaml" >nul
if not exist "config\exclusions.csv" copy "config\exclusions.example.csv" "config\exclusions.csv" >nul

echo [4/4] 샘플 데이터로 동작 확인
set PYTHONUTF8=1
"%VPY%" -m pullback_trader.cli sample
"%VPY%" -m pullback_trader.cli scan --mode swing --provider csv --csv-dir data/sample --date 2026-10-08
if errorlevel 1 (
  echo [오류] 샘플 실행에 실패했습니다. 위 오류 메시지를 복사해 알려 주세요.
  pause
  exit /b 1
)

echo.
echo ===== 설치 완료 =====
echo 앞으로는 run.bat 뒤에 명령을 붙여 실행합니다. 예:
echo   run.bat scan --mode swing
echo   run.bat hts --mode swing
echo   run.bat live --mode day --broker sheet
echo 설정 파일: config\config.yaml  (계좌 자산, 수수료율, data.provider 를 naver 로)
pause
endlocal
