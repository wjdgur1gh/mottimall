@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  set "PY="
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
  if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
  )
  if not defined PY (
    echo [오류] Python 3.10 이상이 필요합니다. docs\WINDOWS_SETUP.md 의 1번을 먼저 진행하세요.
    pause
    exit /b 1
  )
  echo [게임봇] 가상환경 생성 (.venv)
  %PY% -m venv .venv
)
set "VPY=.venv\Scripts\python.exe"
set PYTHONUTF8=1

"%VPY%" -c "import cv2, yaml, numpy" >nul 2>nul
if errorlevel 1 (
  echo [게임봇] 처음 실행: OpenCV 등 필요한 패키지를 설치합니다 ^(인터넷 필요, 1~2분^)
  "%VPY%" -m pip install --upgrade pip >nul
  "%VPY%" -m pip install -e ".[game]"
  if errorlevel 1 (
    echo [오류] 패키지 설치 실패. 인터넷 연결을 확인한 뒤 다시 실행하세요.
    pause
    exit /b 1
  )
)

if "%~1"=="" (
  echo 사용법:  gamebot.bat ^<명령^> ...
  echo   gamebot.bat devices                              연결된 휴대폰 확인
  echo   gamebot.bat screenshot                           화면 캡처 저장
  echo   gamebot.bat pick -o game_bot\templates\cheonji   버튼 이미지 잘라내기
  echo   gamebot.bat check game_bot\scenarios\cheonji.yaml
  echo   gamebot.bat run   game_bot\scenarios\cheonji.yaml --dry-run -v
  echo   gamebot.bat run   game_bot\scenarios\cheonji.yaml
  echo 자세한 설명: game_bot\README.md
  exit /b 0
)
"%VPY%" -m game_bot %*
endlocal
