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
  pause
  exit /b 1
)

if not exist "static\js\chart.umd.min.js" (
  echo [ERROR] Missing local chart.js: static\js\chart.umd.min.js
  pause
  exit /b 1
)

echo Using: %PYTHON%
"%PYTHON%" --version
echo.
echo Local offline mode
echo URL: http://127.0.0.1:8000
echo Keep this window open while using the page.
echo.

rem Open browser after server has a moment to start
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

"%PYTHON%" -m uvicorn app:app --host 127.0.0.1 --port 8000
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
  echo [ERROR] Server exited with code %EXITCODE%
  echo If port 8000 is busy, close the old process first.
  echo If missing modules, run:
  echo "%PYTHON%" -m pip install -r requirements.txt
)
pause
exit /b %EXITCODE%
