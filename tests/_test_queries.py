"""Quick diagnostic: test prompt building for 10 planning queries without LLM call."""
import sys, json
sys.path.insert(0, '.')
from pathlib import Path
from webapp.app.analyzer import build_grounded_chat_prompt

BASE_DIR = Path('.')
QUERIES = [
    "What is fill rate for an item 2000-293-667",
    "Why fill rates are dropping for product 2000-293-667",
    "Why demand got late or short for item 2000-293-667",
    "What is resource utilization for RES01",
    "Why resource utilization is low for RES01",
    "What are horizons in which resource RES01 is underloaded",
    "Why demand met early for item 2000-293-667",
    "Why site mix is changing for item 2000-293-667",
    "Why fill rates changing solve over solve run",
    "What is end of horizon inventory for item 2000-293-667",
]

for i, q in enumerate(QUERIES, 1):
    try:
        _, prompt, meta = build_grounded_chat_prompt(BASE_DIR, q, None, None, {})
        workflow = meta['workflow']
        has_data = meta['workflow_result'] is not None
        rag_hits = len((meta.get('rag_evidence') or {}).get('hits', []))
        status = "OK" if (has_data or rag_hits > 0) else "NO DATA"
        data_snippet = ""
        if has_data:
            r = meta['workflow_result']
            if isinstance(r, dict):
                keys = list(r.keys())[:3]
                data_snippet = f"  data keys: {keys}"
        print(f"[{i:2}] {status}")
        print(f"     Q: {q[:60]}")
        print(f"     Workflow: {workflow}")
        print(f"     RAG hits: {rag_hits} | Workflow data: {has_data}{data_snippet}")
        print()
    except Exception as e:
        print(f"[{i:2}] ERROR: {e}")
        print(f"     Q: {q[:60]}")
        print()
