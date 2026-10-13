@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 먼저 setup.bat 을 실행하세요.
  exit /b 1
)
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m pullback_trader.cli %*
