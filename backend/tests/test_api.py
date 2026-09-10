from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_arithmetic():
    payload = {"question": "What is 18 + 27?"}
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "45" in body["answer"] or "18 + 27" in body["answer"]
    assert any(item.get("name") == "calculator" for item in body["trace"] if item.get("type") == "tool")


def test_chat_trip_question():
    payload = {"question": "How much is a 3 night trip to Barcelona?"}
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tool_calls"] > 0
    assert isinstance(body["trace"], list)
