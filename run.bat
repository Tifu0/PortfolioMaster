@echo off
setlocal
echo ========================================================
echo  PortfolioMaster - Launching Services
echo ========================================================

REM 1. Set up Python virtual environment
if not exist venv (
    echo [Backend] Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate
    echo [Backend] Installing Python dependencies...
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate
)

REM 2. Set up Frontend Node dependencies if not installed
if not exist "frontend\node_modules" (
    echo [Frontend] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

echo.
echo Starting FastAPI backend on http://localhost:8000...
start "PortfolioMaster Backend" cmd /k "call venv\Scripts\activate && uvicorn backend.api.main:app --reload --port 8000 --env-file .env"

echo Starting Next.js frontend on http://localhost:3000...
start "PortfolioMaster Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Services are launching:
echo  - Frontend:         http://localhost:3000
echo  - Backend API:      http://localhost:8000
echo  - API Docs Swagger: http://localhost:8000/docs
echo ========================================================
