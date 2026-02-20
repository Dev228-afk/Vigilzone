@echo off
REM CCTV AI Module Launcher for Windows
REM This script launches the AI module with proper environment

echo ========================================
echo CCTV AI Module - Starting...
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9+ and try again
    pause
    exit /b 1
)

REM Change to ai_module directory
cd /d "%~dp0"

REM Check if requirements are installed
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Check PyTorch
python -c "import torch" >nul 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: PyTorch not found!
    echo Please install PyTorch first:
    echo CPU: pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    echo CUDA: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
    pause
    exit /b 1
)

echo.
echo Starting CCTV AI Module...
echo Web UI will be available at: http://127.0.0.1:8000
echo.
echo Press Ctrl+C to stop
echo ========================================
echo.

REM Run the application
python run.py

pause
