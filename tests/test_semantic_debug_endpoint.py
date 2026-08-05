from fastapi.testclient import TestClient

from webapp.app.main import app


client = TestClient(app)


def test_semantic_debug_endpoint_returns_semantic_sections():
    payload = {
        "question": "Root cause why demand was not met for item 100000000008 at site F28",
        "scope": {"site": "F28"},
    }

    response = client.post("/api/semantic/debug", json=payload)

    assert response.status_code == 200
    body = response.json()

    assert "intent_classification" in body
    assert "entity_extraction" in body
    assert "semantic_retrieval" in body
    assert "file_selection" in body
    assert "kpi_selection" in body
    assert "relationship_discovery" in body
    assert "hallucinations" in body

    assert body["hallucinations"]["has_hallucination"] in {True, False}
    assert "semantic_snapshot" in body
