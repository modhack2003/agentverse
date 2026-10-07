import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from agentcommons.drivers import CLIDriver
from agentcommons.http_adapter import read_state, reconcile
from agentcommons.models import RuntimeProfile
from agentcommons.node import LocalProfile, NodeConfig, NodeService
from agentcommons.worker import RemoteCancellationUnconfirmed, WorkerStopped, execute_agent
from conftest import agent, project
from test_remote_control import SESSION, node


def test_peers_profiles_help_routing_and_issues(api):
    client, _ = api
    p, other = project(client), project(client, "Other")
    a, ah, _ = agent(client, p, "Builder")
    b, bh, _ = agent(client, p, "Reviewer")
    _, oh, _ = agent(client, other, "Outsider")
    announced = client.post("/api/agents/announce", headers=bh, json={
        "connection": "mcp", "capabilities": ["review"], "limitations": ["No browser"], "tool_version": "1.2"})
    assert announced.status_code == 200
    assert announced.json()["agent"]["limitations"] == ["No browser"]
    assert client.post("/api/agents/announce", headers=ah, json={"protocol_version": 2}).status_code == 426
    assert client.get(f"/api/projects/{p}/teammates", headers=oh).status_code == 403
    peers = client.get(f"/api/projects/{p}/teammates?capability=review", headers=ah).json()
    assert [peer["id"] for peer in peers] == [b]
    edit = {"name": "Builder", "description": "Maintains Python services", "capabilities": ["python"],
            "limitations": ["No UI automation"], "expected_version": 1}
    assert client.patch(f"/api/projects/{p}/agents/{a}", headers=ah, json=edit).status_code == 403
    assert client.patch(f"/api/projects/{p}/agents/{a}", json=edit).status_code == 200
    assert client.patch(f"/api/projects/{p}/agents/{a}", json=edit).status_code == 409
    request = client.post(f"/api/projects/{p}/help", headers=ah, json={"capability": "review", "question": "Check the concurrency design"}).json()
    assert request["recipient_id"] == b
    path = f"/api/projects/{p}/help/{request['id']}"
    assert client.post(f"{path}/claim", headers=ah).status_code == 409
    assert client.post(f"{path}/answer", headers=bh, json={"answer": "Use an atomic claim."}).status_code == 403
    assert client.post(f"{path}/claim", headers=bh).status_code == 200
    assert client.post(f"{path}/claim", headers=bh).status_code == 409
    assert client.post(f"{path}/answer", headers=bh, json={"answer": "Use an atomic claim."}).json()["state"] == "answered"
    issue_path = f"/api/projects/{p}/agents/{b}/issues"
    assert client.post(issue_path, headers=ah, json={"title": "Authentication expired"}).status_code == 403
    issue = client.post(issue_path, headers=bh, json={"title": "Authentication expired", "detail": "Reauthenticate on my node"}).json()
    assert client.post(f"/api/projects/{p}/issues/{issue['id']}/resolve", headers=ah).status_code == 403
    assert client.post(f"/api/projects/{p}/issues/{issue['id']}/resolve").status_code == 200
    snap = client.get(f"/api/projects/{p}/snapshot").json()
    assert snap["issues"][0]["resolved"] == 1
    assert snap["help_requests"][0]["answer"] == "Use an atomic claim."
    assert any(m["content"] == "Use an atomic claim." for m in snap["messages"])


def test_capability_claims_and_token_rotation(api):
    client, _ = api
    p = project(client)
    a, ah, _ = agent(client, p, "Generalist")
    task = client.post(f"/api/projects/{p}/tasks", json={"title": "Python service", "required_capabilities": ["python"]}).json()
    path = f"/api/projects/{p}/tasks/{task['id']}/claim"
    assert client.post(path, headers=ah).status_code == 409
    client.post("/api/agents/announce", headers=ah, json={"capabilities": ["python"]})
    assert client.post(path, headers=ah).status_code == 200
    assert client.post(f"/api/projects/{p}/agents/{a}/token").status_code == 409
    client.post(f"/api/projects/{p}/tasks/{task['id']}/release", headers=ah, json={})
    rotated = client.post(f"/api/projects/{p}/agents/{a}/token").json()
    assert client.get("/api/me", headers=ah).status_code == 401
    assert client.get("/api/me", headers={"Authorization": f"Bearer {rotated['token']}"}).status_code == 200


def test_all_modes_settings_inventory_and_unconfirmed_claims(api):
    client, store = api
    p = project(client)
    a, native, _ = agent(client, p, "API peer")
    n, nh, _ = node(client, p, register=False)
    profiles = [{"id": mode, "name": mode, "kind": "custom", "mode": mode, "capabilities": ["python"],
                 "settings_schema": [{"key": "effort", "label": "Effort", "type": "choice", "options": ["low", "high"], "default": "low"},
                                     {"key": "budget", "label": "Budget", "type": "number", "minimum": 1, "maximum": 5, "default": 2}]} for mode in ["managed_cli", "managed_api", "connected"]]
    inventory = {"session_id": SESSION, "profiles": profiles}
    assert client.post("/api/nodes/me/register", headers=nh, json=inventory).status_code == 200
    base = f"/api/projects/{p}/agents/{a}"
    config = {"node_id": n, "profile_id": "connected", "settings": {"effort": "high"}}
    assert client.put(f"{base}/runtime", json={**config, "settings": {"budget": True}}).status_code == 422
    assert client.put(f"{base}/runtime", json={**config, "settings": {"budget": 6}}).status_code == 422
    assert client.put(f"{base}/runtime", json={**config, "settings": {"secret": "x"}}).status_code == 422
    assert client.put(f"{base}/runtime", json=config).json()["state"] == "external"
    assert client.post(f"{base}/launch").status_code == 409
    assert client.post(f"{base}/stop").status_code == 409
    config["profile_id"] = "managed_api"
    assert client.put(f"{base}/runtime", json=config).json()["settings"] == {"effort": "high", "budget": 2}
    run = client.post(f"{base}/launch").json()
    assert client.get("/api/me", headers=native).status_code == 401
    row = client.post("/api/nodes/me/poll", headers=nh, json={"session_id": SESSION}).json()["runtimes"][0]
    managed = {"Authorization": f"Bearer {row['token']}"}
    task = client.post(f"/api/projects/{p}/tasks", json={"title": "Held until cancellation", "required_capabilities": ["python"]}).json()
    assert client.post(f"/api/projects/{p}/tasks/{task['id']}/claim", headers=managed).status_code == 200
    report = {"session_id": SESSION, "agent_id": a, "run_id": run["run_id"], "state": "unconfirmed"}
    assert client.post("/api/nodes/me/report", headers=nh, json=report).status_code == 200
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "in_progress"
    assert client.post(f"/api/projects/{p}/tasks/{task['id']}/release", json={}).status_code == 409
    assert client.post(f"{base}/launch").status_code == 409
    assert client.put(f"{base}/runtime", json=config).status_code == 409
    client.delete(base)
    assert store.one("SELECT state FROM agent_runtimes WHERE agent_id=?", (a,))["state"] == "unconfirmed"
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "in_progress"
    report["state"] = "stopped"
    assert client.post("/api/nodes/me/report", headers=nh, json=report).status_code == 200
    assert client.get(f"/api/projects/{p}/tasks").json()[0]["status"] == "backlog"
    profiles[0]["availability"] = "unavailable"
    assert client.post("/api/nodes/me/inventory", headers=nh, json=inventory).status_code == 200
    assert client.get(f"/api/projects/{p}/nodes").json()[0]["profiles"][0]["availability"] == "unavailable"


def test_schema_and_cli_setting_substitution():
    assert RuntimeProfile(id="llm", name="LLM", kind="custom", settings_schema=[{
        "key": "max_tokens", "label": "Maximum output tokens", "type": "number", "default": 2048}]).settings_schema[0].default == 2048
    with pytest.raises(ValidationError):
        RuntimeProfile(id="bad", name="Bad", kind="future-tool", settings_schema=[{"key": "api_key", "label": "Key"}])
    with pytest.raises(ValidationError):
        RuntimeProfile(id="bad", name="Bad", kind="future-tool", settings_schema=[{"key": "effort", "label": "Effort", "type": "choice", "default": "unsupported", "options": ["high"]}])
    profile = LocalProfile(id="future", name="New vendor", kind="Future Agent", argv=["vendor", "--model", "{model}", "--effort", "{setting:effort}", "{prompt_file}"])
    assert profile.kind == "future-agent"
    assert CLIDriver().command(profile, "", {"effort": "high"}) == ["vendor", "--effort", "high", "{prompt_file}"]
    assert NodeConfig(profiles=[{"id": "editor", "name": "Editor", "kind": "cline", "mode": "connected"}]).profiles[0].driver == "connected"


@contextmanager
def jobs_server(mode, result=None):
    evidence = {"state": "running", "cancelled": False, "polled": threading.Event()}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def respond(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            evidence["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            evidence["authorization"] = self.headers.get("Authorization")
            evidence["idempotency"] = self.headers.get("Idempotency-Key")
            if mode.startswith("lost"):
                self.close_connection = True
                return
            self.respond({"job_id": "job_1"})
        def do_GET(self):
            evidence["polled"].set()
            if "?" in self.path:
                self.respond({"state": evidence["state"], "confirmed": evidence["cancelled"]})
            else:
                self.respond({"state": "completed" if mode == "completed" else evidence["state"], "result": result or {"summary": "Fixture completion"}})
        def do_DELETE(self):
            if mode != "lost-unsafe":
                evidence.update(state="cancelled", cancelled=True)
            self.respond({"ok": True})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", evidence
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("mode", ["completed", "running", "lost-safe", "lost-unsafe"])
def test_real_http_bridge_completion_lost_starts_and_cancellation(tmp_path, monkeypatch, mode):
    journal = tmp_path / "journal.json"
    monkeypatch.setenv("FIXTURE_API_TOKEN", "node-local-provider-fixture")
    with jobs_server(mode) as (url, evidence):
        env = {"AGENTVERSE_HTTP_CONFIG": json.dumps({"url": url, "token_env": "FIXTURE_API_TOKEN"}),
               "AGENTVERSE_ADAPTER_STATE": str(journal), "AGENTVERSE_RUNTIME_MODE": "managed_api",
               "AGENTVERSE_RUN_ID": "fixture", "AGENTVERSE_MODEL": "fixture-model", "AGENTVERSE_SETTINGS": '{"effort":"high"}'}
        command = f"{sys.executable} -m agentcommons.http_adapter {{prompt_file}}"
        if mode == "completed":
            assert execute_agent(command, "Fixture task", tmp_path, 10, env) == {"summary": "Fixture completion"}
        elif mode == "running":
            stop = threading.Event()
            def cancel_started_job():
                if evidence["polled"].wait(15):
                    stop.set()
            trigger = threading.Thread(target=cancel_started_job, daemon=True)
            trigger.start()
            with pytest.raises(WorkerStopped):
                execute_agent(command, "Fixture task", tmp_path, 20, env, stop=stop)
            trigger.join(timeout=1)
        elif mode == "lost-safe":
            with pytest.raises(RuntimeError, match="Agent exited"):
                execute_agent(command, "Fixture task", tmp_path, 10, env)
        else:
            with pytest.raises(RemoteCancellationUnconfirmed):
                execute_agent(command, "Fixture task", tmp_path, 10, env)
        state = read_state(journal)
        assert state["confirmed"] is (mode != "lost-unsafe")
        assert evidence["payload"]["settings"] == {"effort": "high"}
        assert evidence["payload"]["model"] == "fixture-model"
        assert evidence["authorization"] == "Bearer node-local-provider-fixture"
        assert evidence["idempotency"] == evidence["payload"]["request_id"]
        assert journal.stat().st_mode & 0o777 == 0o600
        if mode == "lost-unsafe":
            assert not reconcile(journal)
            evidence.update(state="cancelled", cancelled=True)
            assert reconcile(journal)
    assert not reconcile(tmp_path / "missing.json")


def test_connected_only_and_broken_plugin_do_not_need_a_git_clone(monkeypatch):
    monkeypatch.setattr("agentcommons.node.drivers", lambda: __import__("agentcommons.drivers", fromlist=["drivers"]).drivers())
    service = NodeService("http://127.0.0.1:1", "fixture", NodeConfig(profiles=[
        {"id": "editor", "name": "Cline editor", "kind": "cline", "mode": "connected"},
        {"id": "future", "name": "Future adapter", "kind": "future", "driver": "not-installed"},
    ]))
    try:
        report = service.inspect()
        assert report["profiles"][0]["availability"] == "available"
        assert report["profiles"][1]["availability"] == "needs_setup"
        assert "argv" not in json.dumps(report)
    finally:
        service.http.close()


def test_node_managed_api_and_connected_editor_complete_a_real_planning_task(live_server, tmp_path):
    url, client = live_server
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "Initial"], cwd=repo, check=True, capture_output=True)
    p = project(client, auto_plan=True)
    a, _, _ = agent(client, p, "API planner")
    n, _, token = node(client, p, register=False)
    with jobs_server("completed", {"summary": "Fixture plan", "tasks": [{"title": "Implement the planned feature"}]}) as (endpoint, evidence):
        service = NodeService(url, token, NodeConfig(repo=str(repo), log_dir=str(tmp_path / "logs"), profiles=[
            {"id": "api", "name": "API bridge", "kind": "custom", "driver": "http", "http": {"url": endpoint}, "push": False},
            {"id": "editor", "name": "Cline", "kind": "cline", "mode": "connected"},
        ]))
        try:
            assert all(p["availability"] == "available" for p in service.register()["node"]["profiles"])
            path = f"/api/projects/{p}/agents/{a}"
            assert client.put(f"{path}/runtime", json={"node_id": n, "profile_id": "api"}).status_code == 200
            assert client.post(f"{path}/launch").status_code == 200
            service.step()
            deadline = time.monotonic() + 15
            while client.get(f"/api/projects/{p}/tasks").json()[0]["status"] != "done":
                assert time.monotonic() < deadline
                service.step()
                time.sleep(.1)
            assert "Create a bounded, ordered implementation plan" in evidence["payload"]["prompt"]
            assert client.post(f"{path}/stop").status_code == 200
            service.step()
            assert client.get(f"/api/projects/{p}/snapshot").json()["agents"][0]["runtime"]["state"] == "stopped"
        finally:
            service.shutdown()


def test_inventory_hot_reload_retains_good_config_and_reports_bad_edits(live_server, tmp_path):
    url, client = live_server
    p = project(client)
    n, _, token = node(client, p, register=False)
    path = tmp_path / "node.json"
    data = {"log_dir": str(tmp_path / "logs"), "profiles": [{"id": "editor", "name": "Editor", "kind": "cline", "mode": "connected"}]}
    path.write_text(json.dumps(data))
    service = NodeService(url, token, NodeConfig(**data), config_path=path)
    try:
        service.register()
        data["profiles"].append({"id": "future", "name": "Future app", "kind": "future", "mode": "connected"})
        path.write_text(json.dumps(data))
        service.refresh()
        assert len(client.get(f"/api/projects/{p}/nodes").json()[0]["profiles"]) == 2
        path.write_text("incomplete edit")
        service.refresh()
        saved = client.get(f"/api/projects/{p}/nodes").json()[0]
        assert saved["id"] == n and len(saved["profiles"]) == 2
        assert any(d["code"] == "config.pending" for d in saved["diagnostics"])
        path.unlink()
        service.refresh()
        assert "unavailable" in service.config_warning
    finally:
        service.shutdown()


def test_new_sdk_namespace_connection_and_context_cleanup(live_server):
    from agentverse import Client
    url, client = live_server
    p = project(client)
    _, _, token = agent(client, p, "SDK peer")
    with Client(url, token) as peer:
        assert peer.connect(capabilities=["review"])["agent"]["project_id"] == p
        assert len(peer.teammates(p, "review")) == 1
        assert peer.request_help(p, "Review this contract", "review")["state"] == "open"
    assert peer.http.is_closed


def test_baseline_schema_migration_preserves_tokens_tasks_and_runtime(tmp_path):
    from agentcommons.models import AgentCreate, NodeCreate, NodeRegister, ProjectCreate, RuntimeConfig, TaskCreate
    from agentcommons.store import Store
    from conftest import TOKEN
    from test_remote_control import PROFILES
    path = str(tmp_path / "baseline.db")
    old = Store(path, TOKEN)
    admin = old.authenticate(f"Bearer {TOKEN}")
    p = old.create_project(admin, ProjectCreate(name="Existing", goal="Preserve this workspace", auto_plan=False))["id"]
    peer = old.add_agent(admin, p, AgentCreate(name="Existing peer"))
    task = old.create_task(admin, p, TaskCreate(title="Existing task"))
    n = old.runtimes.add_node(admin, p, NodeCreate(name="Existing VPS"))
    identity = old.runtimes.authenticate_node(f"Bearer {n['token']}")
    old.runtimes.register(identity, NodeRegister(session_id=SESSION, profiles=PROFILES))
    old.runtimes.configure(admin, p, peer["agent"]["id"], RuntimeConfig(node_id=n["node"]["id"], profile_id="test-peer", model="provider/deep"))
    for table, columns in {"agents": ["description", "limitations", "profile_version", "session_info"], "tasks": ["required_capabilities"],
                           "nodes": ["diagnostics", "capacity", "protocol_version"], "agent_runtimes": ["settings", "mode"]}.items():
        for column in columns:
            old.db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    old.db.execute("DROP TABLE help_requests")
    old.db.execute("DROP TABLE agent_issues")
    # Baseline catalogs lacked mode/health/settings fields.
    old.db.execute("UPDATE nodes SET profiles=?", (json.dumps(PROFILES),))
    old.close()
    updated = Store(path, TOKEN)
    try:
        assert updated.authenticate(f"Bearer {peer['token']}").agent_id == peer["agent"]["id"]
        assert updated.runtimes.authenticate_node(f"Bearer {n['token']}")["id"] == n["node"]["id"]
        snap = updated.snapshot(admin, p)
        assert snap["tasks"][0]["id"] == task["id"] and snap["tasks"][0]["required_capabilities"] == []
        assert snap["agents"][0]["runtime"]["model"] == "provider/deep"
        assert snap["agents"][0]["runtime"]["settings"] == {}
        assert snap["nodes"][0]["profiles"][0]["mode"] == "managed_cli"
        assert snap["help_requests"] == [] and snap["issues"] == []
    finally:
        updated.close()


@pytest.mark.parametrize("data", [1, [], "invalid", {"confirmed": False, "connector": []}])
def test_malformed_api_journals_cannot_release_claims_or_crash_a_node(tmp_path, data):
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(data))
    assert not reconcile(path)


def test_api_reconciliation_is_parallel_so_bad_endpoints_do_not_starve_node_leases(tmp_path, monkeypatch):
    service = NodeService("http://127.0.0.1:1", "fixture", NodeConfig(log_dir=str(tmp_path), profiles=[{
        "id": "editor", "name": "Editor", "kind": "custom", "mode": "connected"}]))
    rows = [{"agent_id": f"peer_{i}", "run_id": f"run_{i}", "state": "unconfirmed", "desired_state": "stopped"} for i in range(4)]
    reports = []
    barrier = threading.Barrier(4)
    def reconcile_in_parallel(_):
        barrier.wait(timeout=3)
        return True
    def request(route, payload):
        if route == "report":
            reports.append(payload)
        return {"runtimes": rows}
    monkeypatch.setattr("agentcommons.node.reconcile", reconcile_in_parallel)
    monkeypatch.setattr(service, "request", request)
    try:
        service.step()
        assert len(reports) == 4 and all(row["state"] == "stopped" for row in reports)
    finally:
        service.http.close()
