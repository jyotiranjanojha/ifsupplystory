# Intel Foundry Planning AI Assistant

Deployable web application wrapper for IFSP workflows using `by_input/` and `by_output/` datasets.

## Features
- Web UI for planners
- REST APIs for validation, scenario comparison, and root-cause workflows
- Optional local LLM summarization through Ollama for planner-friendly chat responses
- Folder-first data convention:
  - `by_input/`: BY ESP input datasets
  - `by_output/`: BY ESP generated outputs
- Snowflake can be added as fallback in API logic

## Run Locally
From repository root:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r webapp/requirements.txt
uvicorn webapp.app.main:app --reload
```

Open `http://127.0.0.1:8000`.

### Optional Local Nollama or Ollama Integration
If Nollama or Ollama is already installed and running locally, the chat assistant can use it to turn grounded workflow results into more natural planner-facing answers.

Default settings:

```bash
LLM_PROVIDER=nollama
NOLLAMA_BASE_URL=http://127.0.0.1:8000
NOLLAMA_MODEL=qwen2@GPU

# Backward-compatible aliases used by some helper paths.
OLLAMA_BASE_URL=http://127.0.0.1:8000
OLLAMA_MODEL=qwen2@GPU

# Optional DataFrame-backed SQL execution
# When true, DuckDB registers CSVs through pandas DataFrames.
SQL_USE_PANDAS=false

# Optional Snowflake DataFrame execution path
# Applies only when SQL_BACKEND=snowflake.
SNOWFLAKE_USE_PANDAS=false
```

For a local Ollama server that exposes a different endpoint, set `OLLAMA_BASE_URL` and `OLLAMA_MODEL` to that server instead.

The application keeps BY workflow logic grounded in local data and uses the configured LLM only to summarize the computed result.

If Ollama is unavailable, the app automatically falls back to the built-in rule-based response format.

### Auto-select Free Port (Recommended)
If `8000` is busy, run the launcher script to automatically pick the next available port.

```bash
python webapp/run.py --reload
```

Optional flags:

```bash
python webapp/run.py --host 127.0.0.1 --port 8000 --max-tries 30 --reload
```

## API Endpoints
- `GET /api/health`
- `GET /api/datasets/summary`
- `POST /api/validate`
- `POST /api/compare`
- `POST /api/root-cause`
- `POST /api/chat`

## Docker or Podman Build and Run
From repository root:

```bash
docker build -t ifsp-webapp -f webapp/Dockerfile .
docker run --rm -p 8000:8000 ifsp-webapp
```

For a local Podman test with Nollama already running on the host at `http://127.0.0.1:8000`, publish the web app on a different host port so the host Nollama port remains free:

```powershell
podman build -t ifsp-webapp -f webapp/Dockerfile .

podman run --rm -p 8010:8000 `
  -e LLM_PROVIDER=nollama `
  -e NOLLAMA_BASE_URL=http://host.containers.internal:8000 `
  -e NOLLAMA_MODEL=qwen2@GPU `
  -e OLLAMA_BASE_URL=http://host.containers.internal:8000 `
  -e OLLAMA_MODEL=qwen2@GPU `
  -v "${PWD}\by_input:/app/by_input:ro" `
  -v "${PWD}\by_output:/app/by_output:ro" `
  ifsp-webapp
```

Then validate the integration:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/health
Invoke-RestMethod http://127.0.0.1:8010/api/llm/models
```

A repeatable smoke test is available in `podman-smoke-test.ps1` at the repository root.

## Deploy Options
- Azure Container Apps
- Azure App Service (container)
- AKS/Kubernetes
- Any platform that runs a Python container

## Notes
- Current scenario and root-cause analysis uses file-snapshot evidence and returns data-gap guidance when scenario-grain metadata is missing.
- Extend `webapp/app/analyzer.py` to add Snowflake SQL and lineage graph calls for full production behavior.
