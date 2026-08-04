# Risk Register

## Risk Scoring

- Probability: Low / Medium / High
- Impact: Low / Medium / High / Critical

## Risks

| ID | Risk | Probability | Impact | Detection Signal | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-01 | Unauthorized API usage due to weak auth enforcement | Medium | Critical | Unknown users hitting expensive endpoints | Enforce authN/authZ and endpoint ACLs | Platform |
| R-02 | Prompt injection causes policy drift in answer synthesis | Medium | High | Response deviates from grounded evidence | Strict system prompts + citation gating + output validators | AI Platform |
| R-03 | SQL generation produces invalid queries repeatedly | Medium | Medium | Retry loops spike, execution errors increase | Template-first SQL for top intents; schema validation | Data Engineering |
| R-04 | Snowflake cost overrun from unconstrained queries | Medium | High | Bytes scanned and warehouse runtime spikes | Query tagging, approved views, hard row/timeout limits | Data Platform |
| R-05 | OpenVINO inference latency unacceptable at peak | Medium | High | TTFT and p95 latency exceed SLA | Warmup, token caps, device fallback strategy | AI Platform |
| R-06 | Single-process semaphore bottlenecks throughput | High | Medium | Queue depth consistently > 2 | Split API and inference workers; queue-based dispatch | Platform |
| R-07 | Memory growth due to unbounded caches | Medium | High | RSS increases steadily over uptime | LRU+TTL bounds, memory guardrails, cache telemetry | Platform |
| R-08 | RAG index staleness leads to outdated policy answers | Medium | Medium | Answers cite old timestamped docs | Versioned document sets + reindex schedules + freshness checks | Knowledge Ops |
| R-09 | Hallucinated claims in hybrid answers | Medium | High | Claims without supporting rows/citations | Enforce "no citation no claim" and confidence tiers | AI Platform |
| R-10 | Endpoint abuse triggers local machine instability | Medium | High | CPU/GPU pegged, process restarts | Rate limiting, max request budget, circuit breakers | Platform |
| R-11 | Snowflake connectivity issues disrupt explainability | Medium | Medium | Backend timeout spikes | Graceful fallback to local snapshots and retry policy | Data Platform |
| R-12 | Dependency vulnerabilities in Python stack | Medium | High | Security scan findings | SBOM + patch cadence + lockfile discipline | DevSecOps |
| R-13 | Missing runbook causes slow incident response | Medium | Medium | MTTR exceeds target | On-call runbook and failure playbooks | Operations |
| R-14 | Model drift from ad-hoc parameter changes | Low | Medium | Output inconsistency across builds | Config baselines and change control | AI Platform |
| R-15 | Sensitive data exposure in logs | Low | Critical | Tokens/credentials/PII observed in logs | Redaction middleware + log scanning | Security |

## Top 5 Immediate Risks

1. R-01 Unauthorized API access
2. R-04 Snowflake cost overrun
3. R-05 OpenVINO latency instability
4. R-07 Memory growth and process pressure
5. R-09 Hallucination without evidence gating

## Immediate Mitigation Sprint (2 weeks)

1. Enforce endpoint authentication and role checks.
2. Add rate limits and request budget controls.
3. Implement citation enforcement for hybrid responses.
4. Add bounded cache controls and memory telemetry.
5. Add Snowflake query tagging and hard SQL guardrails.
