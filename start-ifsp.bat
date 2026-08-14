@echo off
setlocal
cd /d "%~dp0"

call stop-ifsp.bat 2>nul

set "PORT=3004"
set "HOST=localhost"
set "PYTHON_BASE_URL=http://localhost:8001"

start /b "" cmd /c "cd /d "%~dp0" && call .venv\Scripts\activate.bat && set PYTHON_BASE_URL=http://localhost:8001 && python webapp/run.py --host localhost --port 8001 > logs\ifsp-ui.log 2>&1"
start /b "" cmd /c "cd /d "%~dp0" && set PORT=3004 && set PYTHON_BASE_URL=http://localhost:8001 && npm start > logs\ifsp-node.log 2>&1"

if not exist logs mkdir logs

echo IFSP UI: http://localhost:8001
echo Node shell: http://localhost:3004
echo Open the app here: http://localhost:3004/login
echo Use stop-ifsp.bat to stop the app.
endlocal
