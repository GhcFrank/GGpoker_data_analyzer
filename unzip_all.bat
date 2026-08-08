@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "all_zip" (
    echo [ERROR] all_zip folder not found.
    pause
    exit /b 1
)

if not exist "all_hand" mkdir "all_hand"

set /a total=0
set /a ok=0
set /a fail=0

for %%f in ("all_zip\*.zip") do (
    set /a total+=1
    echo Extracting: %%~nxf
    tar -xf "%%f" -C "all_hand"
    if errorlevel 1 (
        set /a fail+=1
        echo   [FAIL] %%~nxf
    ) else (
        set /a ok+=1
    )
)

echo.
echo Done. total=%total% ok=%ok% fail=%fail%
echo Output: %cd%\all_hand
pause
