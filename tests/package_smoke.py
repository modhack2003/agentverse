"""Test the installer and complete package outside the source checkout, without Node/Git."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def verify(wheel):
    repo = Path(__file__).resolve().parents[1]
    package = wheel if wheel.startswith("https://") else str(Path(wheel).resolve())
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AGENTVERSE_", "AGENTCOMMONS_"))
           and key not in {"PYTHONPATH", "VIRTUAL_ENV", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                           "http_proxy", "https_proxy", "all_proxy"}}
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="agentverse-package-") as temporary:
        cwd = Path(temporary)
        home = (cwd / "installation with spaces ü").resolve()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        installer = repo / "install.py"
        archive_prefix = "https://github.com/modhack2003/agentverse/archive/"
        if package.startswith(archive_prefix):
            revision = package.removeprefix(archive_prefix).removesuffix(".zip")
            raw_url = f"https://raw.githubusercontent.com/modhack2003/agentverse/{revision}/install.py"
            with urllib.request.urlopen(raw_url, timeout=30) as response:
                content = response.read()
            assert content == installer.read_bytes(), "Downloaded installer differs from the tested checkout"
            installer = cwd / "downloaded-install.py"
            installer.write_bytes(content)
        install = [sys.executable, str(installer), "--source", str(package),
                   "--home", str(home), "--port", str(port), "--no-start"]
        result = subprocess.run(install, cwd=cwd, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        config = json.loads((home / "config.json").read_text())
        python = Path(json.loads((home / "installation.json").read_text())["python"])
        env["PATH"] = str(python.parent)  # No Node.js, npm, Git, uv, or source checkout on PATH.
        launcher = home / ("agentverse.cmd" if os.name == "nt" else "agentverse")
        launcher_command = [str(launcher), 'status']
        if os.name == 'nt':
            launcher_command = [str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/cmd.exe'), '/c', *launcher_command]
        launcher_status = json.loads(subprocess.check_output(launcher_command, cwd=cwd, env=env, text=True, encoding='utf-8'))
        assert launcher_status['configured'] and launcher_status['home'] == str(home), launcher_status
        if os.name == 'nt':
            powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            output = subprocess.check_output([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                              str(home / 'agentverse.ps1'), 'status'], cwd=cwd, env=env, text=True, encoding='utf-8')
            assert json.loads(output)['home'] == str(home)
        installed = subprocess.check_output([str(python), "-c",
            "import agentverse, agentcommons; print(agentverse.__version__); print(agentcommons.__file__)"],
            cwd=cwd, env=env, text=True)
        assert installed.startswith("0.4.1\n") and str(repo) not in installed, installed
        for alias in ("agentverse", "agentcommons"):
            executable = python.parent / (alias + (".exe" if os.name == "nt" else ""))
            subprocess.run([str(executable), "--help"], cwd=cwd, env=env, check=True, capture_output=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{port}"

        def request(path, data=None, token=None):
            headers = {"Authorization": "Bearer " + (token or config["admin_token"]),
                       "Accept": "application/json, text/event-stream"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode() if data is not None else None
            with opener.open(urllib.request.Request(base + path, data=body, headers=headers), timeout=5) as response:
                return json.loads(response.read())

        project_id = None
        for run in range(2):
            with (cwd / "server.log").open("w") as log:
                command = [str(python), "-m", "agentcommons.cli", "setup" if run == 0 else "serve",
                           "--home", str(home)]
                if run == 0:
                    command.append("--no-browser")
                server = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            assert request("/api/health")["version"] == "0.4.1"
                            break
                        except OSError:
                            assert server.poll() is None, (cwd / "server.log").read_text()
                            assert time.monotonic() < deadline, "Packaged server startup timed out"
                            time.sleep(0.1)
                    with opener.open(base, timeout=5) as response:
                        html = response.read().decode()
                        assert "AgentVerse" in html
                    assets = re.findall(r'(?:src|href)="(/(?:assets/[^"\s]+|favicon\.svg))"', html)
                    assert len(assets) >= 3, html
                    for asset in assets:
                        with opener.open(base + asset, timeout=5) as response:
                            assert response.status == 200 and len(response.read()) > 100
                    assert request("/api/me")["admin"] is True
                    try:
                        request("/api/me", token="invalid")
                        raise AssertionError("Invalid token was accepted")
                    except urllib.error.HTTPError as exc:
                        assert exc.code == 401
                    if run == 0:
                        project_id = request("/api/projects", {"name": "Fresh package", "goal": "One package works",
                                                               "auto_plan": False})["id"]
                        task = request(f"/api/projects/{project_id}/tasks", {"title": "Installed workflow"})
                        assert task["title"] == "Installed workflow"
                        peer = request(f"/api/projects/{project_id}/agents", {"name": "Package peer", "kind": "custom"})
                        mcp = request("/mcp/", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                            "protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "package-check", "version": "1"}}}, peer["token"])
                        assert mcp["result"]["serverInfo"]["name"] == "AgentVerse"
                    else:
                        assert request("/api/projects")[0]["id"] == project_id
                        assert request(f"/api/projects/{project_id}/tasks")[0]["title"] == "Installed workflow"
                finally:
                    if server.poll() is None:
                        server.send_signal(signal.SIGINT if os.name != "nt" else signal.SIGTERM)
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
            subprocess.run([str(python), "-m", "agentcommons.cli", "setup", "--home", str(home), "--no-start"],
                           cwd=cwd, env=env, check=True, capture_output=True)
            assert json.loads((home / "config.json").read_text()) == config
            if run == 0:
                result = subprocess.run(install, cwd=cwd, env=env, text=True, capture_output=True)
                assert result.returncode == 0, result.stdout + result.stderr
                failed = list(install)
                failed[failed.index("--source") + 1] = str(cwd / "missing-package.whl")
                result = subprocess.run(failed, cwd=cwd, env=env, text=True, capture_output=True)
                assert result.returncode != 0 and "did not complete" in result.stderr
                assert json.loads((home / "config.json").read_text()) == config
        print("PASS: isolated installer, packaged dashboard/assets, SDK/CLI aliases, authentication, project/task/peer/MCP, "
              "setup/installer reruns, failed-install recovery and restart persistence; no Node/npm/Git/uv on runtime PATH")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", "--package", dest="wheel", required=True)
    verify(parser.parse_args().wheel)
