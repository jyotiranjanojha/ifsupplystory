# Production Readiness Checklist

## Scope

Deployment target:
- Intel Ultra 7 AI Boost PC
- OpenVINO GenAI
- Qwen2.5-Coder-7B-Instruct
- Local-first architecture

## 1. Security and Access Control

- [ ] Enforce authentication on all API endpoints except health.
- [ ] Implement role-based authorization for admin endpoints (`/api/rag/reindex`, export endpoints, report email).
- [ ] Add rate limits per user and per endpoint class.
- [ ] Add request body size limits and prompt size limits.
- [ ] Enforce HTTPS in deployment and trusted reverse proxy headers.
- [ ] Move all secrets to secure store (not plain env files in shared environments).
- [ ] Add secret rotation procedure and last-rotation audit field.
- [ ] Redact PII/sensitive tokens from logs.

## 2. Snowflake Hardening and Optimization

- [ ] Restrict to approved database/schema/view allowlist.
- [ ] Add query tags: intent, workflow, user, trace_id.
- [ ] Enforce `LIMIT` and denylist for non-SELECT operations.
- [ ] Configure warehouse auto-suspend and auto-resume for cost control.
- [ ] Create performance views/materialized views for common explainability joins.
- [ ] Add timeout and retry policy for Snowflake connectivity.
- [ ] Add SQL cost telemetry (duration, bytes scanned, cache hit).

## 3. OpenVINO Runtime Optimization

- [ ] Benchmark model on CPU/NPU/GPU and choose default device by SLA.
- [ ] Warm up LLM and embedding models during service startup.
- [ ] Define per-route token caps and stop sequences.
- [ ] Configure fallback path for device unavailability.
- [ ] Capture TTFT and total generation latency metrics.
- [ ] Verify memory footprint under worst-case concurrent workload.

## 4. LangGraph Reliability

- [ ] Add trace_id propagation through every graph state.
- [ ] Define schema contracts for graph output payloads.
- [ ] Add retry/error counters and circuit breaker thresholds.
- [ ] Add deterministic fallback behavior for each workflow.
- [ ] Add graph-level smoke tests for all critical routes.

## 5. Resource and Memory Controls

- [ ] Enforce bounded cache sizes and TTLs.
- [ ] Enforce max rows/docs/chunks/top_k across all retrieval paths.
- [ ] Add memory high-watermark alerts and eviction logs.
- [ ] Move heavy reindex tasks to background worker model.
- [ ] Add streaming/pagination for large responses.

## 6. Prompt and Hallucination Controls

- [ ] Standardize prompts by route type: SQL-only, RAG-only, SQL+RAG.
- [ ] Require citations for policy/process claims.
- [ ] Add mandatory "confirmed vs hypothesis" answer sections.
- [ ] Add confidence labels and missing-evidence reporting.
- [ ] Add post-response consistency validator for claim vs evidence.

## 7. Observability and Operations

- [ ] Add structured logs with correlation IDs.
- [ ] Add metrics: request rate, latency p50/p95/p99, queue depth, errors.
- [ ] Add health probes for LLM, vector store, Snowflake backend.
- [ ] Add daily operational report for failures and retries.
- [ ] Add dashboard for top intents and route distribution.

## 8. Testing and Release Gates

- [ ] Unit tests pass (router, KPI, RAG, SQL agents).
- [ ] Integration tests pass with representative BY ESP snapshots.
- [ ] Load test with target concurrency and realistic prompt sizes.
- [ ] Security scan and dependency audit pass.
- [ ] Rollback plan tested.

## 9. Data Governance

- [ ] Define data retention policy for chat history and RAG chunks.
- [ ] Define legal/compliance boundaries for document ingestion.
- [ ] Validate PII handling and redaction policy.
- [ ] Version and audit source document sets for RAG.

## Go/No-Go Criteria

Go-live minimum:
- All P0 controls from `ARCHITECTURE_REVIEW.md` implemented.
- Security, rate limit, and tracing controls enabled.
- OpenVINO benchmark profile documented and selected.
- Citation enforcement active for RAG and hybrid routes.
