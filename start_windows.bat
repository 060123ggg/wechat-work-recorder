@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Please install Python 3.10 or newer from python.org and enable the py launcher.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m wechat_work_recorder.app
if errorlevel 1 goto fail
exit /b 0
:fail
echo Setup or application startup failed. Check the message above.
pause
exit /b 1
