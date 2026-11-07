@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "logs" mkdir "logs"

echo ============================================================
echo  智慧树 · 一口气刷完模式 (All-in-One Marathon Mode)
echo  将连续学习所有未完成视频，每 ~2 小时自动短暂休息防风控
echo ============================================================

if exist "zhs-daily.exe" (
  "zhs-daily.exe" --config "%~dp0config.yaml" --all
) else if exist "zhs-daily-lite.exe" (
  "zhs-daily-lite.exe" --config "%~dp0config.yaml" --all
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" daily.py --config "%~dp0config.yaml" --all
) else (
  python daily.py --config "%~dp0config.yaml" --all
)

set RC=%ERRORLEVEL%
echo.
echo [运行结束，退出码=%RC%]
pause
exit /b %RC%
