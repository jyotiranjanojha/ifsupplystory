# Operations Runbook

## Environment

Target:
- Intel Ultra 7 AI Boost PC
- Windows local-first deployment
- OpenVINO GenAI and FAISS local index

## Startup Procedure

1. Activate Python environment.
2. Verify model paths and embedding paths in environment variables.
3. Start service via `python webapp/run.py --reload` (dev) or production launcher.
4. Verify health endpoint `/api/health`.
5. Verify model discovery endpoint `/api/llm/models`.
6. Verify RAG readiness `/api/rag/status` and `/api/rag/openvino/status`.

## Daily Health Checks

1. API health returns status ok.
2. LLM queue depth remains within threshold.
3. p95 latency within SLA targets:
   - SQL-only <= 3s
   - RAG-only <= 4s
   - SQL+RAG <= 7s
4. Error rate < 2%.
5. Memory watermark below configured threshold.

## Weekly Maintenance

1. Reindex policy/SOP documents as needed.
2. Validate citation freshness (document timestamps).
3. Run regression tests.
4. Review risk register and unresolved incidents.

## Incident Playbooks

### Playbook A: LLM latency spike

Symptoms:
- High TTFT
- Growing queue depth

Actions:
1. Reduce max token settings for heavy routes.
2. Temporarily disable non-critical generation routes.
3. Restart model worker after draining active requests.
4. Verify device fallback (NPU/GPU/CPU) behavior.

### Playbook B: Snowflake timeout / outage

Symptoms:
- SQL backend exceptions

Actions:
1. Switch to local CSV snapshot mode where possible.
2. Enable reduced query templates for critical asks.
3. Notify data platform owner.
4. Resume Snowflake backend after health checks pass.

### Playbook C: RAG retrieval quality drop

Symptoms:
- Low relevance hits
- Missing citations

Actions:
1. Verify index freshness and metadata completeness.
2. Re-run ingest pipeline with chunk config 800/150.
3. Validate embedding model path and OpenVINO load.
4. Rebuild FAISS index and run retrieval smoke tests.

### Playbook D: Memory pressure

Symptoms:
- Process RSS growth
- OOM or degraded response times

Actions:
1. Clear/rotate large caches.
2. Reduce top_k, max rows, and response payload size.
3. Restart process during maintenance window.
4. Enable stricter cache bounds and monitor.

## Recovery Verification

After any incident:
1. Run health endpoints.
2. Run route smoke checks for SQL-only, RAG-only, SQL+RAG.
3. Validate one deterministic KPI response.
4. Validate one policy response with citation.
5. Confirm error rate and latency normalize.

## Escalation Matrix

1. Platform owner: API/runtime failures.
2. AI platform owner: model and prompt pipeline failures.
3. Data platform owner: Snowflake/data access failures.
4. Security owner: auth/secrets/logging incidents.
