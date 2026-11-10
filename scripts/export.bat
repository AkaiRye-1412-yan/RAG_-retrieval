@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "SRC=dist\AkaiRyeRAG"
set "DST=dist\AkaiRyeRAG_export"

if not exist "%SRC%\AkaiRyeRAG.exe" (
  echo [ERROR] %SRC%\AkaiRyeRAG.exe not found. Run scripts\build.bat first.
  pause
  exit /b 1
)

echo ============================================================
echo  Export a clean, shareable package
echo  Source: %SRC%
echo  Output: %DST%
echo ============================================================
echo.

echo [1/2] Removing old export folder...
if exist "%DST%" rmdir /S /Q "%DST%"
if errorlevel 1 goto err

echo [2/2] Copying program files (excluding .env, data\, log files)...
robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP /XD "%SRC%\data" /XF "%SRC%\.env"
if errorlevel 8 goto err

echo.
echo ============================================================
echo  Done: %DST%
echo.
echo  This folder contains ONLY the program:
echo    - AkaiRyeRAG.exe
echo    - _internal\
echo  It does NOT contain your .env (API keys) or data\ (knowledge base).
echo  The first run on the target PC creates a fresh .env and data\.
echo ============================================================
pause
exit /b 0

:err
echo.
echo [ERROR] Export failed. Close AkaiRyeRAG.exe and try again.
pause
exit /b 1
