@echo off
title AUREUS-SMC Institutional Gold Engine - Sandbox Test
echo =================================================================
echo   EJECUTANDO SIMULADOR SANDBOX AUREUS-SMC (XAU/USD)
echo =================================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Entorno virtual .venv no encontrado.
    pause
    exit /b 1
)

.venv\Scripts\python.exe scripts\run_sandbox.py
pause
