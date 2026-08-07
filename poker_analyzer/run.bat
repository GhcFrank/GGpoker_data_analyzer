@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
      set "PYTHON=%%i"
      goto found
    )
  )
)

:found
if not defined PYTHON (
  echo [ERROR] Python not found.
  echo Install Python 3.12 or add it to PATH, then run this again.
  pause
  exit /b 1
)

echo Using: %PYTHON%
"%PYTHON%" --version
if errorlevel 1 (
  echo [ERROR] Failed to run Python.
  pause
  exit /b 1
)

echo.
echo Starting Poker Analyzer ...
echo Open browser: http://127.0.0.1:8000
echo Press Ctrl+C to stop.
echo.

"%PYTHON%" -m uvicorn app:app --host 127.0.0.1 --port 8000
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
  echo [ERROR] Server exited with code %EXITCODE%
  echo If it says No module named uvicorn, run:
  echo "%PYTHON%" -m pip install -r requirements.txt
)
pause
exit /b %EXITCODE%
