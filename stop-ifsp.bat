@echo off
setlocal EnableExtensions

echo Stopping IFSP services...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('node.exe','python.exe') -and ($_.CommandLine -match 'src/server.js' -or $_.CommandLine -match 'webapp/run.py' -or $_.CommandLine -match 'ifspstory') } | Select-Object -ExpandProperty ProcessId; if ($pids) { Stop-Process -Id $pids -Force -ErrorAction SilentlyContinue }; foreach ($port in 3004,8001) { $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue; if ($conns) { foreach ($conn in $conns) { if ($conn.OwningProcess) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } } } }"

echo IFSP services stopped.
endlocal
exit /b 0
