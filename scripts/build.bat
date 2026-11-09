@echo off
chcp 936 >nul
setlocal
cd /d %~dp0..

echo ============================================================
echo  AkaiRye 知识RAG平台 - 打包脚本（前端构建 -^> uv sync -^> PyInstaller）
echo ============================================================

echo.
echo [1/3] 构建前端（Vue3 + Vite）...
pushd frontend
call npm install || goto :err
call npm run build || goto :err
popd

echo.
echo [2/3] 同步 Python 环境（Python 3.12 + uv）...
call uv sync || goto :err

echo.
echo [3/3] PyInstaller 打包（onedir）...
call uv run pyinstaller akairye.spec --noconfirm --clean || goto :err

echo.
echo ============================================================
echo  打包完成： dist\AkaiRyeRAG\AkaiRyeRAG.exe
echo  首次双击运行会在 exe 旁自动生成 .env 与 data 目录。
echo ============================================================
pause
exit /b 0

:err
echo.
echo [错误] 构建失败，请查看上方日志。
pause
exit /b 1
