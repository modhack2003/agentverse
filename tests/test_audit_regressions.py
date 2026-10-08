"""Regression checks for the round-three lifecycle and coordination findings."""

import asyncio
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from agentcommons.drivers import CLIDriver
from agentcommons.models import validate_settings
from agentcommons.node import Child, LocalProfile, NodeConfig, NodeService
from agentcommons.worker import WorkerStopped, execute_agent
from conftest import agent, project
from test_remote_control import SESSION, configure, node


def start_runtime(client, project_id, agent_id):
    node_id, headers, _ = node(client, project_id)
    configure(client, project_id, agent_id, node_id)
    base = f"/api/projects/{project_id}/agents/{agent_id}"
    assert client.post(base + "/launch").status_code == 200
    row = client.post("/api/nodes/me/poll", headers=headers, json={"session_id": SESSION}).json()["runtimes"][0]
    managed = {"Authorization": f"Bearer {row['token']}"}
    return node_id, headers, base, row, managed


def test_managed_review_release_waits_for_terminal_report(api):
    client, _ = api
    p = project(client)
    reviewer, _, _ = agent(client, p, "Managed reviewer")
    _, author, _ = agent(client, p, "Author")
    _, replacement, _ = agent(client, p, "Replacement")
    _, nh, _, row, mh = start_runtime(client, p, reviewer)
    task = client.post(f"/api/projects/{p}/tasks", json={"title": "Review lifecycle"}).json()
    path = f"/api/projects/{p}/tasks/{task['id']}"
    assert client.post(path + "/claim", headers=author).status_code == 200
    assert client.post(path + "/submit", headers=author, json={"summary": "Code", "branch": "feature", "commit_sha": "a" * 40}).status_code == 200
    assert client.post(path + "/review-claim", headers=mh).status_code == 200
    assert client.post(path + "/review-release").status_code == 409
    assert client.post(path + "/review-claim", headers=replacement).status_code == 409
    # The worker can release its own completed invocation without stopping the idle supervisor.
    assert client.post(path + "/review-release", headers=mh).status_code == 200
    assert client.post(path + "/review-claim", headers=mh).status_code == 200
    report = {"session_id": SESSION, "agent_id": reviewer, "run_id": row["run_id"], "state": "stopped"}
    assert client.post("/api/nodes/me/report", headers=nh, json=report).status_code == 200
    assert client.post(path + "/review-claim", headers=replacement).status_code == 200


@pytest.mark.parametrize("legacy_contract", [False, True])
def test_inventory_mode_is_snapshotted_and_api_takeover_holds_claims(api, legacy_contract):
    client, store = api
    p = project(client)
    a, _, _ = agent(client, p, "API executor")
    n, nh, _ = node(client, p)
    configure(client, p, a, n)
    profile = {"id": "test-peer", "name": "API", "kind": "custom", "mode": "managed_api", "driver": "http"}
    inventory = {"session_id": SESSION, "profiles": [profile]}
    assert client.post("/api/nodes/me/inventory", headers=nh, json=inventory).status_code == 200
    # Change the selected model to the one advertised by the replacement profile.
    base = f"/api/projects/{p}/agents/{a}"
    store.db.execute("UPDATE agent_runtimes SET model='' WHERE agent_id=?", (a,))
    launched = client.post(base + "/launch")
    assert launched.status_code == 200, launched.text
    assert launched.json()["mode"] == "managed_api"
    assert launched.json()["run_contract"]["driver"] == "http"
    row = client.post("/api/nodes/me/poll", headers=nh, json={"session_id": SESSION}).json()["runtimes"][0]
    mh = {"Authorization": f"Bearer {row['token']}"}
    task = client.post(f"/api/projects/{p}/tasks", json={"title": "Remote claim"}).json()
    assert client.post(f"/api/projects/{p}/tasks/{task['id']}/claim", headers=mh).status_code == 200
    changed = {**profile, "mode": "managed_cli", "driver": "cli"}
    assert client.post("/api/nodes/me/inventory", headers=nh, json={**inventory, "profiles": [changed]}).status_code == 409
    if legacy_contract:
        store.db.execute("UPDATE agent_runtimes SET mode='managed_cli',run_contract='{}' WHERE agent_id=?", (a,))
    store.db.execute("UPDATE nodes SET last_seen=? WHERE id=?", (time.time() - 91, n))
    assert client.post("/api/nodes/me/register", headers=nh, json={**inventory, "session_id": "f" * 32}).status_code == 200
    snapshot = client.get(f"/api/projects/{p}/snapshot").json()
    assert snapshot["agents"][0]["runtime"]["state"] == "unconfirmed"
    assert snapshot["tasks"][0]["status"] == "in_progress"
    assert client.post(f"/api/projects/{p}/tasks/{task['id']}/release", json={}).status_code == 409


def child_wrapper(tmp_path, completed=False):
    heartbeat = tmp_path / "heartbeat"
    pid_file = tmp_path / "child.pid"
    child = (
        "import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f"while True:\n pathlib.Path({str(heartbeat)!r}).write_text(str(time.time()))\n time.sleep(.02)"
    )
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import subprocess,sys,pathlib,time\n"
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        "time.sleep(.25)\n" + ("print('{\"summary\":\"done\"}')\n" if completed else "time.sleep(60)\n")
    )
    return wrapper, heartbeat, pid_file


def assert_heartbeat_stopped(heartbeat):
    before = heartbeat.read_text()
    time.sleep(.15)
    assert heartbeat.read_text() == before


def kill_leftover(pid_file):
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize("ending", ["success", "timeout", "stop"])
def test_command_cleanup_escalates_ignoring_descendants(tmp_path, ending):
    wrapper, heartbeat, pid_file = child_wrapper(tmp_path, ending == "success")
    stop = threading.Event()
    timer = threading.Timer(.7, stop.set)
    if ending == "stop":
        timer.start()
    try:
        command = shlex.join([sys.executable, str(wrapper)])
        if ending == "success":
            assert execute_agent(command, "regression", tmp_path, 3)["summary"] == "done"
        else:
            with pytest.raises(WorkerStopped if ending == "stop" else subprocess.TimeoutExpired):
                execute_agent(command, "regression", tmp_path, 1, stop=stop)
        assert_heartbeat_stopped(heartbeat)
    finally:
        timer.cancel()
        kill_leftover(pid_file)


@pytest.mark.parametrize("ending", ["terminate", "observed_exit"])
def test_supervisor_cleanup_escalates_ignoring_descendants(tmp_path, monkeypatch, ending):
    wrapper, heartbeat, pid_file = child_wrapper(tmp_path, ending == "observed_exit")
    log = (tmp_path / "worker.log").open("w")
    process = subprocess.Popen([sys.executable, str(wrapper)], start_new_session=True, stdout=log)
    child = Child("run_" + "a" * 32, process, log)
    service = NodeService("http://127.0.0.1:1", "fixture", NodeConfig(profiles=[{
        "id": "connected", "name": "Connected", "kind": "custom", "mode": "connected"
    }]))
    try:
        deadline = time.monotonic() + 3
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert heartbeat.exists()
        if ending == "terminate":
            service.terminate(child)
        else:
            process.wait(timeout=3)
            service.children["fixture"] = child
            row = {"agent_id": "fixture", "run_id": child.run_id, "desired_state": "running", "state": "running"}
            monkeypatch.setattr(service, "request", lambda *_: {"runtimes": [row]})
            monkeypatch.setattr(service, "flush_reports", lambda: None)
            service.step()
            assert "fixture" not in service.children
        assert_heartbeat_stopped(heartbeat)
    finally:
        kill_leftover(pid_file)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        log.close()
        service.http.close()


def test_agent_command_strips_coordinator_credentials_and_cannot_reload_dotenv(tmp_path, monkeypatch):
    for prefix in ("AGENTVERSE", "AGENTCOMMONS"):
        for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_TOKEN", "NODE_TOKEN"):
            monkeypatch.setenv(f"{prefix}_{name}", "synthetic-secret")
    monkeypatch.setenv("PROVIDER_API_KEY", "intentionally-needed")
    (tmp_path / ".env").write_text("AGENTVERSE_ADMIN_PASSWORD=dotenv-secret\n")
    script = tmp_path / "environment.py"
    script.write_text(
        "import os,json\nfrom dotenv import load_dotenv\nload_dotenv()\n"
        "print(json.dumps({k:os.getenv(k) for k in ['AGENTVERSE_ADMIN_USERNAME','AGENTVERSE_ADMIN_PASSWORD',"
        "'AGENTVERSE_ADMIN_TOKEN','AGENTVERSE_NODE_TOKEN','AGENTCOMMONS_ADMIN_USERNAME','AGENTCOMMONS_ADMIN_PASSWORD',"
        "'AGENTCOMMONS_ADMIN_TOKEN','AGENTCOMMONS_NODE_TOKEN','PROVIDER_API_KEY']}))\n"
    )
    result = execute_agent(shlex.join([sys.executable, str(script)]), "regression", tmp_path, 5)
    assert result.pop("PROVIDER_API_KEY") == "intentionally-needed"
    assert all(value is None for value in result.values())


def test_required_settings_validate_selected_values_and_every_placeholder(api, tmp_path):
    profile = LocalProfile(id="required", name="Required", kind="custom", push=False, argv=[
        sys.executable, "{setting:effort}/{setting:budget}"
    ], settings_schema=[
        {"key": "effort", "label": "Effort", "type": "choice", "options": ["low", "high"]},
        {"key": "budget", "label": "Budget", "type": "number"}
    ])
    assert CLIDriver().check(profile)[0] == "available"
    assert CLIDriver().command(profile, "", {"effort": "high", "budget": 2}) == [sys.executable, "high/2"]
    profile.argv.append("{setting:unknown}")
    assert CLIDriver().check(profile)[0] == "needs_setup"
    profile.argv.pop()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "Initial"], cwd=repo, check=True, capture_output=True)
    service = NodeService("http://127.0.0.1:1", "fixture", NodeConfig(repo=str(repo), profiles=[profile]))
    try:
        public = service.inspect()["profiles"][0]
        assert public["availability"] == "available"
        assert public["required_settings"] == ["budget", "effort"]
        with pytest.raises(ValueError, match="Budget"):
            validate_settings(public, {"effort": "high"}, require=True)
        client, _ = api
        p = project(client)
        a, _, _ = agent(client, p, "Required settings")
        n, nh, _ = node(client, p, register=False)
        assert client.post("/api/nodes/me/register", headers=nh, json={"session_id": SESSION, "profiles": [public]}).status_code == 200
        path = f"/api/projects/{p}/agents/{a}"
        config = {"node_id": n, "profile_id": profile.id, "settings": {"effort": "high"}}
        assert client.put(path + "/runtime", json=config).status_code == 422
        config["settings"]["budget"] = 2
        assert client.put(path + "/runtime", json=config).status_code == 200
        assert client.post(path + "/launch").status_code == 200
    finally:
        service.http.close()


@pytest.mark.parametrize("base", ["main", "master"])
def test_git_prerequisites_disable_managed_profiles(tmp_path, base):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "Initial"], cwd=repo, check=True, capture_output=True)
    service = NodeService("http://127.0.0.1:1", "fixture", NodeConfig(repo=str(repo), profiles=[{
        "id": "cli", "name": "CLI", "kind": "custom", "argv": [sys.executable], "base": base
    }, {"id": "editor", "name": "Editor", "kind": "custom", "mode": "connected"}]))
    try:
        report = service.inspect()
        assert report["profiles"][0]["availability"] == "needs_setup"
        assert report["diagnostics"][0]["severity"] == "warning"
        assert report["profiles"][1]["availability"] == "available"
    finally:
        service.http.close()


def test_revoked_websocket_close_tolerates_client_disconnect(api):
    client, _ = api
    p = project(client)
    a, headers, _ = agent(client, p, "Revoked peer")
    ticket = client.post(f"/api/realtime-ticket?project_id={p}", headers=headers).json()["ticket"]
    assert client.delete(f"/api/projects/{p}/agents/{a}").status_code == 200
    endpoint = next(route.endpoint for route in client.app.routes if getattr(route, "path", None) == "/api/live")
    class DisconnectedSocket:
        async def accept(self):
            pass

        async def close(self, code):
            raise WebSocketDisconnect(1006)
    asyncio.run(endpoint(DisconnectedSocket(), ticket))
