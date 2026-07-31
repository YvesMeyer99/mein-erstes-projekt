from fastapi.testclient import TestClient

from app.main import app, get_session


def _client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_cors_allows_localhost_vite_dev_server(db_session):
    client = _client(db_session)

    response = client.get("/api/portfolio", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    app.dependency_overrides.clear()


def test_cors_allows_127_0_0_1_vite_dev_server(db_session):
    client = _client(db_session)

    response = client.get("/api/portfolio", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    app.dependency_overrides.clear()


def test_cors_rejects_unknown_origin(db_session):
    client = _client(db_session)

    response = client.get("/api/portfolio", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
    app.dependency_overrides.clear()
