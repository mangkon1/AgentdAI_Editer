@echo off
REM ============================================================
REM  build_exe.bat  —  Build GeminiAgentApp.exe with PyInstaller
REM  Run this script from the project root directory.
REM  Uses "py -m" launcher so it works without pip/pyinstaller
REM  on PATH (only py.exe needs to be available).
REM ============================================================

echo.
echo  =====================================================
echo   Local AI Coding Agent  --  PyInstaller Builder
echo  =====================================================
echo.

REM --- Detect Python launcher ---
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=py
    echo [INFO] Using Python launcher: py
    goto :deps
)
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=python
    echo [INFO] Using: python
    goto :deps
)
echo ERROR: Python not found. Please install Python and try again.
pause
exit /b 1

:deps
echo.
echo [1/3] Installing / upgrading dependencies...
%PYTHON% -m pip install --upgrade -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip install failed. Aborting.
    pause
    exit /b 1
)

echo.
echo [2/3] Installing PyInstaller...
%PYTHON% -m pip install --upgrade pyinstaller
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller install failed. Aborting.
    pause
    exit /b 1
)

echo.
echo [3/3] Running PyInstaller...
%PYTHON% -m PyInstaller ^
    --noconsole ^
    --onefile ^
    --name GeminiAgentApp ^
    --collect-all customtkinter ^
    --collect-all google.genai ^
    --hidden-import google.genai ^
    --hidden-import google.genai.types ^
    --hidden-import customtkinter ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo =====================================================
echo  Build complete!
echo  Output: dist\GeminiAgentApp.exe
echo =====================================================
echo.
echo  NOTE: config.json is NOT bundled (stores your API key).
echo        The app will auto-create config.json on first run
echo        in the same folder as the .exe.
echo.
pause
