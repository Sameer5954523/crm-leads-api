from app.models import Role
from tests.conftest import auth_header, make_user


def new_lead(client, headers, **overrides):
    body = {"full_name": "Jane Doe", "email": "jane@example.com", "source": "facebook", "campaign": "uk-debt"}
    body.update(overrides)
    return client.post("/leads", json=body, headers=headers)


def test_create_lead_requires_contact(client, admin):
    res = client.post("/leads", json={"full_name": "No Contact"}, headers=admin)
    assert res.status_code == 422


def test_duplicate_lead_is_rejected(client, admin):
    assert new_lead(client, admin).status_code == 201
    dup = new_lead(client, admin, full_name="Jane D", email="JANE@example.com")
    assert dup.status_code == 409


def test_phone_is_normalised_for_duplicate_check(client, admin):
    assert new_lead(client, admin, email=None, phone="+44 7700 900-123").status_code == 201
    assert new_lead(client, admin, email=None, phone="+447700900123").status_code == 409


def test_round_robin_assigns_least_loaded_agent(client, db, admin):
    a1 = make_user(db, "a1@example.com", Role.agent)
    a2 = make_user(db, "a2@example.com", Role.agent)
    first = new_lead(client, admin, email="l1@example.com").json()
    second = new_lead(client, admin, email="l2@example.com").json()
    third = new_lead(client, admin, email="l3@example.com").json()
    assert [first["assigned_to_id"], second["assigned_to_id"], third["assigned_to_id"]] == [a1.id, a2.id, a1.id]


def test_agent_only_sees_own_leads(client, db, admin):
    make_user(db, "a1@example.com", Role.agent)
    make_user(db, "a2@example.com", Role.agent)
    l1 = new_lead(client, admin, email="l1@example.com").json()
    l2 = new_lead(client, admin, email="l2@example.com").json()
    a1 = auth_header(client, "a1@example.com")
    listing = client.get("/leads", headers=a1).json()
    assert [item["id"] for item in listing["items"]] == [l1["id"]]
    assert client.get(f"/leads/{l2['id']}", headers=a1).status_code == 404


def test_status_pipeline_enforces_valid_transitions(client, admin):
    lead = new_lead(client, admin).json()
    skip = client.post(f"/leads/{lead['id']}/status", json={"status": "converted"}, headers=admin)
    assert skip.status_code == 422
    for step in ["contacted", "qualified", "converted"]:
        res = client.post(f"/leads/{lead['id']}/status", json={"status": step, "note": "ok"}, headers=admin)
        assert res.status_code == 200
        assert res.json()["status"] == step
    detail = client.get(f"/leads/{lead['id']}", headers=admin).json()
    kinds = [a["kind"] for a in detail["activities"]]
    assert kinds.count("status") == 3


def test_notes_and_activity_history(client, admin):
    lead = new_lead(client, admin).json()
    res = client.post(f"/leads/{lead['id']}/notes", json={"message": "Called, asked to ring back"}, headers=admin)
    assert res.status_code == 201
    assert res.json()["activities"][-1]["message"] == "Called, asked to ring back"


def test_filter_search_and_pagination(client, admin):
    for i in range(5):
        new_lead(client, admin, full_name=f"Person {i}", email=f"p{i}@example.com", source="google" if i % 2 else "facebook")
    page = client.get("/leads", params={"source": "google", "size": 1, "page": 2}, headers=admin).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    search = client.get("/leads", params={"q": "person 3"}, headers=admin).json()
    assert search["total"] == 1


def test_manager_can_assign_but_agent_cannot(client, db, admin, manager):
    agent = make_user(db, "a1@example.com", Role.agent)
    lead = new_lead(client, admin).json()
    agent_headers = auth_header(client, "a1@example.com")
    assert client.post(f"/leads/{lead['id']}/assign", json={"user_id": agent.id}, headers=agent_headers).status_code == 403
    assert client.post(f"/leads/{lead['id']}/assign", json={"user_id": agent.id}, headers=manager).status_code == 200


def test_pipeline_stats(client, admin, manager):
    a = new_lead(client, admin, email="a@example.com", source="google").json()
    new_lead(client, admin, email="b@example.com", source="facebook")
    for step in ["contacted", "qualified", "converted"]:
        client.post(f"/leads/{a['id']}/status", json={"status": step}, headers=admin)
    stats = client.get("/leads/stats", headers=manager).json()
    assert stats["total"] == 2
    assert stats["by_status"]["converted"] == 1
    assert stats["by_source"] == {"google": 1, "facebook": 1}
    assert stats["conversion_rate"] == 0.5


def test_only_admin_can_delete(client, admin, manager):
    lead = new_lead(client, admin).json()
    assert client.delete(f"/leads/{lead['id']}", headers=manager).status_code == 403
    assert client.delete(f"/leads/{lead['id']}", headers=admin).status_code == 204
    assert client.get(f"/leads/{lead['id']}", headers=admin).status_code == 404
