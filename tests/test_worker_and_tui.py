import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from textual.widgets import DataTable, Input

from agentcommons.tui import CommonsTUI
from agentcommons.worker import Worker, result_json
from conftest import TOKEN, agent, project


def test_two_remote_workers_plan_code_review_and_merge(live_server, tmp_path, monkeypatch):
    url, client = live_server
    for key, value in {"GIT_AUTHOR_NAME": "Test peer", "GIT_COMMITTER_NAME": "Test peer",
                       "GIT_AUTHOR_EMAIL": "peer@example.test", "GIT_COMMITTER_EMAIL": "peer@example.test"}.items():
        monkeypatch.setenv(key, value)
    origin, repo_a, repo_b = (tmp_path / name for name in ("origin.git", "node-a", "node-b"))

    def git(*args, cwd=None):
        return subprocess.run(["git", *map(str, args)], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

    git("init", "--bare", "--initial-branch=main", origin)
    git("clone", origin, repo_a)
    (repo_a / "README.md").write_text("Remote collaboration fixture\n")
    git("add", "README.md", cwd=repo_a)
    git("commit", "-m", "Initialize project", cwd=repo_a)
    git("push", "origin", "main", cwd=repo_a)
    git("clone", origin, repo_b)
    p = project(client, auto_plan=True)
    _, _, token_a = agent(client, p, "Remote planner / coder")
    _, _, token_b = agent(client, p, "Remote reviewer")
    script = Path(__file__).parent / "fixtures/peer_cli.py"
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{prompt_file}}"
    Worker(url, token_a, repo_a, command).run(once=True)
    Worker(url, token_a, repo_a, command).run(once=True)
    snap = client.get(f"/api/projects/{p}/snapshot").json()
    assert [t["status"] for t in snap["tasks"]] == ["done", "review"]
    assert snap["memories"][0]["title"] == "Feature handoff"
    Worker(url, token_b, repo_b, command).run(once=True)
    snap = client.get(f"/api/projects/{p}/snapshot").json()
    assert all(t["status"] == "done" for t in snap["tasks"])
    assert snap["tasks"][1]["integration_sha"]
    assert snap["reviews"][0]["decision"] == "approve"
    assert git("show", "main:feature.txt", cwd=origin) == "Built by an independent remote teammate."
    assert git("status", "--porcelain", cwd=repo_a) == ""
    assert git("status", "--porcelain", cwd=repo_b) == ""


def test_tui_loads_remote_data_and_sends_chat(live_server):
    url, client = live_server
    p = project(client)
    agent(client, p, "Terminal teammate")
    client.post(f"/api/projects/{p}/tasks", json={"title": "Visible terminal task"})

    async def pilot_test():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(130, 45)) as pilot:
            await pilot.pause(1)
            assert app.query_one("#tasks", DataTable).row_count == 1
            assert app.query_one("#agents", DataTable).row_count == 1
            if os.getenv("UPDATE_TUI_SCREENSHOT"):
                app.save_screenshot("terminal.svg", path=str(Path(__file__).parents[1] / "docs/assets"))
            app.query_one("#chat-input", Input).value = "A handoff from the terminal"
            await app.send()
            await pilot.pause(0.3)
            assert client.get(f"/api/projects/{p}/messages").json()[0]["content"] == "A handoff from the terminal"
        await app.http.aclose()

    asyncio.run(pilot_test())


def test_agent_result_requires_structured_output():
    assert result_json('some prose\n```agentcommons\n{"summary":"done"}\n```')["summary"] == "done"
    with pytest.raises(RuntimeError):
        result_json("I might have finished it.")
