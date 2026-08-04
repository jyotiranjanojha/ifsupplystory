from pathlib import Path
import base64
import json
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import dataset_inventory, generate_input_dq_html_report, generate_validation_html_report, list_ollama_models, run_chat_assistant, run_input_data_quality, run_insights, run_knowledge_graph, run_log_reader, run_root_cause, run_root_cause_explained, run_scenario_compare, run_validation, run_vision_query, send_html_email_report, smtp_health_check
from .langgraph_bom import run_bom_drill
from .text_to_sql_agent import run_sql_query
from .models import BomDrillRequest, ChatRequest, CompareRequest, InsightsRequest, KnowledgeGraphRequest, RagQueryRequest, RagReindexRequest, RootCauseRequest, SqlQueryRequest, ValidationReportEmailRequest, ValidationReportRequest, ValidationRequest, VisionQueryRequest
from .rag import build_rag_index, get_rag_status, query_rag
from .rag_openvino import build_openvino_rag_index, export_embedding_model, get_openvino_rag_status, query_openvino_rag


BASE_DIR = Path(__file__).resolve().parents[2]

app = FastAPI(
    title="Intel Foundry Planning AI Assistant",
    version="1.0.0",
    description="Web application wrapper for IFSP validation, scenario comparison, and root-cause workflows.",
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _extract_auth_profile(request: Request) -> dict:
    headers = request.headers

    login = (headers.get("x-ms-client-principal-name") or "").strip() or None
    email = (
        headers.get("x-forwarded-email")
        or headers.get("x-user-email")
        or headers.get("x-auth-request-email")
        or headers.get("x-ms-client-principal-name")
        or ""
    ).strip() or None
    source = None

    principal_header = (headers.get("x-ms-client-principal") or "").strip()
    if principal_header:
        try:
            decoded = base64.b64decode(principal_header)
            principal = json.loads(decoded.decode("utf-8"))
            source = "x-ms-client-principal"
            if not login:
                login = principal.get("userDetails") or principal.get("userId") or login
            claims = principal.get("claims") or []
            for claim in claims:
                typ = (claim.get("typ") or "").lower()
                val = (claim.get("val") or "").strip()
                if typ in {"preferred_username", "email", "upn"} and val:
                    email = email or val
                    break
        except Exception:
            pass

    if not source:
        if headers.get("x-ms-client-principal-name"):
            source = "x-ms-client-principal-name"
        elif headers.get("x-forwarded-email") or headers.get("x-user-email") or headers.get("x-auth-request-email"):
            source = "forwarded-email-header"
        elif request.headers.get("remote-user"):
            source = "remote-user"

    return {
        "authenticated": bool(login or email),
        "login": login,
        "email": email,
        "source": source or "none",
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/intelfoundrylogo.png")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(name="index.html", request=request)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ifsp-webapp", "base_dir": str(BASE_DIR)}


@app.get("/api/auth/me")
def auth_me(request: Request):
    return _extract_auth_profile(request)


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
        max_docs=req.max_docs,
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


@app.get("/api/rag/openvino/status")
def rag_openvino_status():
    return get_openvino_rag_status(BASE_DIR)


@app.post("/api/rag/openvino/export-embedding")
def rag_openvino_export_embedding():
    """Export bge-small-en-v1.5 to OpenVINO IR (run once before first reindex)."""
    return export_embedding_model()


@app.post("/api/rag/openvino/reindex")
def rag_openvino_reindex(force: bool = False):
    return build_openvino_rag_index(BASE_DIR, force=force)


@app.post("/api/rag/openvino/query")
def rag_openvino_query(req: RagQueryRequest):
    return query_openvino_rag(
        BASE_DIR,
        req.question,
        week_id=req.week_id,
        scenario_id=req.scenario_id,
        top_k=req.top_k,
    )


@app.post("/api/validate")
def validate(req: ValidationRequest):
    return run_validation(BASE_DIR, req.week_id, req.scenario_id, req.scope.model_dump(), req.focus_areas)


def _resolve_validation_report(req: ValidationReportRequest):
    focus = (req.focus_area or "").strip().lower()
    if focus == "data_quality_input":
        report = run_input_data_quality(BASE_DIR, req.week_id, req.scenario_id)
        title = "BY Input Data Quality Report"
        html_content = generate_input_dq_html_report(report)
        file_stem = "by_input_data_quality"
    else:
        report = run_validation(BASE_DIR, req.week_id, req.scenario_id, {}, [focus])
        title = f"Validation Report - {focus.replace('_', ' ').title()}"
        html_content = generate_validation_html_report(report, title=title)
        file_stem = f"validation_{focus}"
    return report, title, html_content, file_stem


@app.post("/api/validate/report/html")
def validate_report_html(req: ValidationReportRequest):
    _report, _title, html_content, file_stem = _resolve_validation_report(req)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{file_stem}_{timestamp}.html"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=html_content, media_type="text/html", headers=headers)


@app.post("/api/validate/report/email")
def validate_report_email(req: ValidationReportEmailRequest, request: Request):
    auth = _extract_auth_profile(request)
    recipient = (req.recipient_email or auth.get("email") or "").strip()
    if not recipient:
        return {
            "sent": False,
            "error": "Could not determine recipient email from SSO headers. Please configure auth headers or pass recipient_email.",
            "auth": auth,
        }

    report, title, html_content, _file_stem = _resolve_validation_report(req)
    score = ((report.get("Summary") or {}).get("overall_score_pct"))
    score_suffix = f" - Score {score}%" if score is not None else ""
    subject = f"{title}{score_suffix}"
    text = f"{title} generated by IFSP assistant.{(' Overall score: ' + str(score) + '%.') if score is not None else ''}"
    sent, message = send_html_email_report(recipient, subject, html_content, text)
    return {
        "sent": sent,
        "message": message,
        "recipient_email": recipient,
        "auth": auth,
        "focus_area": req.focus_area,
    }


@app.get("/api/email/smtp/health")
def email_smtp_health():
    return smtp_health_check()


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
    return run_root_cause_explained(
        BASE_DIR,
        req.week_id,
        req.scenario_id,
        req.demand_id,
        req.scope.model_dump(),
        question_type=req.question_type or "full_diagnosis",
        llm_model=req.llm_model,
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
