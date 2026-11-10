@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo  AkaiRye RAG - build (frontend -^> uv sync -^> PyInstaller)
echo ============================================================
echo.

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

echo.
echo ============================================================
echo  Done: dist\AkaiRyeRAG\AkaiRyeRAG.exe
echo  First run creates .env and data\ next to the exe.
echo ============================================================
pause
exit /b 0

:err
echo.
echo [ERROR] Build failed. See the log above.
pause
exit /b 1