import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, TabbedContent, TextArea

from agentcommons.tui import CommonsTUI, FormScreen
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
                assets = Path(__file__).parents[1] / "docs/assets"
                app.save_screenshot("terminal.svg", path=str(assets))
                image = assets / "terminal.svg"
                image.write_text("\n".join(line.rstrip() for line in image.read_text().splitlines()) + "\n")
            app.query_one("#chat-input", Input).value = "A handoff from the terminal"
            await app.send()
            await pilot.pause(0.3)
            assert client.get(f"/api/projects/{p}/messages").json()[0]["content"] == "A handoff from the terminal"
        await app.http.aclose()

    asyncio.run(pilot_test())


def test_tui_paginates_history_and_restores_conflicted_memory_draft(live_server):
    url, client = live_server
    p = project(client)
    for index in range(105):
        response = client.post(f"/api/projects/{p}/messages", json={"content": f"terminal history {index}"})
        assert response.status_code == 201
        response = client.post(f"/api/projects/{p}/help", json={"question": f"help request {index}"})
        assert response.status_code == 200

    async def pilot_test():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(130, 45)) as pilot:
            await pilot.pause(1)
            assert len(app.chat_messages) == 100
            assert len(app.help_requests) == 100
            assert not app.query_one("#older-chat").disabled
            assert not app.query_one("#older-help").disabled

            await app.load_older_chat()
            await app.load_older_help()
            await pilot.pause(.5)
            assert len(app.chat_messages) == 200
            assert len(app.help_requests) == 105
            assert not app.query_one("#older-chat").disabled
            assert app.query_one("#older-help").disabled
            await app.load_older_chat()
            await pilot.pause(.3)
            assert len(app.chat_messages) == 210
            assert app.query_one("#older-chat").disabled

            memory = client.post(f"/api/projects/{p}/memories", json={
                "title": "Draft memory", "content": "Original", "tags": []}).json()
            assert client.put(f"/api/projects/{p}/memories/{memory['id']}", json={
                "title": "Server edit", "content": "Server edit", "tags": [], "expected_version": 1}).status_code == 200
            app.form("Update shared memory", [
                ("title", "Title", False, "Draft title"),
                ("content", "Shared knowledge", True, "Draft content"),
                ("tags", "Tags", False, "terminal")],
                f"/api/projects/{p}/memories/{memory['id']}", "PUT", {"expected_version": 1})
            await pilot.pause(.2)
            app.screen.query_one("#field-title").value = "My preserved title"
            app.screen.query_one("#field-content").text = "My preserved content"
            await pilot.click("#save")
            await pilot.pause(.5)
            assert isinstance(app.screen, FormScreen)
            assert app.screen.query_one("#field-title").value == "My preserved title"
            assert app.screen.query_one("#field-content").text == "My preserved content"
        await app.http.aclose()

    asyncio.run(pilot_test())


def test_agent_result_requires_structured_output():
    assert result_json('some prose\n```agentcommons\n{"summary":"done"}\n```')["summary"] == "done"
    with pytest.raises(RuntimeError):
        result_json("I might have finished it.")


def test_tui_runtime_profile_launch_stop_and_peer_help(live_server):
    from test_remote_control import node
    url, client = live_server
    p = project(client)
    a, _, _ = agent(client, p, "Terminal managed peer")
    node(client, p)
    async def pilot_test():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = "agents-tab"
            app.query_one("#agents", DataTable).focus()
            await pilot.press("e")
            await pilot.pause(.2)
            app.screen.query_one("#field-capabilities", Input).value = "python, review"
            await pilot.click("#save")
            await pilot.pause(.5)
            app.query_one("#agents", DataTable).focus()
            await pilot.press("c")
            await pilot.pause(.2)
            await pilot.click("#save")
            await pilot.pause(.5)
            app.query_one("#agents", DataTable).focus()
            await pilot.press("l")
            await pilot.pause(.3)
            assert client.get(f"/api/projects/{p}/snapshot").json()["agents"][0]["runtime"]["state"] == "queued"
            await pilot.press("s")
            await pilot.pause(.3)
            assert client.get(f"/api/projects/{p}/snapshot").json()["agents"][0]["runtime"]["state"] == "stopped"
            await pilot.press("h")
            await pilot.pause(.2)
            app.screen.query_one("#field-capability", Input).value = "review"
            app.screen.query_one("#field-question", TextArea).text = "Check this terminal workflow"
            await pilot.click("#save")
            await pilot.pause(.3)
            snap = client.get(f"/api/projects/{p}/snapshot").json()
            assert snap["agents"][0]["id"] == a and snap["agents"][0]["configured_capabilities"] == ["python", "review"]
            assert snap["help_requests"][0]["recipient_id"] == a
        await app.http.aclose()
    asyncio.run(pilot_test())
