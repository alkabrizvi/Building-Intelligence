from fastapi.testclient import TestClient

from building_with_rag.main import app
from building_with_rag.registry import MODEL_IDS

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_query_placeholder():
    r = client.post("/v1/query", json={"question": "What is murder?", "pattern": "semantic"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_implemented" and body["results"] == []


def test_query_validation():
    assert client.post("/v1/query", json={"question": "", "pattern": "semantic"}).status_code == 422


def test_models():
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids == list(MODEL_IDS.values())


def test_chat_json_and_sse():
    payload = {"model": "rag-semantic", "messages": [{"role": "user", "content": "hi"}]}
    r = client.post("/v1/chat/completions", json=payload)
    assert "not implemented" in r.json()["choices"][0]["message"]["content"]
    s = client.post("/v1/chat/completions", json={**payload, "stream": True})
    assert s.text.rstrip().endswith("data: [DONE]")


def test_chat_error_envelope():
    r = client.post("/v1/chat/completions", json={"model": "nope", "messages": []})
    assert "error" in r.json()
