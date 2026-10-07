"""Verify the installed production image and persistent data across both environment prefixes."""

import argparse
import json
import subprocess
import time
import uuid
from urllib.request import Request, urlopen

TOKEN = "container-test-only-admin-token-not-a-secret"


def docker(*args):
    return subprocess.run(["docker", *args], check=True, text=True, capture_output=True).stdout.strip()


def request(base, path, data=None, token=TOKEN):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    with urlopen(Request(base + path, data=body, headers=headers), timeout=5) as response:
        return json.loads(response.read())


def verify(image):
    name = "agentverse-check-" + uuid.uuid4().hex[:12]
    volume = name + "-data"
    docker("volume", "create", volume)
    project_id, peer_token = None, None
    try:
        for prefix in ("AGENTVERSE", "AGENTCOMMONS"):
            try:
                docker("run", "-d", "--name", name, "-e", f"{prefix}_ADMIN_TOKEN={TOKEN}",
                       "-p", "127.0.0.1::8000", "-v", f"{volume}:/data", image)
                base = "http://" + docker("port", name, "8000/tcp")
                deadline = time.monotonic() + 30
                while True:
                    try:
                        health = request(base, "/api/health")
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError("Production container did not become ready: " + docker("logs", name))
                        time.sleep(.2)
                assert health == {"status": "ok", "version": "0.2.0", "product": "AgentVerse"}
                assert request(base, "/api/protocol")["connection_modes"] == ["managed_cli", "managed_api", "connected"]
                assert docker("exec", name, "id", "-u") == "10001"
                docker("exec", name, "python", "-c", "from agentverse import Client, __version__; assert __version__ == '0.2.0'")
                docker("exec", name, "agentverse", "--help")
                docker("exec", name, "agentcommons", "--help")
                with urlopen(base, timeout=5) as response:
                    html = response.read().decode()
                    assert "AgentVerse" in html and "/assets/index-" in html
                if project_id is None:
                    project_id = request(base, "/api/projects", {"name": "Container workspace", "goal": "Verify the production image", "auto_plan": False})["id"]
                    peer = request(base, f"/api/projects/{project_id}/agents", {"name": "Container peer", "kind": "future-tool", "capabilities": ["review"]})
                    peer_token = peer["token"]
                else:
                    assert request(base, "/api/projects")[0]["id"] == project_id
                    assert request(base, "/api/me", token=peer_token)["project_id"] == project_id
                mcp = request(base, "/mcp/", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "container-check", "version": "1"}}}, peer_token)
                assert mcp["result"]["serverInfo"]["name"] == "AgentVerse"
                print(f"PASS {prefix}: production frontend, protocol, installed SDK/CLIs, MCP, non-root user, persistent workspace/tokens")
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    finally:
        docker("volume", "rm", volume)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    verify(parser.parse_args().image)
