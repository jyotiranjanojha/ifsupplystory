@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('node.exe','python.exe') -and ($_.CommandLine -match 'src/server.js' -or $_.CommandLine -match 'webapp/run.py' -or $_.CommandLine -match 'ifspstory') } | Select-Object -ExpandProperty ProcessId; if ($pids) { Stop-Process -Id $pids -Force -ErrorAction SilentlyContinue }; foreach ($port in 3004,3005,8001,8002) { try { $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction Stop; foreach ($c in $conns) { if ($c.OwningProcess) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } } } catch {} }"

echo IFSP services stopped.
endlocal
