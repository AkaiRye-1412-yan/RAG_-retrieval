@echo off
setlocal
cd /d "%~dp0.."

REM Dev mode: backend API (8000) + frontend Vite (5173)
start "AkaiRye API (uvicorn 8000)" cmd /k "uv run uvicorn akairye_rag.api.main:app --reload --port 8000"
start "AkaiRye Web (vite 5173)" cmd /k "cd frontend && npm run dev"

echo.
echo API docs: http://127.0.0.1:8000/docs
echo Frontend: http://localhost:5173
echo.
echo Desktop window with hot reload: set AKAIR_DEV=1 ^&^& uv run akairye-rag
pause