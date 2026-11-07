@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "logs" mkdir "logs"

echo ============================================================
echo  智慧树 · 每日 25 分钟自动打卡模式 (稳拿平时习惯分)
echo ============================================================

if exist "zhs-daily.exe" (
  "zhs-daily.exe" --config "%~dp0config.yaml"
) else if exist "zhs-daily-lite.exe" (
  "zhs-daily-lite.exe" --config "%~dp0config.yaml"
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" daily.py --config "%~dp0config.yaml"
) else (
  python daily.py --config "%~dp0config.yaml"
)

set RC=%ERRORLEVEL%
echo.
echo [运行结束，退出码=%RC%]
pause
exit /b %RC%
