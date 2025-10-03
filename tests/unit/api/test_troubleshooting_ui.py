from fastapi.testclient import TestClient

from app.main import app


def test_troubleshooting_ui_served():
    client = TestClient(app)
    response = client.get("/ui/troubleshooting")
    assert response.status_code == 200
    # Basic sanity check on returned HTML
    assert "Orbit • Event Sync Tools" in response.text
