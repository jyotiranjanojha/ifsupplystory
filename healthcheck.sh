#!/usr/bin/env bash
set -euo pipefail

# The actual IFSP web UI runs on 8001 to avoid clashing with the local NoLlama/Nollama UI.
if curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
  curl -fsS http://127.0.0.1:3000/api/health >/dev/null 2>&1
else
  exit 1
fi
