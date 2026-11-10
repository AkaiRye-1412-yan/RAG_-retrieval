@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "OUTDIR=dist\AkaiRyeRAG"
set "KEEPDIR=dist\.akairye_userdata"

echo ============================================================
echo  AkaiRye RAG - build (frontend -^> uv sync -^> PyInstaller)
echo ============================================================
echo.

echo [!] Please close AkaiRyeRAG.exe before building.
echo     PyInstaller --noconfirm deletes the whole output folder,
echo     so .env and data\ are moved aside and restored automatically.
echo.

rem ---- Refuse to build while the packaged app holds the database open ----
tasklist /FI "IMAGENAME eq AkaiRyeRAG.exe" 2>NUL | find /I "AkaiRyeRAG.exe" >NUL
if not errorlevel 1 (
  echo [ERROR] AkaiRyeRAG.exe is still running.
  echo         Close it first, otherwise data\ cannot be moved aside and may be deleted.
  pause
  exit /b 1
)

call :protect_userdata
if errorlevel 1 goto err

echo [1/3] Building frontend (Vue3 + Vite)...
pushd frontend
call npm install
if errorlevel 1 goto err
call npm run build
if errorlevel 1 goto err
popd

echo.
echo [2/3] Syncing Python environment (Python 3.12 + uv)...
call uv sync
if errorlevel 1 goto err

echo.
echo [3/3] Packaging with PyInstaller (onedir)...
call uv run pyinstaller akairye.spec --noconfirm --clean
if errorlevel 1 goto err

call :restore_userdata

echo.
echo ============================================================
echo  Done: dist\AkaiRyeRAG\AkaiRyeRAG.exe
echo  User data (.env + data\) has been restored next to the exe.
echo.
echo  For sharing with others, run scripts\export.bat to produce
echo  dist\AkaiRyeRAG_export WITHOUT .env or data\ (no API keys).
echo ============================================================
pause
exit /b 0

:err
echo.
echo [ERROR] Build failed. See the log above.
call :restore_userdata
pause
exit /b 1

rem ---- Protect .env and data\ from PyInstaller's output-dir wipe ----
:protect_userdata
if not exist "%OUTDIR%" exit /b 0
if not exist "%KEEPDIR%" mkdir "%KEEPDIR%"
if exist "%OUTDIR%\.env" (
  move /Y "%OUTDIR%\.env" "%KEEPDIR%\.env" >nul
  if not exist "%KEEPDIR%\.env" (
    echo [ERROR] Could not move .env aside. Abort to protect user data.
    exit /b 1
  )
  echo   [keep] .env moved to %KEEPDIR%
)
if exist "%OUTDIR%\data" (
  if exist "%KEEPDIR%\data" rmdir /S /Q "%KEEPDIR%\data"
  move /Y "%OUTDIR%\data" "%KEEPDIR%\data" >nul
  if not exist "%KEEPDIR%\data" (
    echo [ERROR] Could not move data\ aside ^(files may be locked^).
    echo         Aborting BEFORE PyInstaller so the knowledge base is not deleted.
    exit /b 1
  )
  echo   [keep] data\ moved to %KEEPDIR%
)
exit /b 0

:restore_userdata
if not exist "%KEEPDIR%" exit /b 0
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if exist "%KEEPDIR%\.env" (
  move /Y "%KEEPDIR%\.env" "%OUTDIR%\.env" >nul
  echo   [restore] .env
)
if exist "%KEEPDIR%\data" (
  if exist "%OUTDIR%\data" rmdir /S /Q "%OUTDIR%\data"
  move /Y "%KEEPDIR%\data" "%OUTDIR%\data" >nul
  echo   [restore] data\
)
rmdir "%KEEPDIR%" 2>nul
if exist "%KEEPDIR%" (
  echo   [WARN] Could not restore everything from %KEEPDIR%
  echo          Make sure AkaiRyeRAG.exe is closed, then move the folder back manually.
)
exit /b 0
