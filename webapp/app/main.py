from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import dataset_inventory, list_ollama_models, run_chat_assistant, run_insights, run_knowledge_graph, run_log_reader, run_root_cause, run_scenario_compare, run_validation, run_vision_query
from .langgraph_bom import run_bom_drill
from .text_to_sql_agent import run_sql_query
from .models import BomDrillRequest, ChatRequest, CompareRequest, InsightsRequest, KnowledgeGraphRequest, RagQueryRequest, RagReindexRequest, RootCauseRequest, SqlQueryRequest, ValidationRequest, VisionQueryRequest
from .rag import build_rag_index, get_rag_status, query_rag


BASE_DIR = Path(__file__).resolve().parents[2]

app = FastAPI(
    title="Intel Foundry Planning AI Assistant",
    version="1.0.0",
    description="Web application wrapper for IFSP validation, scenario comparison, and root-cause workflows.",
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/intelfoundrylogo.png")


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


@app.get("/api/rag/status")
def rag_status():
    return get_rag_status(BASE_DIR)


@app.post("/api/rag/reindex")
def rag_reindex(req: RagReindexRequest):
    return build_rag_index(
        BASE_DIR,
        force=req.force,
        max_rows_per_file=req.max_rows_per_file,
    )


@app.post("/api/rag/query")
def rag_query(req: RagQueryRequest):
    return query_rag(
        BASE_DIR,
        req.question,
        top_k=req.top_k,
        week_id=req.week_id,
        scenario_id=req.scenario_id,
        site=req.scope.site,
        item_id=req.item_id,
    )


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
    demand_entity = req.demand_entity.model_dump() if req.demand_entity else None
    return run_root_cause(
        BASE_DIR,
        req.week_id,
        req.scenario_id,
        req.demand_id,
        req.scope.model_dump(),
        demand_entity=demand_entity,
    )


@app.post("/api/insights")
def insights(req: InsightsRequest):
    return run_insights(
        BASE_DIR,
        req.week_id,
        req.scenario_id,
        req.base_scenario_id,
        req.compare_scenario_id,
        req.scope.model_dump(),
    )


@app.post("/api/knowledge-graph")
def knowledge_graph(req: KnowledgeGraphRequest):
    return run_knowledge_graph(BASE_DIR, req.week_id, req.scenario_id, req.item_id, req.scope.model_dump())


@app.post("/api/bom-drill")
def bom_drill(req: BomDrillRequest):
    return run_bom_drill(
        BASE_DIR,
        req.week_id,
        req.scenario_id,
        req.root_item,
        req.scope.model_dump(),
        max_depth=req.max_depth,
    )


@app.post("/api/sql-query")
def sql_query(req: SqlQueryRequest):
    return run_sql_query(
        BASE_DIR,
        req.question,
        req.week_id,
        req.scenario_id,
        req.scope.model_dump(),
    )


@app.post("/api/vision-query")
def vision_query_endpoint(req: VisionQueryRequest):
    return run_vision_query(
        BASE_DIR,
        req.question,
        req.image_base64,
        req.week_id,
        req.scenario_id,
        req.scope.model_dump(),
    )


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
