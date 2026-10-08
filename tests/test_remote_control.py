import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import httpx

from agentcommons.node import NodeConfig, NodeService
from agentcommons.store import Store
from conftest import TOKEN, agent, project

SESSION = "a" * 32
PROFILES = [{"id": "test-peer", "name": "Custom peer", "kind": "custom", "models": [
    {"id": "provider/fast", "name": "Fast model"}, {"id": "provider/deep", "name": "Deep reasoning"},
]}]


def node(client, project_id, register=True):
    result = client.post(f"/api/projects/{project_id}/nodes", json={"name": "Development VPS"})
    assert result.status_code == 201, result.text
    data = result.json()
    headers = {"Authorization": f"Bearer {data['token']}"}
    if register:
        response = client.post("/api/nodes/me/register", headers=headers, json={"session_id": SESSION, "profiles": PROFILES})
        assert response.status_code == 200, response.text
    return data["node"]["id"], headers, data["token"]


def configure(client, project_id, agent_id, node_id, model="provider/deep"):
    response = client.put(f"/api/projects/{project_id}/agents/{agent_id}/runtime", json={
        "node_id": node_id, "profile_id": "test-peer", "model": model})
    assert response.status_code == 200, response.text
    return response.json()


def test_runtime_permissions_catalog_validation_and_private_credentials(api):
    client, store = api
    p, other = project(client), project(client, "Other")
    a, agent_headers, _ = agent(client, p, "Atlas")
    n, node_headers, node_token = node(client, p)
    alien_node, _, _ = node(client, other)
    path = f"/api/projects/{p}/agents/{a}"
    config = {"node_id": n, "profile_id": "test-peer", "model": "provider/deep"}
    assert client.get("/api/projects", headers=node_headers).status_code == 401
    assert client.post("/api/nodes/me/poll", headers=agent_headers, json={"session_id": SESSION}).status_code == 401
    assert client.put(f"{path}/runtime", headers=agent_headers, json=config).status_code == 403
    assert client.put(f"{path}/runtime", json={**config, "node_id": alien_node}).status_code == 404
    assert client.put(f"{path}/runtime", json={**config, "model": "not-advertised"}).status_code == 422
    assert client.put(f"{path}/runtime", json={**config, "profile_id": "unknown"}).status_code == 422
    configure(client, p, a, n)
    snap = client.get(f"/api/projects/{p}/snapshot").json()
    assert snap["nodes"][0]["online"]
    assert snap["agents"][0]["runtime"]["model"] == "provider/deep"
    assert node_token not in json.dumps(snap) and "token_hash" not in json.dumps(snap)
    assert store.one("SELECT token_hash FROM nodes WHERE id=?", (n,))["token_hash"] == hashlib.sha256(node_token.encode()).hexdigest()


def test_idempotent_launch_stop_ack_and_generation_fencing(api):
    client, _ = api
    p = project(client)
    a, _, _ = agent(client, p, "Atlas")
    n, h, _ = node(client, p)
    configure(client, p, a, n)
    path = f"/api/projects/{p}/agents/{a}"
    queued = client.post(f"{path}/launch").json()
    with ThreadPoolExecutor(2) as pool:
        launches = list(pool.map(lambda _: client.post(f"{path}/launch").json(), range(2)))
    assert all(row["run_id"] == queued["run_id"] for row in launches)
    payload = {"session_id": SESSION}
    runtime = client.post("/api/nodes/me/poll", headers=h, json=payload).json()["runtimes"][0]
    repeated = client.post("/api/nodes/me/poll", headers=h, json=payload).json()["runtimes"][0]
    assert runtime["state"] == "starting" and runtime["token"] == repeated["token"]
    managed = {"Authorization": f"Bearer {runtime['token']}"}
    assert client.get("/api/me", headers=managed).json()["actor_id"] == a
    t = client.post(f"/api/projects/{p}/tasks", json={"title": "Interruptible task"}).json()
    client.post(f"/api/projects/{p}/tasks/{t['id']}/claim", headers=managed)
    report = {"session_id": SESSION, "agent_id": a, "run_id": queued["run_id"], "state": "running", "pid": 12345}
    assert client.post("/api/nodes/me/report", headers=h, json=report).status_code == 200
    assert client.put(f"{path}/runtime", json={"node_id": n, "profile_id": "test-peer", "model": "provider/fast"}).status_code == 409
    stopped = client.post(f"{path}/stop").json()
    assert stopped["state"] == "stopping"
    assert client.post("/api/agents/heartbeat", headers=managed, json={"status": "working"}).json()["stop_requested"]
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "in_progress"
    assert client.post(f"{path}/launch").status_code == 409
    assert client.post(f"/api/projects/{p}/tasks/{t['id']}/claim", headers=managed).status_code == 409
    final = client.post("/api/nodes/me/report", headers=h, json={**report, "state": "stopped", "pid": None}).json()
    assert final["state"] == "stopped" and final["desired_state"] == "stopped"
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "backlog"
    assert client.get("/api/me", headers=managed).status_code == 401
    configure(client, p, a, n, "provider/fast")
    again = client.post(f"{path}/launch").json()
    assert again["run_id"] != queued["run_id"]
    assert client.post("/api/nodes/me/report", headers=h, json={**report, "state": "stopped"}).status_code == 409


def test_offline_node_session_ownership_and_lease_expiry(api):
    client, store = api
    p = project(client)
    a, _, _ = agent(client, p, "Atlas")
    n, h, _ = node(client, p)
    configure(client, p, a, n)
    path = f"/api/projects/{p}/agents/{a}"
    client.post(f"{path}/launch")
    runtime = client.post("/api/nodes/me/poll", headers=h, json={"session_id": SESSION}).json()["runtimes"][0]
    replacement = {"session_id": "b" * 32, "profiles": PROFILES}
    assert client.post("/api/nodes/me/register", headers=h, json=replacement).status_code == 409
    store.db.execute("UPDATE nodes SET last_seen=? WHERE id=?", (time.time() - 91, n))
    assert client.get("/api/me", headers={"Authorization": f"Bearer {runtime['token']}"}).status_code == 401
    assert client.post(f"{path}/launch").status_code == 409
    assert client.post("/api/nodes/me/register", headers=h, json=replacement).status_code == 200
    assert client.post("/api/nodes/me/poll", headers=h, json={"session_id": SESSION}).status_code == 409
    assert client.get(f"/api/projects/{p}/snapshot").json()["agents"][0]["runtime"]["state"] == "failed"


def test_managed_revocation_cancels_run_before_releasing_claims(api):
    client, _ = api
    p = project(client)
    a, _, _ = agent(client, p, "Atlas")
    n, h, _ = node(client, p)
    configure(client, p, a, n)
    path = f"/api/projects/{p}/agents/{a}"
    client.post(f"{path}/launch")
    row = client.post("/api/nodes/me/poll", headers=h, json={"session_id": SESSION}).json()["runtimes"][0]
    managed = {"Authorization": f"Bearer {row['token']}"}
    task = client.post(f"/api/projects/{p}/tasks", json={"title": "Active work"}).json()
    client.post(f"/api/projects/{p}/tasks/{task['id']}/claim", headers=managed)
    assert client.delete(path).status_code == 200
    assert client.get("/api/me", headers=managed).status_code == 401
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "in_progress"
    client.post("/api/nodes/me/report", headers=h, json={"session_id": SESSION, "agent_id": a,
        "run_id": row["run_id"], "state": "stopped"})
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "backlog"
    assert client.post(f"{path}/launch").status_code == 409


def test_upgrade_preserves_existing_agent_tokens_and_project_state(tmp_path):
    path = str(tmp_path / "old.db")
    old = Store(path, TOKEN)
    from agentcommons.models import AgentCreate, ProjectCreate
    identity = old.authenticate(f"Bearer {TOKEN}")
    p = old.create_project(identity, ProjectCreate(name="Existing project", goal="Keep this goal", auto_plan=False))
    a = old.add_agent(identity, p["id"], AgentCreate(name="Existing peer"))
    old.db.execute("ALTER TABLE agents DROP COLUMN revoked")
    old.close()
    updated = Store(path, TOKEN)
    assert updated.authenticate(f"Bearer {a['token']}").agent_id == a["agent"]["id"]
    snap = updated.snapshot(identity, p["id"])
    assert snap["project"]["goal"] == "Keep this goal"
    assert snap["agents"][0]["runtime"] is None and snap["nodes"] == []
    updated.close()


@pytest.mark.parametrize("stop_mode", ["dashboard", "server_5xx"])
def test_supervisor_launches_model_and_stops_real_worker_and_cli_children(live_server, tmp_path, monkeypatch, stop_mode):
    url, client = live_server
    repo = tmp_path / "managed-project"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Remote test", "GIT_COMMITTER_NAME": "Remote test",
           "GIT_AUTHOR_EMAIL": "remote@example.test", "GIT_COMMITTER_EMAIL": "remote@example.test"}
    for args in (["init", "--initial-branch=main"], ["commit", "--allow-empty", "-m", "Initialize test clone"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    trace = tmp_path / "agent-trace.json"
    monkeypatch.setenv("AGENTCOMMONS_TEST_TRACE", str(trace))
    monkeypatch.setenv("AGENTCOMMONS_ADMIN_TOKEN", "must-not-reach-worker-or-cli")
    monkeypatch.setenv("AGENTCOMMONS_NODE_TOKEN", "must-not-reach-worker-or-cli")
    p = project(client)
    a, _, _ = agent(client, p, "Managed Atlas")
    n, _, token = node(client, p, register=False)
    script = Path(__file__).parent / "fixtures/controlled_cli.py"
    config = NodeConfig(repo=str(repo), log_dir=str(tmp_path / "logs"), profiles=[{
        **PROFILES[0], "argv": [sys.executable, str(script), "{prompt_file}", "{model}"], "push": False,
    }])
    service = NodeService(url, token, config, interval=0.1)
    try:
        service.register()
        configure(client, p, a, n)
        t = client.post(f"/api/projects/{p}/tasks", json={"title": "A long-running task"}).json()
        path = f"/api/projects/{p}/agents/{a}"
        client.post(f"{path}/launch")
        service.step()
        child = service.children[a]
        deadline = time.monotonic() + 10
        while not trace.exists():
            assert child.process.poll() is None, (tmp_path / "logs" / f"{child.run_id}.log").read_text()
            if time.monotonic() > deadline:
                raise AssertionError("Managed coding CLI did not start")
            time.sleep(0.1)
        evidence = json.loads(trace.read_text())
        assert evidence["argv_model"] == evidence["env_model"] == evidence["context_model"] == "provider/deep"
        assert evidence["admin_token"] is None and evidence["node_token"] is None
        assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "in_progress"
        if stop_mode == "dashboard":
            client.post(f"{path}/stop")
            service.step()
        else:
            request = httpx.Request("POST", f"{url}/api/nodes/me/poll")
            def failed_poll():
                raise httpx.HTTPStatusError("Unavailable", request=request, response=httpx.Response(503, request=request))
            monkeypatch.setattr(service, "register", lambda: {"node": {"name": "Test node"}})
            monkeypatch.setattr(service, "step", failed_poll)
            service.last_success = time.monotonic() - 46
            with pytest.raises(RuntimeError, match="lease expired"):
                service.run()
        assert child.process.poll() == 0
        assert a not in service.children
        snapshot = client.get(f"/api/projects/{p}/snapshot").json()
        assert snapshot["agents"][0]["runtime"]["state"] == "stopped"
        assert snapshot["tasks"][0]["id"] == t["id"] and snapshot["tasks"][0]["status"] == "backlog"
        for pid in (evidence["pid"], evidence["child_pid"]):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        service.shutdown()


def test_missing_tool_does_not_disable_other_node_profiles(live_server, tmp_path):
    url, client = live_server
    p = project(client)
    node_id, _, token = node(client, p, register=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "Initial"],
                   cwd=repo, check=True, capture_output=True)
    service = NodeService(url, token, NodeConfig(repo=str(repo), log_dir=str(tmp_path / "logs"), profiles=[
        {**PROFILES[0], "argv": ["agentverse-nonexistent-executable"]},
        {**PROFILES[0], "id": "healthy", "name": "Healthy CLI", "argv": [sys.executable], "push": False},
    ]))
    try:
        registered = service.register()["node"]
        assert registered["online"]
        assert registered["profiles"][0]["availability"] == "unavailable"
        assert registered["profiles"][1]["availability"] == "available"
        a, _, _ = agent(client, p, "Healthy teammate")
        configure(client, p, a, node_id)
        assert client.post(f"/api/projects/{p}/agents/{a}/launch").status_code == 409
        response = client.put(f"/api/projects/{p}/agents/{a}/runtime", json={"node_id": node_id, "profile_id": "healthy", "model": "provider/deep"})
        assert response.status_code == 200
        assert client.post(f"/api/projects/{p}/agents/{a}/launch").status_code == 200
    finally:
        service.shutdown()


def test_managed_launch_does_not_duplicate_an_external_agent_session(api):
    client, _ = api
    p = project(client)
    a, h, _ = agent(client, p, "Atlas")
    n, _, _ = node(client, p)
    configure(client, p, a, n)
    path = f"/api/projects/{p}/agents/{a}"
    client.post("/api/agents/heartbeat", headers=h, json={"status": "idle"})
    assert client.post(f"{path}/launch").status_code == 409
    client.post("/api/agents/heartbeat", headers=h, json={"status": "offline"})
    assert client.post(f"{path}/launch").status_code == 200
