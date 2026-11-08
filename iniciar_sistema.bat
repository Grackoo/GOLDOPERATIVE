@echo off
title AUREUS-SMC Institutional Gold Engine - Live Server
echo =================================================================
echo   INICIANDO MOTOR INSTITUCIONAL AUREUS-SMC (XAU/USD)
echo =================================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Entorno virtual .venv no encontrado.
    pause
    exit /b 1
)

echo Iniciando servidor FastAPI y WebSockets en http://localhost:8000 ...
start "" "http://localhost:8000"
.venv\Scripts\python.exe scripts\run_live.py
pause
