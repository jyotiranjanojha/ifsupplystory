#!/usr/bin/env bash
set -euo pipefail

if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  curl -fsS http://127.0.0.1:3000/api/health >/dev/null 2>&1
else
  exit 1
fi
