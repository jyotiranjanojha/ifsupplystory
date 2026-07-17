"""
Chat assistant end-to-end tests.
Runs against the live server at http://127.0.0.1:8010/api/chat
"""
import json
import sys
import time
from urllib import request, error

BASE = "http://127.0.0.1:8010"
HISTORY = []   # simulates a real conversation — grows across multi-turn tests


def chat(question, extra=None, use_history=False):
    payload = {
        "question": question,
        "llm_enabled": True,
        "history": list(HISTORY) if use_history else [],
        "scope": {},
    }
    if extra:
        payload.update(extra)
    data = json.dumps(payload).encode()
    req = request.Request(
        f"{BASE}/api/chat", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    with request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())
    elapsed = round(time.time() - t0, 1)
    # Append to simulated history
    HISTORY.append({"role": "user", "content": question})
    HISTORY.append({"role": "assistant", "content": body.get("Assistant Reply", "")})
    return body, elapsed


def check(label, body, expect_workflow=None, expect_keys=None, expect_reply_contains=None):
    workflow   = body.get("Workflow", "")
    router     = body.get("Router Metadata") or {}
    intent     = router.get("intent", "–")
    confidence = router.get("confidence", "–")
    llm_used   = router.get("llm_fallback_used", False)
    reply      = body.get("Assistant Reply", "")[:120].replace("\n", " ")

    status = "PASS"
    notes  = []

    if expect_workflow and expect_workflow.lower() not in workflow.lower():
        status = "FAIL"
        notes.append(f"workflow={workflow!r} (expected {expect_workflow!r})")

    if expect_keys:
        for k in expect_keys:
            if k not in body:
                status = "FAIL"
                notes.append(f"missing key {k!r}")

    if expect_reply_contains:
        if not any(s.lower() in reply.lower() for s in expect_reply_contains):
            status = "WARN"
            notes.append(f"reply does not mention {expect_reply_contains}")

    note_str = f"  !! {'; '.join(notes)}" if notes else ""
    print(f"  {status:4}  intent={intent:<22} conf={confidence:<5} llm_fb={str(llm_used):<5}  [{workflow}]{note_str}")
    print(f"        reply: {reply!r}")
    return status


print("=" * 72)
print("IFSP Chat Assistant — End-to-End Test Suite")
print("=" * 72)
results = []

# ── 1. Health check ──────────────────────────────────────────────────────────
print("\n[1] Health check")
req = request.Request(f"{BASE}/api/health")
with request.urlopen(req, timeout=10) as r:
    h = json.loads(r.read())
print(f"  status={h['status']}  service={h['service']}")

# ── 2. Dataset summary ───────────────────────────────────────────────────────
print("\n[2] Dataset summary (keyword: high confidence)")
body, t = chat("what datasets are available")
results.append(check("[2]", body, expect_workflow="Summary", expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 3. Validation ────────────────────────────────────────────────────────────
print("\n[3] Validation (keyword: high confidence)")
body, t = chat("validate data quality and referential integrity")
results.append(check("[3]", body, expect_workflow="Validation", expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 4. Scenario compare ──────────────────────────────────────────────────────
print("\n[4] Scenario compare (keyword)")
body, t = chat("compare the two scenarios and show deltas")
results.append(check("[4]", body, expect_workflow="Comparison", expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 5. Domain fulfillment ────────────────────────────────────────────────────
print("\n[5] Domain – Fulfillment (keyword)")
body, t = chat("why do we have stockouts and low fill rate this week")
results.append(check("[5]", body, expect_workflow="Fulfillment", expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 6. Root cause with item ──────────────────────────────────────────────────
print("\n[6] Root cause — item in question")
body, t = chat("why is ITEM 100000000004 unmet")
results.append(check("[6]", body, expect_keys=["Assistant Reply", "Workflow"]))
print(f"       ({t}s)")

# ── 7. Multi-turn: follow-up references prior item via history ───────────────
print("\n[7] Multi-turn: follow-up references 'that item' from history")
body, t = chat("show me demand and supply for that item", use_history=True)
results.append(check("[7]", body, expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 8. Table explain ─────────────────────────────────────────────────────────
print("\n[8] Table explain")
body, t = chat("explain table by_if_snop_out_inddmdview")
results.append(check("[8]", body, expect_workflow="Table", expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 9. Low-confidence → LLM router fallback ──────────────────────────────────
print("\n[9] LLM router fallback (ambiguous, low keyword score)")
body, t = chat("something seems off with the numbers from last week")
results.append(check("[9]", body, expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── 10. Log reader ────────────────────────────────────────────────────────────
print("\n[10] Log reader intent")
body, t = chat("read log: ERROR solver exception capacity exceeded for resource R001 week 202547")
results.append(check("[10]", body, expect_workflow="Log", expect_keys=["Assistant Reply"]))
print(f"       ({t}s)")

# ── Summary ──────────────────────────────────────────────────────────────────
passed = results.count("PASS")
warned = results.count("WARN")
failed = results.count("FAIL")
print("\n" + "=" * 72)
print(f"Results: {passed} PASS  {warned} WARN  {failed} FAIL  (of {len(results)} tests)")
print("=" * 72)
sys.exit(0 if failed == 0 else 1)
