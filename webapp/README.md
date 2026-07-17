# IFSP Planning Copilot WebApp

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

### Optional Local Ollama Integration
If Ollama is already installed and running locally, the chat assistant can use it to turn grounded workflow results into more natural planner-facing answers.

Default settings:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:latest
```

The application keeps BY workflow logic grounded in local data and uses Ollama only to summarize the computed result.

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

## Docker Build and Run
From repository root:

```bash
docker build -t ifsp-webapp -f webapp/Dockerfile .
docker run --rm -p 8000:8000 ifsp-webapp
```

## Deploy Options
- Azure Container Apps
- Azure App Service (container)
- AKS/Kubernetes
- Any platform that runs a Python container

## Notes
- Current scenario and root-cause analysis uses file-snapshot evidence and returns data-gap guidance when scenario-grain metadata is missing.
- Extend `webapp/app/analyzer.py` to add Snowflake SQL and lineage graph calls for full production behavior.
