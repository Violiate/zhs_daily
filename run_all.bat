@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
echo ============================================================
echo  智慧树 · 一口气刷完模式 (All-in-One Marathon Mode)
echo  将连续学习所有未完成视频，每 ~2 小时自动短暂休息防风控
echo ============================================================
"%PY%" daily.py --config "%~dp0config.yaml" --all
set RC=%ERRORLEVEL%
echo.
echo [运行结束，退出码=%RC%]
pause
exit /b %RC%
