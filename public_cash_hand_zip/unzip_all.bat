@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "..\public_cash_hand" mkdir "..\public_cash_hand"

set /a total=0
set /a ok=0
set /a fail=0

for %%f in ("*.zip") do (
    set /a total+=1
    echo Extracting: %%~nxf
    tar -xf "%%f" -C "..\public_cash_hand"
    if errorlevel 1 (
        set /a fail+=1
        echo   [FAIL] %%~nxf
    ) else (
        set /a ok+=1
    )
)

echo.
echo Done. total=%total% ok=%ok% fail=%fail%
echo Output: %cd%\..\public_cash_hand
pause
