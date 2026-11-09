@echo off
chcp 936 >nul
setlocal
cd /d %~dp0..

REM 开发模式：启动后端(8000) + 前端 Vite(5173)
start "AkaiRye API (uvicorn 8000)" cmd /k "uv run uvicorn akairye_rag.api.main:app --reload --port 8000"
start "AkaiRye Web (vite 5173)" cmd /k "cd frontend && npm run dev"

echo.
echo 后端: http://127.0.0.1:8000/docs
echo 前端: http://localhost:5173
echo.
echo 如需桌面壳联调，另开终端运行: set AKAIR_DEV=1 ^& uv run akairye-rag
echo.
pause
