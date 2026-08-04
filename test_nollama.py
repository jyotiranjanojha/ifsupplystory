import json
import urllib.request

# Test chat endpoint with Nollama
payload = {
    "question": "What is the inventory level?",
    "llm_enabled": True,
    "history": [],
    "scope": {}
}

req = urllib.request.Request(
    "http://127.0.0.1:8010/api/chat",
    method="POST",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}
)

try:
    print("Testing Nollama integration...")
    print("Request sent to http://127.0.0.1:8010/api/chat")
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    print("✅ Nollama Integration Test Results")
    print("=" * 50)
    print(f"LLM Provider: {result.get('LLM Provider')}")
    print(f"Model: {result.get('LLM Model')}")
    print(f"Workflow: {result.get('Workflow')}")
    print(f"LLM Used: {result.get('llm_used')}")
    if result.get('Assistant Reply'):
        print(f"\nResponse Preview:")
        print(result.get("Assistant Reply")[:300])
    print("\n✅ Nollama v1 API Integration Working!")
except urllib.error.URLError as e:
    print(f"❌ Connection Error: {e}")
except json.JSONDecodeError as e:
    print(f"❌ JSON Decode Error: {e}")
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
