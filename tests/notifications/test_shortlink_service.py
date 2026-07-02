from fastapi.testclient import TestClient

from shortlink_service.app import app


def test_create_and_resolve_short_link():
    client = TestClient(app)
    create_response = client.post(
        "/api/v1/short-links",
        json={"target_url": "https://movies.local/movies/777"},
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["code"]
    resolve_response = client.get(f"/s/{body['code']}", follow_redirects=False)
    assert resolve_response.status_code == 307
