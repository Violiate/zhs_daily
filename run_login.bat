@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
echo ============================================================
echo  智慧树扫码登录
echo  二维码会显示在下方，同时保存到 state\login_qr.png
echo ============================================================
"%PY%" daily.py --login
echo.
pause
