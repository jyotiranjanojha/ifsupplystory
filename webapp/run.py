import argparse
import importlib.util
import json
import os
import socket
import threading
from pathlib import Path

import uvicorn


def _load_dotenv(env_path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ (no override)."""
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:   # existing env vars take priority
                os.environ[key] = value


def _warmup_llm() -> None:
    """Send a tiny request to pre-warm the LLM so the first user query isn't cold."""
    import urllib.request, urllib.error
    provider = os.getenv("LLM_PROVIDER", "nollama").lower()
    if provider not in ("nollama", "custom"):
        return  # cloud providers (openai, azure, anthropic) are always warm
    base_url = os.getenv("NOLLAMA_BASE_URL", "http://localhost:8000") if provider == "nollama" \
               else os.getenv("CUSTOM_LLM_BASE_URL", "")
    if not base_url:
        return
    model = os.getenv("NOLLAMA_MODEL", "qwen2@GPU") if provider == "nollama" \
            else os.getenv("CUSTOM_LLM_MODEL", "")
    try:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # No semaphore — warmup runs independently; model loading happens on the LLM server
        urllib.request.urlopen(req, timeout=180)
        print(f"[IFSP] LLM warmed up ({provider} / {model})")
    except Exception as e:
        print(f"[IFSP] LLM warmup skipped: {e}")

# Load .env BEFORE importing the app so module-level env vars (NOLLAMA_MODEL, etc.) are set correctly
_load_dotenv(Path(__file__).resolve().parents[1] / ".env")

try:
    from webapp.app.main import app as fastapi_app
except ModuleNotFoundError:
    from app.main import app as fastapi_app


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex((host, port)) != 0


def pick_port(host: str, start_port: int, max_tries: int) -> int:
    for port in range(start_port, start_port + max_tries):
        if _port_is_free(host, port):
            return port
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_tries - 1}")


def resolve_port(host: str, port: int, max_tries: int) -> int:
    if _port_is_free(host, port):
        return port

    for candidate in range(port, port + max_tries):
        if _port_is_free(host, candidate):
            print(f"[IFSP] Port {port} is already in use; using {candidate} instead.")
            return candidate

    raise RuntimeError(f"Port {port} is already in use and no fallback port is available in range {port}-{port + max_tries - 1}.")


def main() -> None:
    # Load .env before anything else so env vars are set before module imports
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    parser = argparse.ArgumentParser(description="Run IFSP web app on a free port.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8001, help="Preferred starting port (default: 8001)")
    parser.add_argument("--max-tries", type=int, default=30, help="Number of ports to scan (default: 30)")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload for development")
    args = parser.parse_args()

    selected_port = resolve_port(args.host, args.port, args.max_tries)
    print(f"[IFSP] Starting server at http://{args.host}:{selected_port}")

    # Warm up the LLM in background so first user query isn't cold-start slow
    threading.Thread(target=_warmup_llm, daemon=True).start()

    if args.reload:
        try:
            has_workspace_pkg = importlib.util.find_spec("webapp.app.main") is not None
        except ModuleNotFoundError:
            has_workspace_pkg = False
        app_target = "webapp.app.main:app" if has_workspace_pkg else "app.main:app"
    else:
        app_target = fastapi_app

    uvicorn.run(
        app_target,
        host=args.host,
        port=selected_port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
