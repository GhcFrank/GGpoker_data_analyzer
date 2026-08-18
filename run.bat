@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
cd /d "%~dp0"
title Poker Analyzer

set "ROOT=%~dp0"
set "APP_DIR=%ROOT%poker_analyzer"
set "PY_DIR=%ROOT%runtime\python"
set "PY_VER=3.12.10"
set "PY_ZIP=%ROOT%runtime\python-%PY_VER%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-embed-amd64.zip"
set "PYTHON="

echo ========================================
echo   Poker Analyzer - local offline
echo ========================================
echo.

rem --- prefer portable Python shipped with this folder ---
if exist "%PY_DIR%\python.exe" set "PYTHON=%PY_DIR%\python.exe"
if not defined PYTHON if exist "%PY_ZIP%" (
  echo Extracting portable Python...
  call :extract_python
  if exist "%PY_DIR%\python.exe" set "PYTHON=%PY_DIR%\python.exe"
)
if not defined PYTHON (
  echo First run: downloading portable Python %PY_VER% , about 11MB, one time...
  call :download_python
  if exist "%PY_DIR%\python.exe" set "PYTHON=%PY_DIR%\python.exe"
)
if defined PYTHON call :patch_pth

rem --- fallback: system Python ---
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
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
  echo [ERROR] Python not found. Need internet once to download portable Python,
  echo         or install Python 3.10+ and retry.
  goto :end
)

if not exist "%APP_DIR%\app.py" (
  echo [ERROR] app.py not found. Expected under poker_analyzer\.
  goto :end
)

if not exist "%APP_DIR%\static\js\chart.umd.min.js" (
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
ping -n 2 127.0.0.1 >nul

echo.
echo Starting...
echo Open: http://127.0.0.1:8000
echo Keep this window open. Press Ctrl+C to stop.
echo ========================================
echo.

cd /d "%APP_DIR%"
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

:download_python
if not exist "%ROOT%runtime" mkdir "%ROOT%runtime"
curl.exe -L --fail --retry 3 --connect-timeout 20 -o "%PY_ZIP%" "%PY_URL%"
if errorlevel 1 (
  powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%' } catch { exit 1 }"
)
if not exist "%PY_ZIP%" (
  echo [WARN] Download failed.
  goto :eof
)
call :extract_python
goto :eof

:extract_python
if not exist "%ROOT%runtime" mkdir "%ROOT%runtime"
if exist "%PY_DIR%" rmdir /s /q "%PY_DIR%"
mkdir "%PY_DIR%"
tar.exe -xf "%PY_ZIP%" -C "%PY_DIR%"
if not exist "%PY_DIR%\python.exe" (
  powershell -NoProfile -Command "Expand-Archive -LiteralPath '%PY_ZIP%' -DestinationPath '%PY_DIR%' -Force"
)
if not exist "%PY_DIR%\python.exe" (
  echo [WARN] Extract failed.
  if exist "%PY_DIR%" rmdir /s /q "%PY_DIR%"
)
goto :eof

:patch_pth
for %%f in ("%PY_DIR%\python*._pth") do (
  findstr /c:"poker_analyzer" "%%f" >nul 2>&1
  if errorlevel 1 (
    echo ..\..\poker_analyzer>>"%%f"
  )
)
goto :eof
