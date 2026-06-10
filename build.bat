@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  Windows Scanner Agent — Build Script
::  Produces:  dist\scanner.exe  (single portable executable)
::  Requires:  Python 3.8+ with pip  (only on the BUILD machine)
:: ============================================================

set SCRIPT_DIR=%~dp0
set DIST_DIR=%SCRIPT_DIR%dist
set BUILD_DIR=%SCRIPT_DIR%build

echo.
echo ============================================================
echo   Windows Scanner Agent - Build
echo ============================================================

:: ── 1. Verify Python is available ───────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.8+ and add it to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   Python : %%v

:: ── 2. Verify pip ────────────────────────────────────────────
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found. Run: python -m ensurepip
    pause
    exit /b 1
)

:: ── 3. Install / upgrade PyInstaller ─────────────────────────
echo.
echo   Installing / upgrading PyInstaller...
python -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] PyInstaller install failed.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('pyinstaller --version 2^>^&1') do echo   PyInstaller : %%v

:: ── 4. Create collectors\__init__.py if missing ──────────────
if not exist "%SCRIPT_DIR%collectors\__init__.py" (
    echo. > "%SCRIPT_DIR%collectors\__init__.py"
    echo   Created collectors\__init__.py
)

:: ── 5. Clean previous build artefacts ───────────────────────
echo.
echo   Cleaning previous build...
if exist "%BUILD_DIR%" rd /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%"  rd /s /q "%DIST_DIR%"

:: ── 6. Run PyInstaller ───────────────────────────────────────
echo.
echo   Building scanner.exe ...
echo.
pyinstaller scanner.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. Check output above.
    pause
    exit /b 1
)

:: ── 7. Verify output ─────────────────────────────────────────
set EXE_PATH=%DIST_DIR%\scanner.exe
if not exist "%EXE_PATH%" (
    echo [ERROR] Expected output not found: %EXE_PATH%
    pause
    exit /b 1
)

:: Print file size
for %%F in ("%EXE_PATH%") do set EXE_SIZE=%%~zF
set /a EXE_SIZE_MB=!EXE_SIZE! / 1048576

echo.
echo ============================================================
echo   Build successful!
echo   Output : %EXE_PATH%
echo   Size   : ~!EXE_SIZE_MB! MB
echo ============================================================
echo.
echo   To run the scanner:
echo     dist\scanner.exe
echo     dist\scanner.exe --output C:\Reports\my_machine.json
echo     dist\scanner.exe --skip software folders
echo.

pause
endlocal