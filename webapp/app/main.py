from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import dataset_inventory, list_ollama_models, run_chat_assistant, run_knowledge_graph, run_root_cause, run_scenario_compare, run_validation
from .models import ChatRequest, CompareRequest, KnowledgeGraphRequest, RootCauseRequest, ValidationRequest


BASE_DIR = Path(__file__).resolve().parents[2]

app = FastAPI(
    title="IFSP Planning Copilot WebApp",
    version="1.0.0",
    description="Web application wrapper for IFSP validation, scenario comparison, and root-cause workflows.",
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(name="index.html", request=request)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ifsp-webapp", "base_dir": str(BASE_DIR)}


@app.get("/api/datasets/summary")
def datasets_summary():
    return dataset_inventory(BASE_DIR)


@app.get("/api/llm/models")
def llm_models():
    return list_ollama_models()


@app.post("/api/validate")
def validate(req: ValidationRequest):
    return run_validation(BASE_DIR, req.week_id, req.scenario_id, req.scope.model_dump(), req.focus_areas)


@app.post("/api/compare")
def compare(req: CompareRequest):
    return run_scenario_compare(
        BASE_DIR,
        req.week_id,
        req.base_scenario_id,
        req.compare_scenario_id,
        req.scope.model_dump(),
        req.metrics,
    )


@app.post("/api/root-cause")
def root_cause(req: RootCauseRequest):
    return run_root_cause(BASE_DIR, req.week_id, req.scenario_id, req.demand_id, req.scope.model_dump())


@app.post("/api/knowledge-graph")
def knowledge_graph(req: KnowledgeGraphRequest):
    return run_knowledge_graph(BASE_DIR, req.week_id, req.scenario_id, req.item_id, req.scope.model_dump())


@app.post("/api/chat")
def chat(req: ChatRequest):
    return run_chat_assistant(
        BASE_DIR,
        req.question,
        req.week_id,
        req.scenario_id,
        req.scope.model_dump(),
        req.llm_enabled,
        req.llm_model,
        [m.model_dump() for m in req.history],
    )
