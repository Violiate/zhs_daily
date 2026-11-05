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
echo [%date% %time%] daily start>>"logs\task.log"
"%PY%" daily.py --config "%~dp0config.yaml" >>"logs\task.log" 2>&1
set RC=%ERRORLEVEL%
echo [%date% %time%] daily exit=%RC%>>"logs\task.log"
exit /b %RC%
