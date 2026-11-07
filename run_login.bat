@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "logs" mkdir "logs"

echo ============================================================
echo  智慧树（知到）扫码登录
echo  二维码将显示在下方，同时自动打开 state\login_qr.png
echo ============================================================

if exist "zhs-daily.exe" (
  "zhs-daily.exe" --config "%~dp0config.yaml" --login
) else if exist "zhs-daily-lite.exe" (
  "zhs-daily-lite.exe" --config "%~dp0config.yaml" --login
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" daily.py --config "%~dp0config.yaml" --login
) else (
  python daily.py --config "%~dp0config.yaml" --login
)

echo.
pause
