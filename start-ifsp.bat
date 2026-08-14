@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist logs mkdir logs

echo Stopping any previous IFSP processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports = @(3004,8001); foreach ($port in $ports) { $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue; if ($conns) { foreach ($conn in $conns) { if ($conn.OwningProcess) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } } } }; $pids = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('node.exe','python.exe') -and ($_.CommandLine -match 'src/server.js' -or $_.CommandLine -match 'webapp/run.py' -or $_.CommandLine -match 'ifspstory') } | Select-Object -ExpandProperty ProcessId; if ($pids) { Stop-Process -Id $pids -Force -ErrorAction SilentlyContinue }"

echo Waiting for the required ports to clear...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$count = 0; while ($count -lt 30) { $ports = @(3004,8001); $inUse = $false; foreach ($p in $ports) { $c = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue; if ($c) { $inUse = $true; break } }; if (-not $inUse) { exit 0 }; Start-Sleep -Milliseconds 500; $count++ }; exit 1"
if errorlevel 1 (
  echo ERROR: One or more required ports are still in use. Please run stop-ifsp.bat and try again.
  exit /b 1
)

start "" /b "%ComSpec%" /d /c "cd /d ""%~dp0"" && call .venv\Scripts\activate.bat && set PYTHON_BASE_URL=http://localhost:8001 && python webapp\run.py --host 127.0.0.1 --port 8001 > logs\ifsp-python.log 2>&1"
start "" /b "%ComSpec%" /d /c "cd /d ""%~dp0"" && set PORT=3004 && set PYTHON_BASE_URL=http://localhost:8001 && npm start > logs\ifsp-node.log 2>&1"

echo Waiting for Python backend...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$end = (Get-Date).AddSeconds(30); while ((Get-Date) -lt $end) { $client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', 8001); $client.Close(); exit 0 } catch { $client.Dispose() }; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo ERROR: Python backend did not start. Check logs\ifsp-python.log
  call "%~dp0stop-ifsp.bat"
  exit /b 1
)

echo Waiting for Node app...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$end = (Get-Date).AddSeconds(30); while ((Get-Date) -lt $end) { $client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', 3004); $client.Close(); exit 0 } catch { $client.Dispose() }; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo ERROR: Node app did not start. Check logs\ifsp-node.log
  call "%~dp0stop-ifsp.bat"
  exit /b 1
)

echo IFSP services started.
echo Python backend: http://localhost:8001
echo Node shell: http://localhost:3004
echo Open the app here: http://localhost:3004/login
echo Use stop-ifsp.bat to stop the app.
endlocal
exit /b 0
