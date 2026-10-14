@echo off
REM ============================================================
REM  build_exe.bat  —  Build GeminiAgentApp.exe with PyInstaller
REM  Run this script from the project root directory.
REM ============================================================

echo.
echo  =====================================================
echo   Local AI Coding Agent  —  PyInstaller Builder
echo  =====================================================
echo.

REM --- Install / upgrade dependencies first ---
echo [1/3] Installing / upgrading dependencies...
pip install --upgrade -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip install failed. Aborting.
    pause
    exit /b 1
)

echo.
echo [2/3] Running PyInstaller...
pyinstaller ^
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
echo [3/3] Build complete!
echo  Output: dist\GeminiAgentApp.exe
echo.
echo  NOTE: config.json is NOT bundled (it stores your API key).
echo        The app will create config.json on first run in the
echo        same folder as the .exe.
echo.
pause
