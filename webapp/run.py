import argparse
import importlib.util
import os
import socket
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


def main() -> None:
    # Load .env before anything else so env vars are set before module imports
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    parser = argparse.ArgumentParser(description="Run IFSP web app on a free port.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Preferred starting port (default: 8000)")
    parser.add_argument("--max-tries", type=int, default=30, help="Number of ports to scan (default: 30)")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload for development")
    args = parser.parse_args()

    selected_port = pick_port(args.host, args.port, args.max_tries)
    print(f"[IFSP] Starting server at http://{args.host}:{selected_port}")

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
