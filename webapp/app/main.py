from pathlib import Path
import base64
import json
import os
import time
from datetime import datetime
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import ALLOWED_SEMANTIC_MODES, LLM_CONFIG, SEMANTIC_MODE, STREAM_LLM_HTTP_TIMEOUT_SECS, STREAM_LLM_TTFT_TIMEOUT_SECS, _update_chat_session_context, build_grounded_chat_prompt, build_no_llm_deterministic_payload, build_planner_friendly_deterministic_reply, dataset_inventory, generate_input_dq_html_report, generate_validation_html_report, list_ollama_models, run_chat_assistant, run_input_data_quality, run_insights, run_knowledge_graph, run_log_reader, run_root_cause, run_root_cause_explained, run_scenario_compare, run_validation, run_vision_query, send_html_email_report, smtp_health_check, stream_llm
from .context_resolution import get_context_resolver, get_context_store
from .langgraph_bom import run_bom_drill
from .text_to_sql_agent import run_sql_query
from .models import BomDrillRequest, ChatRequest, CompareRequest, ContextResetRequest, ContextResolveRequest, InsightsRequest, KnowledgeGraphRequest, RagQueryRequest, RagReindexRequest, RootCauseRequest, SemanticDebugRequest, SqlQueryRequest, ValidationReportEmailRequest, ValidationReportRequest, ValidationRequest, VisionQueryRequest
from .rag import build_rag_index, get_rag_status, query_rag
from .rag_openvino import build_openvino_rag_index, export_embedding_model, export_reranker_model, get_openvino_rag_status, query_openvino_rag
from .semantic_regression import evaluate_semantic_debug


BASE_DIR = Path(__file__).resolve().parents[2]

# Global semaphore — Nollama/OpenVINO are single-GPU serial; track queue depth for status messages
import threading as _threading
_llm_semaphore = _threading.Semaphore(1)
_llm_queue_count = 0
_llm_queue_lock = _threading.Lock()
_last_request_debug_lock = _threading.Lock()
_last_request_debug = {
    "intent": "",
    "analysis_completed": False,
    "llm_invoked": False,
    "llm_model": "",
    "prompt_characters": 0,
    "estimated_tokens": 0,
    "llm_duration_ms": 0,
    "timeout_duration_ms": 0,
    "response_generation_stage": "idle",
    "conversation_history_chars": 0,
    "retrieved_data_chars": 0,
    "evidence_chars": 0,
    "kpi_chars": 0,
    "rule_chars": 0,
    "semantic_retrieval_chars": 0,
    "prompt_template_chars": 0,
    "total_chars": 0,
    "largest_contributor": {"component": "", "chars": 0},
    "response_formatter_metrics": {},
}
_last_response_debug_lock = _threading.Lock()
_last_response_debug = {
    "analysis_completed": False,
    "formatted_response": "",
    "formatted_response_exists": False,
    "response_length": 0,
    "response_exists": False,
    "deterministic_response_available": False,
    "deterministic_response_used": False,
    "llm_skipped": False,
    "reason": "",
    "workflow_duration_ms": 0,
    "llm_duration_ms": 0,
    "total_duration_ms": 0,
    "stream_required": False,
    "api_response_created": False,
    "api_response_sent": False,
    "returned_response_type": "",
    "fallback_triggered": False,
    "fallback_reason": "",
    "fallback_source": "",
}

# Optional security controls (P0 hardening)
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
RATE_LIMIT_WINDOW_SECS = int(os.getenv("RATE_LIMIT_WINDOW_SECS", "60"))
RATE_LIMIT_PER_WINDOW = int(os.getenv("RATE_LIMIT_PER_WINDOW", "120"))
RATE_LIMIT_STRICT_PATHS = {
    "/api/chat",
    "/api/chat/stream",
    "/api/sql-query",
    "/api/rag/reindex",
    "/api/rag/openvino/reindex",
}
RATE_LIMIT_STRICT_PER_WINDOW = int(os.getenv("RATE_LIMIT_STRICT_PER_WINDOW", "30"))
NO_LLM_RESPONSE_MODE = os.getenv("NO_LLM_RESPONSE_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}

_rate_lock = _threading.Lock()
_rate_buckets = defaultdict(lambda: deque())

app = FastAPI(
    title="Intel Foundry Planning AI Assistant",
    version="1.0.0",
    description="Web application wrapper for IFSP validation, scenario comparison, and root-cause workflows.",
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _estimate_tokens(text: str) -> int:
    chars = len(text or "")
    return max(1, (chars + 3) // 4)


def _update_last_request_debug(**kwargs) -> None:
    with _last_request_debug_lock:
        _last_request_debug.update(kwargs)


def _snapshot_last_request_debug() -> dict:
    with _last_request_debug_lock:
        return dict(_last_request_debug)


def _record_last_response(
    formatted_response: str,
    fallback_triggered: bool,
    fallback_reason: str,
    fallback_source: str = "",
    analysis_completed: bool = False,
    api_response_created: bool = False,
    api_response_sent: bool = False,
    deterministic_response_available: bool = False,
    deterministic_response_used: bool = False,
    llm_skipped: bool = False,
    reason: str = "",
    workflow_duration_ms: int = 0,
    llm_duration_ms: int = 0,
    total_duration_ms: int = 0,
    stream_required: bool = False,
    returned_response_type: str = "",
) -> None:
    text = str(formatted_response or "")
    response_exists = bool(text.strip())
    with _last_response_debug_lock:
        _last_response_debug.update(
            {
                "analysis_completed": bool(analysis_completed),
                "formatted_response": text,
                "formatted_response_exists": response_exists,
                "response_length": len(text),
                "response_exists": response_exists,
                "deterministic_response_available": bool(deterministic_response_available),
                "deterministic_response_used": bool(deterministic_response_used),
                "llm_skipped": bool(llm_skipped),
                "reason": str(reason or ""),
                "workflow_duration_ms": int(workflow_duration_ms or 0),
                "llm_duration_ms": int(llm_duration_ms or 0),
                "total_duration_ms": int(total_duration_ms or 0),
                "stream_required": bool(stream_required),
                "api_response_created": bool(api_response_created),
                "api_response_sent": bool(api_response_sent),
                "returned_response_type": str(returned_response_type or ""),
                "fallback_triggered": bool(fallback_triggered),
                "fallback_reason": str(fallback_reason or ""),
                "fallback_source": str(fallback_source or ""),
            }
        )
    print(
        f"[IFSP] FORMATTER_END response_length={len(text)} response_exists={str(response_exists).lower()} "
        f"deterministic_response_available={str(bool(deterministic_response_available)).lower()} "
        f"deterministic_response_used={str(bool(deterministic_response_used)).lower()} "
        f"llm_skipped={str(bool(llm_skipped)).lower()} reason={reason} "
        f"workflow_duration_ms={int(workflow_duration_ms or 0)} llm_duration_ms={int(llm_duration_ms or 0)} total_duration_ms={int(total_duration_ms or 0)} "
        f"fallback_triggered={str(bool(fallback_triggered)).lower()} fallback_reason={fallback_reason} "
        f"fallback_source={fallback_source} stream_required={str(bool(stream_required)).lower()} "
        f"returned_response_type={returned_response_type} "
        f"api_response_created={str(bool(api_response_created)).lower()} api_response_sent={str(bool(api_response_sent)).lower()}",
        flush=True,
    )


def _snapshot_last_response_debug() -> dict:
    with _last_response_debug_lock:
        return dict(_last_response_debug)


def _is_open_endpoint(path: str) -> bool:
    return path in {
        "/",
        "/favicon.ico",
        "/api/health",
        "/api/auth/me",
    } or path.startswith("/static/")


def _client_key(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _rate_limit_check(client: str, path: str) -> tuple[bool, int]:
    now = time.time()
    limit = RATE_LIMIT_STRICT_PER_WINDOW if path in RATE_LIMIT_STRICT_PATHS else RATE_LIMIT_PER_WINDOW
    key = f"{client}:{path if path in RATE_LIMIT_STRICT_PATHS else 'default'}"

    with _rate_lock:
        q = _rate_buckets[key]
        while q and (now - q[0]) > RATE_LIMIT_WINDOW_SECS:
            q.popleft()
        if len(q) >= limit:
            retry_after = int(max(1, RATE_LIMIT_WINDOW_SECS - (now - q[0])))
            return False, retry_after
        q.append(now)
    return True, 0


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path

    if API_AUTH_ENABLED and path.startswith("/api/") and not _is_open_endpoint(path):
        if not API_AUTH_TOKEN:
            return JSONResponse(status_code=500, content={"error": "API auth is enabled but API_AUTH_TOKEN is not configured."})
        provided = (request.headers.get("x-api-key") or "").strip()
        if provided != API_AUTH_TOKEN:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    if RATE_LIMIT_ENABLED and path.startswith("/api/") and not _is_open_endpoint(path):
        client = _client_key(request)
        ok, retry_after = _rate_limit_check(client, path)
        if not ok:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"error": "Rate limit exceeded", "retry_after_seconds": retry_after},
            )

    return await call_next(request)


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


def _resolve_session_id(request: Request, provided: str | None = None) -> str:
    sid = (provided or "").strip()
    if sid:
        return sid
    header_sid = (request.headers.get("x-session-id") or "").strip()
    if header_sid:
        return header_sid
    cookie_sid = (request.cookies.get("ifsp_session_id") or "").strip()
    if cookie_sid:
        return cookie_sid
    client = request.client.host if request.client and request.client.host else "anon"
    return f"session-{client}"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/intelfoundrylogo.png")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(name="index.html", request=request)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ifsp-webapp", "base_dir": str(BASE_DIR)}


@app.get("/api/config")
def runtime_config():
    return {
        "semantic_mode": SEMANTIC_MODE,
        "allowed_semantic_modes": sorted(ALLOWED_SEMANTIC_MODES),
        "semantic_mode_validation": "ok",
        "guidance": "Set SEMANTIC_MODE to exactly one allowed value in .env and restart the service after changes.",
    }


@app.get("/api/auth/me")
def auth_me(request: Request):
    return _extract_auth_profile(request)


@app.get("/api/context/current")
def context_current(request: Request, session_id: str | None = None):
    sid = _resolve_session_id(request, session_id)
    ctx = get_context_store().get_or_create(sid)
    return {
        "session_id": ctx.session_id,
        "current_item": ctx.current_item,
        "current_location": ctx.current_location,
        "current_resource": ctx.current_resource,
        "current_week_id": ctx.current_week_id,
        "current_scenario_id": ctx.current_scenario_id,
        "current_analysis_topic": ctx.current_analysis_topic,
        "last_intent": ctx.last_intent,
        "updated_at": ctx.updated_at.isoformat(),
    }


@app.post("/api/context/reset")
def context_reset(req: ContextResetRequest, request: Request):
    sid = _resolve_session_id(request, req.session_id)
    ctx = get_context_store().reset(sid)
    return {
        "session_id": ctx.session_id,
        "reset": True,
        "updated_at": ctx.updated_at.isoformat(),
    }


@app.post("/api/context/resolve")
def context_resolve(req: ContextResolveRequest, request: Request):
    sid = _resolve_session_id(request, req.session_id)
    ctx = get_context_store().get_or_create(sid)
    resolution = get_context_resolver().resolve(req.query, ctx)
    return {
        "resolved_query": resolution.resolved_query,
        "context_used": resolution.context_used,
        "confidence": resolution.confidence,
        "follow_up_detected": resolution.follow_up_detected,
    }


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


@app.post("/api/semantic/debug")
def semantic_debug(req: SemanticDebugRequest):
    return evaluate_semantic_debug(
        BASE_DIR,
        question=req.question,
        week_id=req.week_id,
        scenario_id=req.scenario_id,
        scope=req.scope.model_dump(),
        history=[m.model_dump() for m in req.history],
    )


@app.get("/api/rag/openvino/status")
def rag_openvino_status():
    return get_openvino_rag_status(BASE_DIR)


@app.post("/api/rag/openvino/export-embedding")
def rag_openvino_export_embedding():
    """Export bge-small-en-v1.5 to OpenVINO IR (run once before first reindex)."""
    return export_embedding_model()


@app.post("/api/rag/openvino/export-reranker")
def rag_openvino_export_reranker():
    """Export bge-reranker-base to OpenVINO IR (optional — improves retrieval quality)."""
    return export_reranker_model()


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
def chat(req: ChatRequest, request: Request):
    session_id = _resolve_session_id(request, req.session_id)
    effective_llm_enabled = bool(req.llm_enabled) and not NO_LLM_RESPONSE_MODE
    response = run_chat_assistant(
        BASE_DIR,
        req.question,
        session_id,
        req.week_id,
        req.scenario_id,
        req.scope.model_dump(),
        effective_llm_enabled,
        req.llm_model,
        [m.model_dump() for m in req.history],
        req.show_detailed_analysis,
    )
    print("[IFSP] FORMATTER_START", flush=True)
    if isinstance(response, dict):
        assistant_text = str(response.get("Assistant Reply") or "")
        formatted_response_exists = bool(assistant_text.strip())
        fallback_reason = ""
        fallback_triggered = False
        fallback_source = ""
        returned_response_type = ""
        if response.get("Mode") == "NO_LLM_RESPONSE_MODE" and formatted_response_exists:
            fallback_triggered = False
            fallback_reason = ""
            fallback_source = ""
            returned_response_type = "deterministic"
        elif response.get("Mode") == "NO_LLM_RESPONSE_MODE" and not formatted_response_exists:
            fallback_triggered = True
            fallback_reason = "EMPTY_DETERMINISTIC_RESPONSE"
            fallback_source = "chat_sync_mode_guard"
            returned_response_type = "deterministic_error"
        elif "timed out" in assistant_text.lower():
            fallback_triggered = True
            fallback_reason = "LLM_TIMEOUT_FALLBACK_TEXT"
            fallback_source = "chat_sync_assistant_reply"
            returned_response_type = "timeout_fallback"
        elif not assistant_text.strip():
            fallback_triggered = True
            fallback_reason = "EMPTY_FORMATTED_RESPONSE"
            fallback_source = "chat_sync_empty_reply"
            returned_response_type = "deterministic_error"
        else:
            returned_response_type = "standard"
        if fallback_triggered:
            print(
                f"[IFSP] FALLBACK_TRIGGERED reason={fallback_reason} source={fallback_source}",
                flush=True,
            )
        print("[IFSP] API_RESPONSE_CREATED", flush=True)
        _record_last_response(
            assistant_text,
            fallback_triggered,
            fallback_reason,
            fallback_source=fallback_source,
            analysis_completed=True,
            api_response_created=True,
            api_response_sent=False,
            returned_response_type=returned_response_type,
        )
    else:
        print("[IFSP] FALLBACK_TRIGGERED reason=INVALID_RESPONSE_OBJECT source=chat_sync_response_type", flush=True)
        print("[IFSP] API_RESPONSE_CREATED", flush=True)
        _record_last_response(
            "",
            True,
            "INVALID_RESPONSE_OBJECT",
            fallback_source="chat_sync_response_type",
            analysis_completed=True,
            api_response_created=True,
            api_response_sent=False,
            returned_response_type="deterministic_error",
        )

    breakdown = response.get("Prompt Breakdown") if isinstance(response.get("Prompt Breakdown"), dict) else {}
    formatter_metrics = response.get("Response Formatter Metrics") if isinstance(response.get("Response Formatter Metrics"), dict) else {}
    _update_last_request_debug(
        intent=str(response.get("Workflow") or ""),
        analysis_completed=True,
        llm_invoked=bool(response.get("LLM Invoked")),
        llm_model=str(response.get("LLM Model") or (req.llm_model or LLM_CONFIG.get("model") or "")),
        prompt_characters=int(response.get("Prompt Characters") or 0),
        estimated_tokens=int(response.get("Estimated Tokens") or 0),
        llm_duration_ms=int(response.get("LLM Duration MS") or 0),
        timeout_duration_ms=int(response.get("Timeout Duration MS") or 0),
        response_generation_stage="FINAL_RESPONSE_END",
        conversation_history_chars=int(breakdown.get("conversation_history_chars") or 0),
        retrieved_data_chars=int(breakdown.get("retrieved_data_chars") or 0),
        evidence_chars=int(breakdown.get("evidence_chars") or 0),
        kpi_chars=int(breakdown.get("kpi_chars") or 0),
        rule_chars=int(breakdown.get("rule_chars") or 0),
        semantic_retrieval_chars=int(breakdown.get("semantic_retrieval_chars") or 0),
        prompt_template_chars=int(breakdown.get("prompt_template_chars") or 0),
        total_chars=int(breakdown.get("total_chars") or int(response.get("Prompt Characters") or 0)),
        largest_contributor=breakdown.get("largest_contributor") or {"component": "", "chars": 0},
        response_formatter_metrics=formatter_metrics,
    )
    print("[IFSP] API_RESPONSE_SENT", flush=True)
    _record_last_response(
        str(response.get("Assistant Reply") if isinstance(response, dict) else ""),
        bool(_snapshot_last_response_debug().get("fallback_triggered")),
        str(_snapshot_last_response_debug().get("fallback_reason") or ""),
        fallback_source=str(_snapshot_last_response_debug().get("fallback_source") or ""),
        analysis_completed=True,
        api_response_created=True,
        api_response_sent=True,
        returned_response_type=str(_snapshot_last_response_debug().get("returned_response_type") or ""),
    )
    return response


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, request: Request):
    """
    Streaming chat endpoint — returns SSE (text/event-stream).
    Sends ': keepalive' pings every 5 s while the LLM is thinking so the
    browser never drops the connection on slow models (e.g. 30 s TTFT).
    Each data event: data: <json-encoded token chunk>\n\n
    Terminal event:  data: [DONE]\n\n
    """
    import queue as _queue
    import threading as _threading

    # system_prompt is overridden by build_grounded_chat_prompt; this is a fallback only
    system_prompt = (
        "You are a senior Intel Foundry Supply Planning expert. "
        "Answer directly using the data provided. Lead with the actual numbers."
    )
    tok_queue: _queue.Queue = _queue.Queue()
    session_id = _resolve_session_id(request, req.session_id)

    def _is_root_cause(meta: dict) -> bool:
        wf = str((meta or {}).get("workflow") or "").strip().lower()
        return "root cause" in wf or wf == "root_cause"

    def _normalized_intent(meta: dict) -> str:
        payload = (meta or {}).get("workflow_payload") if isinstance(meta, dict) else None
        router_meta = payload.get("router_metadata") if isinstance(payload, dict) else None
        if isinstance(router_meta, dict):
            return str(router_meta.get("normalized_intent") or router_meta.get("intent") or "").strip().lower()
        return ""

    def _deterministic_first_eligible(meta: dict) -> bool:
        intent = _normalized_intent(meta)
        workflow = str((meta or {}).get("workflow") or "").strip().lower()
        llm_only_intents = {
            "recommendation_request",
            "recommendationrequest",
            "executive_summary",
            "executivesummary",
            "explain_plan",
            "explainplan",
            "narrative_generation",
            "narrativegeneration",
        }
        if intent in llm_only_intents:
            return False
        if any(token in workflow for token in ["recommendation", "executive summary", "narrative", "explain plan"]):
            return False
        return True

    def _fallback_from_meta(meta: dict, llm_attempted: bool, show_detailed_analysis: bool = False) -> str:
        clarification = meta.get("clarification")
        if clarification:
            q = clarification.get("question") or "Please provide missing details so I can continue."
            ex = clarification.get("examples") or []
            if ex:
                return f"{q} Example: {ex[0]}"
            return q

        workflow_result = meta.get("workflow_result")
        workflow = meta.get("workflow") or "analysis"
        planner_reply = build_planner_friendly_deterministic_reply(
            meta.get("workflow"),
            workflow_result if isinstance(workflow_result, dict) else None,
            meta.get("retrieval_plan") if isinstance(meta.get("retrieval_plan"), dict) else None,
            show_detailed_analysis=show_detailed_analysis,
        )
        if planner_reply:
            return planner_reply
        if isinstance(workflow_result, dict):
            stats = workflow_result.get("Demand vs Supply Stats") if isinstance(workflow_result.get("Demand vs Supply Stats"), dict) else {}
            item = workflow_result.get("Item") or stats.get("item")
            demand = stats.get("demand_qty_total")
            scheduled = stats.get("scheduled_qty_total")
            unmet = stats.get("unmet_qty")
            status = stats.get("meet_status")
            if item is not None and any(v is not None for v in [demand, scheduled, unmet, status]):
                return (
                    f"Item {item}: demand={demand}, scheduled supply={scheduled}, unmet={unmet}, "
                    f"status={status}."
                )
        if isinstance(workflow_result, dict) and workflow_result:
            if llm_attempted:
                return (
                    f"I completed grounded {workflow} analysis, but the model response timed out. "
                    "I can still explain the result in plain language if you ask a specific follow-up question."
                )
            return f"I completed grounded {workflow} analysis and returned deterministic results without LLM generation."

        return "I do not have enough data to answer."

    def _producer():
        import time as _time
        global _llm_queue_count
        producer_started_at = _time.perf_counter()
        generated_text = ""
        meta = None
        llm_invoked = False
        prompt_characters = 0
        estimated_tokens = 0
        llm_duration_ms = 0
        timeout_ms = int(STREAM_LLM_HTTP_TIMEOUT_SECS * 1000)
        prompt_breakdown = {}
        formatter_metrics = {}
        fallback_triggered = False
        fallback_reason = ""
        fallback_source = ""
        returned_response_type = ""
        deterministic_response_available = False
        deterministic_response_used = False
        llm_skipped = False
        skip_reason = ""
        stream_required = False
        api_response_created = False
        api_response_sent = False
        workflow_duration_ms = 0
        try:
            tok_queue.put(("status", "Analysing your question and querying planning data…"))
            _t0 = _time.perf_counter()
            sp, grounded_prompt, meta = build_grounded_chat_prompt(
                BASE_DIR,
                req.question,
                req.week_id,
                req.scenario_id,
                req.scope.model_dump(),
                session_id=session_id,
                history=[m.model_dump() for m in req.history],
            )
            _grounding_ms = int((_time.perf_counter() - _t0) * 1000)
            print(f"[IFSP] grounding={_grounding_ms}ms q={req.question[:60]!r}", flush=True)
            workflow_name = str((meta or {}).get("workflow") or "")
            prompt_breakdown = meta.get("prompt_breakdown") if isinstance(meta.get("prompt_breakdown"), dict) else {}
            formatter_metrics = meta.get("response_formatter_metrics") if isinstance(meta.get("response_formatter_metrics"), dict) else {}
            timing_metrics = meta.get("timing_metrics") if isinstance(meta.get("timing_metrics"), dict) else {}
            workflow_duration_ms = int(timing_metrics.get("workflow_duration_ms") or 0)
            prompt_characters = int(prompt_breakdown.get("total_chars") or len(sp or "") + len(grounded_prompt or ""))
            estimated_tokens = _estimate_tokens((sp or "") + (grounded_prompt or ""))
            print(f"[IFSP] ANALYSIS_COMPLETE workflow={workflow_name}", flush=True)
            print(
                f"[IFSP] FINAL_RESPONSE_START prompt_characters={prompt_characters} estimated_tokens={estimated_tokens}",
                flush=True,
            )
            if prompt_breakdown:
                print(
                    "[IFSP] PROMPT_BREAKDOWN "
                    f"conversation_history_chars={int(prompt_breakdown.get('conversation_history_chars') or 0)} "
                    f"retrieved_data_chars={int(prompt_breakdown.get('retrieved_data_chars') or 0)} "
                    f"evidence_chars={int(prompt_breakdown.get('evidence_chars') or 0)} "
                    f"kpi_chars={int(prompt_breakdown.get('kpi_chars') or 0)} "
                    f"rule_chars={int(prompt_breakdown.get('rule_chars') or 0)} "
                    f"semantic_retrieval_chars={int(prompt_breakdown.get('semantic_retrieval_chars') or 0)} "
                    f"prompt_template_chars={int(prompt_breakdown.get('prompt_template_chars') or 0)}",
                    flush=True,
                )
            _update_last_request_debug(
                intent=workflow_name,
                analysis_completed=True,
                llm_invoked=False,
                llm_model=str(req.llm_model or LLM_CONFIG.get("model") or ""),
                prompt_characters=prompt_characters,
                estimated_tokens=estimated_tokens,
                llm_duration_ms=0,
                timeout_duration_ms=timeout_ms,
                response_generation_stage="FINAL_RESPONSE_START",
                conversation_history_chars=int(prompt_breakdown.get("conversation_history_chars") or 0),
                retrieved_data_chars=int(prompt_breakdown.get("retrieved_data_chars") or 0),
                evidence_chars=int(prompt_breakdown.get("evidence_chars") or 0),
                kpi_chars=int(prompt_breakdown.get("kpi_chars") or 0),
                rule_chars=int(prompt_breakdown.get("rule_chars") or 0),
                semantic_retrieval_chars=int(prompt_breakdown.get("semantic_retrieval_chars") or 0),
                prompt_template_chars=int(prompt_breakdown.get("prompt_template_chars") or 0),
                total_chars=int(prompt_breakdown.get("total_chars") or prompt_characters),
                largest_contributor=prompt_breakdown.get("largest_contributor") or {"component": "", "chars": 0},
                response_formatter_metrics=formatter_metrics,
            )
            should_invoke_llm = bool(req.llm_enabled) and not NO_LLM_RESPONSE_MODE
            stream_required = bool(should_invoke_llm)
            deterministic_candidate = _fallback_from_meta(meta, llm_attempted=False, show_detailed_analysis=bool(req.show_detailed_analysis))
            deterministic_response_available = bool(
                (deterministic_candidate or "").strip()
                and str(deterministic_candidate).strip().lower() != "i do not have enough data to answer."
                and isinstance((meta or {}).get("workflow_result"), dict)
                and bool((meta or {}).get("workflow_result"))
            )
            if _is_root_cause(meta):
                print("[IFSP] RootCauseAnalysis Started", flush=True)
                print(f"[IFSP] NO_LLM_RESPONSE_MODE = {str(NO_LLM_RESPONSE_MODE).lower()}", flush=True)
                root_result = meta.get("workflow_result") if isinstance(meta.get("workflow_result"), dict) else {}
                print(
                    f"[IFSP] ROOT_CAUSE_RESULT exists={str(bool(root_result)).lower()} chars={len(json.dumps(root_result, ensure_ascii=True)) if root_result else 0}",
                    flush=True,
                )
            print("[IFSP] FORMATTER_START", flush=True)
            if should_invoke_llm and _deterministic_first_eligible(meta) and deterministic_response_available:
                tok_queue.put(("status", "Returning deterministic grounded response (deterministic-first)."))
                generated_text = deterministic_candidate
                tok_queue.put(("token", generated_text))
                api_response_created = True
                stream_required = False
                deterministic_response_used = True
                llm_skipped = True
                skip_reason = "deterministic-first"
                fallback_triggered = False
                fallback_reason = ""
                fallback_source = ""
                returned_response_type = "deterministic"
                print("[IFSP] API_RESPONSE_CREATED", flush=True)
                print("[IFSP] FINAL_RESPONSE_END", flush=True)
                _update_last_request_debug(
                    llm_invoked=False,
                    llm_duration_ms=0,
                    response_generation_stage="FINAL_RESPONSE_END",
                )
                return

            if not should_invoke_llm:
                tok_queue.put(("status", "LLM generation is disabled; returning deterministic grounded response."))
                generated_text = _fallback_from_meta(meta, llm_attempted=False, show_detailed_analysis=bool(req.show_detailed_analysis))
                response_exists = bool((generated_text or "").strip())
                response_length = len(str(generated_text or ""))
                tok_queue.put(("token", generated_text))
                api_response_created = True
                print("[IFSP] API_RESPONSE_CREATED", flush=True)
                if response_exists and response_length > 0:
                    fallback_triggered = False
                    fallback_reason = ""
                    fallback_source = ""
                    returned_response_type = "deterministic"
                    deterministic_response_used = True
                    llm_skipped = True
                    skip_reason = "NO_LLM_RESPONSE_MODE"
                    stream_required = False
                else:
                    fallback_triggered = True
                    fallback_reason = "EMPTY_DETERMINISTIC_RESPONSE"
                    fallback_source = "stream_mode_guard"
                    returned_response_type = "deterministic_error"
                    print(f"[IFSP] FALLBACK_TRIGGERED reason={fallback_reason} source={fallback_source}", flush=True)
                if _is_root_cause(meta):
                    print("[IFSP] LLM Invoked = false", flush=True)
                    print("[IFSP] RootCauseAnalysis Completed", flush=True)
                print("[IFSP] FINAL_RESPONSE_END", flush=True)
                _update_last_request_debug(
                    llm_invoked=False,
                    llm_duration_ms=0,
                    response_generation_stage="FINAL_RESPONSE_END",
                )
                return

            # Show queue position if LLM is busy with another request
            with _llm_queue_lock:
                _llm_queue_count += 1
                position = _llm_queue_count
            if position > 1:
                tok_queue.put(("status", f"Waiting for GPU — {position - 1} request(s) ahead…"))
            _llm_semaphore.acquire()
            _t1 = _time.perf_counter()
            llm_invoked = True
            model_name = (req.llm_model or LLM_CONFIG.get("model") or "").strip()
            print(
                f"[IFSP] LLM_START model={model_name} timeout_ms={timeout_ms} ttft_timeout_ms={int(STREAM_LLM_TTFT_TIMEOUT_SECS * 1000)}",
                flush=True,
            )
            _update_last_request_debug(
                llm_invoked=True,
                llm_model=model_name,
                response_generation_stage="LLM_START",
            )
            try:
                tok_queue.put(("status", "Generating answer…"))
                first_token = True
                for chunk in stream_llm(grounded_prompt, sp, model_name=req.llm_model):
                    if first_token:
                        print(f"[IFSP] ttft={int((_time.perf_counter()-_t1)*1000)}ms", flush=True)
                        first_token = False
                    generated_text += chunk
                    tok_queue.put(("token", chunk))
                    if not api_response_created:
                        api_response_created = True
                        print("[IFSP] API_RESPONSE_CREATED", flush=True)
                if first_token:
                    # No token was emitted (timeout/provider issue). Return deterministic grounded fallback.
                    tok_queue.put(("status", "LLM response timed out; returning grounded fallback."))
                    fallback_text = _fallback_from_meta(meta, llm_attempted=True, show_detailed_analysis=bool(req.show_detailed_analysis))
                    generated_text += fallback_text
                    tok_queue.put(("token", fallback_text))
                    api_response_created = True
                    print("[IFSP] API_RESPONSE_CREATED", flush=True)
                    fallback_triggered = True
                    fallback_reason = "LLM_TIMEOUT_NO_VISIBLE_TOKEN"
                    fallback_source = "_fallback_from_meta(llm_attempted=true)"
                    returned_response_type = "timeout_fallback"
                    print(f"[IFSP] FALLBACK_TRIGGERED reason={fallback_reason} source={fallback_source}", flush=True)
                llm_duration_ms = int((_time.perf_counter() - _t1) * 1000)
                print(f"[IFSP] llm_total={llm_duration_ms}ms", flush=True)
                print(f"[IFSP] LLM_END duration_ms={llm_duration_ms}", flush=True)
                _update_last_request_debug(
                    llm_duration_ms=llm_duration_ms,
                    response_generation_stage="LLM_END",
                )
            finally:
                _llm_semaphore.release()
                with _llm_queue_lock:
                    _llm_queue_count -= 1
                if _is_root_cause(meta):
                    print(f"[IFSP] LLM Invoked = {str(llm_invoked).lower()}", flush=True)
                    print("[IFSP] RootCauseAnalysis Completed", flush=True)
                print("[IFSP] FINAL_RESPONSE_END", flush=True)
                _update_last_request_debug(
                    response_generation_stage="FINAL_RESPONSE_END",
                )
        except Exception as exc:
            tok_queue.put(("error", str(exc)))
            fallback_triggered = True
            fallback_reason = f"STREAM_EXCEPTION:{type(exc).__name__}"
            fallback_source = "chat_stream_producer_exception"
            returned_response_type = "deterministic_error"
            print(f"[IFSP] FALLBACK_TRIGGERED reason={fallback_reason} source={fallback_source}", flush=True)
            _update_last_request_debug(response_generation_stage="ERROR")
        finally:
            if not generated_text:
                fallback_triggered = True
                if not fallback_reason:
                    fallback_reason = "EMPTY_FORMATTED_RESPONSE"
                    fallback_source = "stream_empty_generated_text"
                    returned_response_type = "deterministic_error"
                    print(f"[IFSP] FALLBACK_TRIGGERED reason={fallback_reason} source={fallback_source}", flush=True)
            if not returned_response_type:
                returned_response_type = "standard"
            _record_last_response(
                generated_text,
                fallback_triggered,
                fallback_reason,
                fallback_source=fallback_source,
                analysis_completed=True,
                api_response_created=api_response_created,
                api_response_sent=api_response_sent,
                deterministic_response_available=deterministic_response_available,
                deterministic_response_used=deterministic_response_used,
                llm_skipped=llm_skipped,
                reason=skip_reason,
                workflow_duration_ms=workflow_duration_ms,
                llm_duration_ms=llm_duration_ms,
                total_duration_ms=int((_time.perf_counter() - producer_started_at) * 1000),
                stream_required=stream_required,
                returned_response_type=returned_response_type,
            )
            if isinstance(meta, dict):
                _update_chat_session_context(
                    session_id,
                    req.question,
                    generated_text,
                    meta.get("workflow") or "Conversational Copilot",
                    meta.get("workflow_payload") if isinstance(meta.get("workflow_payload"), dict) else {},
                    meta.get("workflow_result") if isinstance(meta.get("workflow_result"), dict) else None,
                    meta.get("retrieval_plan") if isinstance(meta.get("retrieval_plan"), dict) else None,
                    req.scope.model_dump(),
                    meta.get("context_resolution") if isinstance(meta.get("context_resolution"), dict) else None,
                )
            tok_queue.put(("done", None))

    _threading.Thread(target=_producer, daemon=True).start()

    def _event_stream():
        while True:
            try:
                kind, val = tok_queue.get(timeout=5)
            except _queue.Empty:
                yield ": keepalive\n\n"   # SSE comment keeps browser connection alive
                continue
            if kind == "done":
                print("[IFSP] API_RESPONSE_SENT", flush=True)
                _record_last_response(
                    _snapshot_last_response_debug().get("formatted_response") or "",
                    bool(_snapshot_last_response_debug().get("fallback_triggered")),
                    str(_snapshot_last_response_debug().get("fallback_reason") or ""),
                    fallback_source=str(_snapshot_last_response_debug().get("fallback_source") or ""),
                    analysis_completed=True,
                    api_response_created=bool(_snapshot_last_response_debug().get("api_response_created")),
                    api_response_sent=True,
                    deterministic_response_available=bool(_snapshot_last_response_debug().get("deterministic_response_available")),
                    deterministic_response_used=bool(_snapshot_last_response_debug().get("deterministic_response_used")),
                    llm_skipped=bool(_snapshot_last_response_debug().get("llm_skipped")),
                    reason=str(_snapshot_last_response_debug().get("reason") or ""),
                    workflow_duration_ms=int(_snapshot_last_response_debug().get("workflow_duration_ms") or 0),
                    llm_duration_ms=int(_snapshot_last_response_debug().get("llm_duration_ms") or 0),
                    total_duration_ms=int(_snapshot_last_response_debug().get("total_duration_ms") or 0),
                    stream_required=bool(_snapshot_last_response_debug().get("stream_required")),
                    returned_response_type=str(_snapshot_last_response_debug().get("returned_response_type") or ""),
                )
                yield "data: [DONE]\n\n"
                return
            if kind == "status":
                # Pad to ensure uvicorn flushes immediately (small events get buffered)
                msg = json.dumps({"__status__": val})
                yield f"data: {msg}\n\n"
                continue
            if kind == "error":
                print("[IFSP] API_RESPONSE_SENT", flush=True)
                _record_last_response(
                    _snapshot_last_response_debug().get("formatted_response") or "",
                    True,
                    "STREAM_ERROR_EVENT",
                    fallback_source="chat_stream_error_event",
                    analysis_completed=True,
                    api_response_created=bool(_snapshot_last_response_debug().get("api_response_created")),
                    api_response_sent=True,
                    deterministic_response_available=bool(_snapshot_last_response_debug().get("deterministic_response_available")),
                    deterministic_response_used=bool(_snapshot_last_response_debug().get("deterministic_response_used")),
                    llm_skipped=bool(_snapshot_last_response_debug().get("llm_skipped")),
                    reason=str(_snapshot_last_response_debug().get("reason") or ""),
                    workflow_duration_ms=int(_snapshot_last_response_debug().get("workflow_duration_ms") or 0),
                    llm_duration_ms=int(_snapshot_last_response_debug().get("llm_duration_ms") or 0),
                    total_duration_ms=int(_snapshot_last_response_debug().get("total_duration_ms") or 0),
                    stream_required=bool(_snapshot_last_response_debug().get("stream_required")),
                    returned_response_type=str(_snapshot_last_response_debug().get("returned_response_type") or "deterministic_error"),
                )
                yield f"data: {json.dumps({'error': val})}\n\n"
                yield "data: [DONE]\n\n"
                return
            if kind == "token":
                print("[IFSP] API_RESPONSE_CREATED", flush=True)
            yield f"data: {json.dumps(val)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx/proxy buffering
            "Connection": "keep-alive",
        },
    )


@app.get("/api/debug/last-request")
def debug_last_request():
    return _snapshot_last_request_debug()


@app.get("/api/debug/last-response")
def debug_last_response():
    return _snapshot_last_response_debug()
