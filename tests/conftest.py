import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from agentcommons.server import create_app

TOKEN = "test-only-admin-token-long-enough"


@pytest.fixture
def api(tmp_path):
    app = create_app(str(tmp_path / "commons.db"), TOKEN, web_dir=str(tmp_path / "no-web"))
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, app.state.store


@pytest.fixture
def live_server(tmp_path):
    app = create_app(str(tmp_path / "live.db"), TOKEN, web_dir=str(tmp_path / "no-web"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Test server did not start")
        time.sleep(0.01)
    url = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield url, client
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()


def project(client, name="Orbital", auto_plan=False):
    response = client.post("/api/projects", json={"name": name, "goal": "Build a beautiful collaborative app.", "auto_plan": auto_plan})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def agent(client, project_id, name):
    response = client.post(f"/api/projects/{project_id}/agents", json={"name": name, "kind": "custom"})
    assert response.status_code == 201, response.text
    data = response.json()
    return data["agent"]["id"], {"Authorization": f"Bearer {data['token']}"}, data["token"]
