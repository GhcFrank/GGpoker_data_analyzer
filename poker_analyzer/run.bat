@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
cd /d "%~dp0"
title Poker Analyzer

echo ========================================
echo   Poker Analyzer - local offline
echo ========================================
echo.

rem --- find Python ---
set "PYTHON="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python310\python.exe"
if not defined PYTHON if exist "F:\py3.10.9\python.exe" set "PYTHON=F:\py3.10.9\python.exe"

if not defined PYTHON (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
      set "PYTHON=%%i"
      goto :py_found
    )
  )
)

:py_found
if not defined PYTHON (
  where py >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%i"
  )
)

if not defined PYTHON (
  echo [ERROR] Python not found. Install Python 3.10+ then try again.
  goto :end
)

if not exist "app.py" (
  echo [ERROR] app.py not found. Put this bat in poker_analyzer folder.
  goto :end
)

if not exist "static\js\chart.umd.min.js" (
  echo [ERROR] Missing static\js\chart.umd.min.js
  goto :end
)

echo Python: %PYTHON%
"%PYTHON%" --version
if errorlevel 1 (
  echo [ERROR] Failed to run Python.
  goto :end
)
echo.

rem --- free port 8000 if old server still running ---
echo Checking port 8000...
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
  echo Stopping old process PID %%p
  taskkill /F /PID %%p >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo.
echo Starting...
echo Open: http://127.0.0.1:8000
echo Keep this window open. Press Ctrl+C to stop.
echo ========================================
echo.

"%PYTHON%" -u app.py
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
  echo [ERROR] Exited with code %EXITCODE%
  echo If port 8000 is blocked, close other programs using it and retry.
)

:end
echo.
echo Press any key to close this window...
pause >nul
endlocal
exit /b 0
