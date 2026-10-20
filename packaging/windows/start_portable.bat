@echo off
setlocal
cd /d "%~dp0"
echo Starting WeChat Work Recorder... Please keep this window open.
if not exist "%~dp0WeChatWorkRecorder.exe" goto missing
start "" /wait "%~dp0WeChatWorkRecorder.exe" %*
if errorlevel 1 goto fail
exit /b 0
:missing
echo Application files are missing. Extract the ENTIRE ZIP before starting.
goto fail
:fail
echo Startup failed. Please keep all extracted files in the same folder.
if /i "%~1"=="--packaging-smoke-test" exit /b 1
pause
exit /b 1
