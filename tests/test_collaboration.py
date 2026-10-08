from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from agentcommons.models import TaskCreate
from conftest import TOKEN, agent, project


def test_identity_isolation_and_private_messages(api):
    client, _ = api
    p = project(client)
    other = project(client, "Other team")
    alice, ha, _ = agent(client, p, "Alice")
    bob, hb, _ = agent(client, p, "Bob")
    _, hc, _ = agent(client, p, "Charlie")
    assert client.get(f"/api/projects/{other}/snapshot", headers=ha).status_code == 403
    assert len(client.get("/api/projects", headers=ha).json()) == 1
    assert client.post("/api/projects", headers=ha, json={"name": "No", "goal": "No"}).status_code == 403
    client.post(f"/api/projects/{p}/messages", headers=ha, json={"content": "Private handoff", "recipient_id": bob})
    assert client.get(f"/api/projects/{p}/messages", headers=hb).json()[0]["sender_id"] == alice
    assert client.get(f"/api/projects/{p}/messages", headers=hc).json() == []
    assert client.get(f"/api/projects/{p}/messages").json() == []
    for headers in (hc, {"Authorization": f"Bearer {TOKEN}"}):
        snap = client.get(f"/api/projects/{p}/snapshot", headers=headers).json()
        assert not any(event["kind"] == "message.sent" for event in snap["events"])
    assert "token_hash" not in str(client.get(f"/api/projects/{p}/snapshot").json())


def test_concurrent_claim_has_exactly_one_winner(api):
    client, store = api
    p = project(client)
    _, ha, _ = agent(client, p, "Alice")
    _, hb, _ = agent(client, p, "Bob")
    task = store.create_task(store.authenticate(f"Bearer {TOKEN}"), p, TaskCreate(title="One owner"))

    def claim(header):
        try:
            return store.claim_task(store.authenticate(header["Authorization"]), p, task["id"])["status"]
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, [ha, hb]))
    assert sorted(map(str, results)) == ["409", "in_progress"]


def test_plan_dependencies_review_and_changes_cycle(api):
    client, _ = api
    p = project(client, auto_plan=True)
    alice, ha, _ = agent(client, p, "Alice")
    _, hb, _ = agent(client, p, "Bob")
    root = client.get(f"/api/projects/{p}/tasks").json()[0]["id"]
    base = f"/api/projects/{p}/tasks"
    assert client.post(f"{base}/{root}/claim", headers=ha).status_code == 200
    result = client.post(f"{base}/{root}/plan", headers=ha, json={"summary": "Ordered work", "tasks": [
        {"title": "API foundation"}, {"title": "Dashboard", "depends_on": [0]},
    ]})
    assert result.status_code == 200, result.text
    first, second = result.json()["created_task_ids"]
    assert client.post(f"{base}/{second}/claim", headers=hb).status_code == 409
    assert client.patch(f"{base}/{first}", json={"dependencies": [second]}).status_code == 422
    client.post(f"{base}/{first}/claim", headers=ha)
    work = {"summary": "API ready, tests pass", "branch": "agentcommons/api", "commit_sha": "a" * 40, "diff": "+working code"}
    assert client.post(f"{base}/{first}/submit", headers=hb, json=work).status_code == 403
    assert client.post(f"{base}/{first}/submit", headers=ha, json=work).status_code == 200
    assert client.post(f"{base}/{first}/review-claim", headers=ha).status_code == 403
    client.post(f"{base}/{first}/review-claim", headers=hb)
    assert client.post(f"{base}/{first}/review", headers=ha, json={"decision": "approve", "comment": "No"}).status_code == 403
    feedback = client.post(f"{base}/{first}/review", headers=hb, json={"decision": "changes_requested", "comment": "Add a test."}).json()
    assert feedback["status"] == "backlog" and feedback["assignee_id"] is None
    client.post(f"{base}/{first}/claim", headers=ha)
    client.post(f"{base}/{first}/submit", headers=ha, json={**work, "commit_sha": "b" * 40})
    client.post(f"{base}/{first}/review-claim", headers=hb)
    accepted = client.post(f"{base}/{first}/review", headers=hb, json={"decision": "approve", "comment": "Tests verified.", "integration_sha": "c" * 40}).json()
    assert accepted["status"] == "done" and accepted["integration_sha"] == "c" * 40
    assert accepted["assignee_id"] == alice
    assert client.post(f"{base}/{second}/claim", headers=hb).status_code == 200


def test_invalid_plan_rolls_back_all_created_tasks(api):
    client, _ = api
    p = project(client, auto_plan=True)
    _, headers, _ = agent(client, p, "Planner")
    task = client.get(f"/api/projects/{p}/tasks").json()[0]
    path = f"/api/projects/{p}/tasks/{task['id']}"
    client.post(f"{path}/claim", headers=headers)
    assert client.post(f"{path}/plan", headers=headers, json={"summary": "Oops", "tasks": [
        {"title": "Valid"}, {"title": "Invalid", "depends_on": [3]},
    ]}).status_code == 422
    assert len(client.get(f"/api/projects/{p}/tasks").json()) == 1
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "in_progress"


def test_memory_conflicts_pause_and_revocation(api):
    client, _ = api
    p = project(client)
    a, headers, _ = agent(client, p, "Alice")
    path = f"/api/projects/{p}"
    note = client.post(f"{path}/memories", headers=headers, json={"title": "Architecture", "content": "Use SQLite."}).json()
    update = {"title": "Architecture", "content": "Use WAL.", "expected_version": 1}
    assert client.put(f"{path}/memories/{note['id']}", headers=headers, json=update).json()["version"] == 2
    assert client.put(f"{path}/memories/{note['id']}", headers=headers, json=update).status_code == 409
    task = client.post(f"{path}/tasks", json={"title": "Implement storage"}).json()
    client.patch(path, json={"status": "paused"})
    assert client.post(f"{path}/tasks/{task['id']}/claim", headers=headers).status_code == 409
    client.patch(path, json={"status": "active"})
    client.post(f"{path}/tasks/{task['id']}/claim", headers=headers)
    assert client.delete(f"{path}/agents/{a}").status_code == 200
    assert client.get("/api/me", headers=headers).status_code == 401
    assert client.get(f"{path}/tasks").json()[0]["status"] == "backlog"


def test_realtime_ticket_is_single_use_and_streams_events(api):
    client, _ = api
    p = project(client)
    snap = client.get(f"/api/projects/{p}/snapshot").json()
    ticket = client.post(f"/api/realtime-ticket?project_id={p}").json()["ticket"]
    with client.websocket_connect(f"/api/live?ticket={ticket}&after={snap['cursor']}") as ws:
        assert ws.receive_json()["type"] == "ping"
        client.post(f"/api/projects/{p}/messages", json={"content": "Hello teammates!"})
        assert ws.receive_json()["events"][0]["kind"] == "message.sent"
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/live?ticket={ticket}"):
            pass


def test_mcp_tools_use_scoped_identity(api):
    client, _ = api
    p = project(client)
    agent_id, headers, _ = agent(client, p, "MCP peer")
    h = {**headers, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
    listing = client.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert listing.status_code == 200, listing.text
    assert "claim_task" in [t["name"] for t in listing.json()["result"]["tools"]]
    message = client.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "send_message", "arguments": {"project_id": p, "content": "Hello from MCP"},
    }})
    assert message.status_code == 200, message.text
    assert not message.json()["result"].get("isError"), message.text
    assert client.get(f"/api/projects/{p}/messages").json()[0]["sender_id"] == agent_id
    assert client.post("/mcp/", headers={"Authorization": "Bearer invalid"}, json={}).status_code == 401


def test_password_login_requires_configuration_supports_unicode_and_revokes_sessions(api, monkeypatch):
    client, _ = api
    for prefix in ("AGENTVERSE", "AGENTCOMMONS"):
        monkeypatch.delenv(f"{prefix}_ADMIN_USERNAME", raising=False)
        monkeypatch.delenv(f"{prefix}_ADMIN_PASSWORD", raising=False)
    assert client.post("/api/login", json={"username": "kali", "password": "kali"}).status_code == 503
    monkeypatch.setenv("AGENTVERSE_ADMIN_USERNAME", "用戶")
    monkeypatch.setenv("AGENTVERSE_ADMIN_PASSWORD", "pässword")
    login = client.post("/api/login", json={"username": "用戶", "password": "pässword"})
    assert login.status_code == 200
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/me", headers=headers).json()["admin"] is True
    assert client.post("/api/logout", headers=headers).json() == {"ok": True}
    assert client.get("/api/me", headers=headers).status_code == 401


def test_password_login_rate_limits_failed_attempts(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("AGENTVERSE_ADMIN_USERNAME", "audit-admin")
    monkeypatch.setenv("AGENTVERSE_ADMIN_PASSWORD", "audit-password")
    results = [client.post("/api/login", json={"username": "audit-admin", "password": "wrong"}).status_code for _ in range(10)]
    assert results == [401] * 10
    assert client.post("/api/login", json={"username": "audit-admin", "password": "wrong"}).status_code == 429


def test_remote_mcp_hostname_and_origin_validation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agentcommons.server import create_app

    monkeypatch.setenv("AGENTCOMMONS_DOMAIN", "commons.example.test")
    app = create_app(str(tmp_path / "remote.db"), TOKEN, web_dir=str(tmp_path / "no-web"))
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with TestClient(app, base_url="https://commons.example.test", headers=headers) as client:
        assert client.post("/mcp/", json=request).status_code == 200
        assert client.post("/mcp/", json=request, headers={"Host": "untrusted.example"}).status_code == 421
        assert client.post("/mcp/", json=request, headers={"Origin": "https://untrusted.example"}).status_code == 403
