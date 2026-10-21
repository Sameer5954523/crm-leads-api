from app.models import Role
from tests.conftest import auth_header, make_user


def test_bootstrap_creates_first_admin_only_once(client):
    payload = {"email": "boss@example.com", "full_name": "Boss", "password": "password123"}
    first = client.post("/auth/bootstrap", json=payload)
    assert first.status_code == 201
    assert first.json()["role"] == "admin"
    second = client.post("/auth/bootstrap", json={**payload, "email": "other@example.com"})
    assert second.status_code == 409


def test_login_and_me(client, db):
    make_user(db, "agent@example.com", Role.agent)
    headers = auth_header(client, "agent@example.com")
    res = client.get("/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["email"] == "agent@example.com"


def test_wrong_password_rejected(client, db):
    make_user(db, "agent@example.com", Role.agent)
    res = client.post("/auth/token", data={"username": "agent@example.com", "password": "wrongpass1"})
    assert res.status_code == 401


def test_invalid_token_rejected(client):
    res = client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert res.status_code == 401


def test_only_admin_can_create_users(client, db, admin):
    make_user(db, "agent@example.com", Role.agent)
    agent_headers = auth_header(client, "agent@example.com")
    body = {"email": "new@example.com", "full_name": "New Agent", "password": "password123"}
    assert client.post("/users", json=body, headers=agent_headers).status_code == 403
    assert client.post("/users", json=body, headers=admin).status_code == 201
    assert client.post("/users", json=body, headers=admin).status_code == 409


def test_deactivated_user_cannot_use_token(client, db, admin):
    agent = make_user(db, "agent@example.com", Role.agent)
    headers = auth_header(client, "agent@example.com")
    assert client.patch(f"/users/{agent.id}/deactivate", headers=admin).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401
