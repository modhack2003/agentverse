"""Regression checks for terminal history and failed saves."""

import asyncio

import pytest
from conftest import TOKEN, agent, project


@pytest.mark.parametrize("initial_count", [0, 5, 105])
@pytest.mark.parametrize("target", ["general", "engineering", "private"])
def test_terminal_refresh_bridges_a_multi_page_gap(live_server, target, initial_count):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Button, Select

    url, c = live_server
    p = project(c)
    a, ah, _ = agent(c, p, "Gap peer")

    def post(content):
        body = {"content": content, "channel": target if target != "private" else "general"}
        if target == "private":
            body["recipient_id"] = "human"
        assert c.post(f"/api/projects/{p}/messages", headers=ah, json=body).status_code == 201

    for i in range(initial_count):
        post(f"Before gap {i}")

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one("#chat-target", Select).value = a if target == "private" else "#" + target
            await pilot.pause(0.5)
            assert len(app.chat_messages) == min(initial_count, 100)
            for i in range(205):
                post(f"Inside gap {i}")
            app.refresh_remote()
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            contents = [r["content"] for r in app.chat_messages]
            for _ in range(4):
                if app.query_one("#older-chat", Button).disabled:
                    break
                await app.load_older_chat()
                await app.workers.wait_for_complete()
                await pilot.pause(0.1)
            assert app.query_one("#older-chat", Button).disabled
            contents = [r["content"] for r in app.chat_messages]
            assert len(contents) == initial_count + 205
            assert len({r["id"] for r in app.chat_messages}) == initial_count + 205
            assert "Inside gap 0" in contents and "Inside gap 104" in contents
            if initial_count:
                assert "Before gap 0" in contents
        await app.http.aclose()

    asyncio.run(audit())


@pytest.mark.parametrize("initial_count", [0, 5, 105])
def test_terminal_help_refresh_retains_access_to_requests_inside_gap(live_server, initial_count):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Button

    url, c = live_server
    p = project(c)

    def post(i):
        assert c.post(f"/api/projects/{p}/help", json={"question": f"Gap help {i}"}).status_code == 200

    for i in range(initial_count):
        post(i)

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            assert len(app.help_requests) == min(initial_count, 100)
            for i in range(initial_count, initial_count + 205):
                post(i)
            app.refresh_remote()
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            questions = [r["question"] for r in app.help_requests]
            for _ in range(4):
                if app.query_one("#older-help", Button).disabled:
                    break
                await app.load_older_help()
                await app.workers.wait_for_complete()
                await pilot.pause(0.1)
            assert app.query_one("#older-help", Button).disabled
            questions = [r["question"] for r in app.help_requests]
            assert len(questions) == initial_count + 205
            assert len({r["id"] for r in app.help_requests}) == initial_count + 205
            assert "Gap help 0" in questions
            assert f"Gap help {initial_count + 204}" in questions
        await app.http.aclose()

    asyncio.run(audit())


def test_terminal_refresh_updates_answers_on_already_loaded_older_help(live_server):
    from agentcommons.tui import CommonsTUI

    url, c = live_server
    p = project(c)
    _, peer_headers, _ = agent(c, p, "Helpful peer")
    requests = [
        c.post(f"/api/projects/{p}/help", json={"question": f"Request {i}"}).json() for i in range(105)
    ]
    oldest_id = requests[0]["id"]

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            await app.workers.wait_for_complete()
            await app.load_older_help()
            await app.workers.wait_for_complete()
            assert len(app.help_requests) == 105
            endpoint = f"/api/projects/{p}/help/{oldest_id}"
            assert c.post(endpoint + "/claim", headers=peer_headers).status_code == 200
            assert (
                c.post(
                    endpoint + "/answer", headers=peer_headers, json={"answer": "Updated older answer"}
                ).status_code
                == 200
            )
            app.refresh_remote()
            await app.workers.wait_for_complete()
            row = next(row for row in app.help_requests if row["id"] == oldest_id)
            assert row["state"] == "answered"
            assert row["answer"] == "Updated older answer"

    asyncio.run(audit())


def test_terminal_conflict_preserves_draft_and_protects_concurrent_version(live_server):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import DataTable, TabbedContent, TextArea

    url, c = live_server
    p = project(c)
    note = c.post(
        f"/api/projects/{p}/memories", json={"title": "Retry conflict", "content": "Original"}
    ).json()

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = "memory-tab"
            app.query_one("#memories", DataTable).focus()
            await pilot.press("enter")
            await pilot.pause(0.2)
            app.screen.query_one("#field-content", TextArea).text = "Preserved draft"
            assert (
                c.put(
                    f"/api/projects/{p}/memories/{note['id']}",
                    json={
                        "title": "Retry conflict",
                        "content": "Concurrent version two",
                        "expected_version": 1,
                    },
                ).status_code
                == 200
            )
            await pilot.click("#save")
            await pilot.pause(0.4)
            assert isinstance(app.screen, FormScreen)
            assert app.screen.query_one("#field-content", TextArea).text == "Preserved draft"
            await pilot.click("#save")
            await pilot.pause(0.4)
            saved = c.get(f"/api/projects/{p}/snapshot").json()["memories"][0]
            assert isinstance(app.screen, FormScreen)
            assert app.screen.query_one("#field-content", TextArea).text == "Preserved draft"
            assert saved["content"] == "Concurrent version two" and saved["version"] == 2
            # A plain retry must never overwrite the concurrent edit. A user
            # can cancel, load the latest version, then deliberately reapply.
            await pilot.press("escape")
            app.refresh_remote()
            await pilot.pause(0.4)
            app.query_one("#memories", DataTable).focus()
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert app.screen.query_one("#field-content", TextArea).text == "Concurrent version two"
            app.screen.query_one("#field-content", TextArea).text = "Reviewed and reapplied preserved draft"
            await pilot.click("#save")
            await pilot.pause(0.4)
            assert not isinstance(app.screen, FormScreen)
            saved = c.get(f"/api/projects/{p}/snapshot").json()["memories"][0]
            assert saved["version"] == 3
            assert saved["content"] == "Reviewed and reapplied preserved draft"
        await app.http.aclose()

    asyncio.run(audit())


@pytest.mark.parametrize("kind", ["agent", "node"])
def test_terminal_invitation_keeps_draft_on_validation_error(live_server, kind):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import Input, TextArea

    url, c = live_server
    p = project(c)

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            if kind == "agent":
                app.action_add_agent()
            else:
                app.action_add_node()
            await pilot.pause(0.2)
            app.screen.query_one("#field-name", Input).value = "N" * (81 if kind == "agent" else 101)
            if kind == "agent":
                app.screen.query_one("#field-capabilities", Input).value = "python, review, architecture"
                app.screen.query_one(
                    "#field-limitations", TextArea
                ).text = "Carefully entered onboarding limitations"
            await pilot.click("#save")
            await pilot.pause(0.4)
            rows = c.get(f"/api/projects/{p}/snapshot").json()["agents" if kind == "agent" else "nodes"]
            assert len(rows) == 0
            assert isinstance(app.screen, FormScreen), (
                "A rejected invitation must preserve fields for correction"
            )
            if kind == "agent":
                assert (
                    app.screen.query_one("#field-limitations", TextArea).text
                    == "Carefully entered onboarding limitations"
                )
            app.screen.query_one("#field-name", Input).value = "Corrected invitation"
            await pilot.click("#save")
            await pilot.pause(0.4)
            from agentcommons.tui import DetailScreen
            from textual.widgets import RichLog

            assert isinstance(app.screen, DetailScreen)
            assert "CONNECTION TOKEN" in "\n".join(
                line.text for line in app.screen.query_one("#detail-log", RichLog).lines
            )
            rows = c.get(f"/api/projects/{p}/snapshot").json()["agents" if kind == "agent" else "nodes"]
            assert len(rows) == 1
            if kind == "agent":
                assert rows[0]["configured_capabilities"] == ["python", "review", "architecture"]
                assert rows[0]["configured_limitations"] == ["Carefully entered onboarding limitations"]
        await app.http.aclose()

    asyncio.run(audit())


@pytest.mark.parametrize("kind", ["project", "task", "memory"])
def test_terminal_creation_is_not_resubmitted_after_successful_post_and_failed_refresh(live_server, kind):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import Input, Select, TextArea

    url, c = live_server
    p = project(c)
    name = "Creation retry duplicate"
    collection = {"project": "projects", "task": "tasks", "memory": "memories"}[kind]
    endpoint = "/api/projects" if kind == "project" else f"/api/projects/{p}/{collection}"
    label = "name" if kind == "project" else "title"

    def created_rows():
        if kind == "project":
            return c.get(endpoint).json()
        return c.get(f"/api/projects/{p}/snapshot").json()[collection]

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            getattr(app, f"action_new_{kind}")()
            await pilot.pause(0.2)
            app.screen.query_one(f"#field-{label}", Input).value = name
            field = {"project": "goal", "task": "description", "memory": "content"}[kind]
            app.screen.query_one(
                f"#field-{field}", TextArea
            ).text = "Saved successfully before refresh failure"
            original = app.call
            failed = False
            posts = 0

            async def call(method, path, data=None):
                nonlocal failed, posts
                if method == "POST" and path == endpoint:
                    posts += 1
                if method == "GET" and path == "/api/projects" and not failed:
                    failed = True
                    raise RuntimeError("Simulated projects list refresh 503")
                return await original(method, path, data)

            app.call = call
            await pilot.click("#save")
            await pilot.pause(0.4)
            reopened = isinstance(app.screen, FormScreen)
            assert len([r for r in created_rows() if r[label] == name]) == 1
            if reopened:
                await pilot.click("#save")
                await pilot.pause(0.5)
            count = len([r for r in created_rows() if r[label] == name])
            assert count == 1, "A refresh failure must not invite replaying a successful creation"
            assert posts == 1
            assert not reopened
            assert app.query_one("#project-select", Select).value == app.project_id
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            assert not app.project_refresh_pending
            if kind == "project":
                assert len([r for r in app.projects if r["name"] == name]) == 1
            else:
                assert len([r for r in app.snapshot[collection] if r[label] == name]) == 1
        await app.http.aclose()

    asyncio.run(audit())


def test_terminal_can_send_to_all_named_channels(live_server):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Input, Select, TabbedContent

    url, c = live_server
    p = project(c)

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = "chat-tab"
            for channel in ["general", "engineering", "reviews"]:
                app.query_one("#chat-target", Select).value = "#" + channel
                await pilot.pause(0.2)
                app.query_one("#chat-input", Input).value = "Channel test " + channel
                await app.send()
                await pilot.pause(0.2)
                row = c.get(f"/api/projects/{p}/messages?channel={channel}").json()
                assert row[-1]["content"] == "Channel test " + channel
                assert row[-1]["recipient_id"] is None
        await app.http.aclose()

    asyncio.run(audit())


def test_terminal_polling_allows_a_slow_history_refresh_to_finish(live_server):
    from agentcommons.tui import CommonsTUI

    url, c = live_server
    p = project(c)
    for i in range(5):
        assert c.post(f"/api/projects/{p}/messages", json={"content": f"Before {i}"}).status_code == 201

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            assert len(app.chat_messages) == 5
            for i in range(205):
                assert (
                    c.post(f"/api/projects/{p}/messages", json={"content": f"Burst {i}"}).status_code == 201
                )
            original = app.chat_page
            started, release = asyncio.Event(), asyncio.Event()

            async def slow_page(project_id, target, before=None):
                if before:
                    started.set()
                    await release.wait()
                return await original(project_id, target, before)

            app.chat_page = slow_page
            worker = app.refresh_remote()
            await asyncio.wait_for(started.wait(), 5)
            try:
                # Cross the real four-second polling tick while a page is pending.
                await pilot.pause(4.2)
                assert not worker.is_finished
                assert not worker.is_cancelled
            finally:
                release.set()
            await app.workers.wait_for_complete()
            assert len(app.chat_messages) == 210
            assert len({row["id"] for row in app.chat_messages}) == 210

    asyncio.run(audit())


@pytest.mark.parametrize(
    "change",
    [
        "chat_target",
        "chat_project",
        "help_project",
        "chat_target_roundtrip",
        "chat_project_roundtrip",
        "help_project_roundtrip",
    ],
)
def test_terminal_discards_late_older_pages_after_switching_context(live_server, change):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Select

    url, c = live_server
    p = project(c)
    for i in range(105):
        if change.startswith("help"):
            assert c.post(f"/api/projects/{p}/help", json={"question": f"Old help {i}"}).status_code == 200
        else:
            assert (
                c.post(f"/api/projects/{p}/messages", json={"content": f"Old message {i}"}).status_code == 201
            )
    new_project = p if change.startswith("chat_target") else project(c, "Next project")
    if change.startswith("help"):
        assert c.post(f"/api/projects/{new_project}/help", json={"question": "Fresh help"}).status_code == 200
    else:
        channel = "engineering" if change.startswith("chat_target") else "general"
        assert (
            c.post(
                f"/api/projects/{new_project}/messages", json={"content": "Fresh message", "channel": channel}
            ).status_code
            == 201
        )

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one("#project-select", Select).value = p
            await pilot.pause(0.3)
            await app.workers.wait_for_complete()
            assert app.project_id == p
            assert len(app.help_requests if change.startswith("help") else app.chat_messages) == 100
            started, release = asyncio.Event(), asyncio.Event()
            is_help = change.startswith("help")
            original = app.help_page if is_help else app.chat_page

            async def delayed_page(*args, **kwargs):
                rows = await original(*args, **kwargs)
                before = kwargs.get("before", args[-1] if len(args) > (1 if is_help else 2) else None)
                if before:
                    started.set()
                    await release.wait()
                return rows

            if is_help:
                app.help_page = delayed_page
            else:
                app.chat_page = delayed_page
            pending = asyncio.create_task(app.load_older_help() if is_help else app.load_older_chat())
            await asyncio.wait_for(started.wait(), 5)
            try:
                if change.startswith("chat_target"):
                    app.query_one("#chat-target", Select).value = "#engineering"
                else:
                    app.query_one("#project-select", Select).value = new_project
                await pilot.pause(0.3)
                await app.workers.wait_for_complete()
                if change.endswith("_roundtrip"):
                    for i in range(205):
                        endpoint = f"/api/projects/{p}/{'help' if is_help else 'messages'}"
                        response = c.post(
                            endpoint, json={"question" if is_help else "content": f"New burst {i}"}
                        )
                        assert response.status_code == (200 if is_help else 201)
                    if change.startswith("chat_target"):
                        app.query_one("#chat-target", Select).value = "#general"
                    else:
                        app.query_one("#project-select", Select).value = p
                    await pilot.pause(0.3)
                    await app.workers.wait_for_complete()
            finally:
                release.set()
            await pending
            await app.workers.wait_for_complete()
            if change.endswith("_roundtrip"):
                from textual.widgets import Button

                button = app.query_one("#older-help" if is_help else "#older-chat", Button)
                assert len(app.help_requests if is_help else app.chat_messages) == 100
                assert not button.disabled
                for _ in range(4):
                    if button.disabled:
                        break
                    await (app.load_older_help() if is_help else app.load_older_chat())
                    await app.workers.wait_for_complete()
                    await pilot.pause(0.1)
                rows = app.help_requests if is_help else app.chat_messages
                assert len(rows) == 310
                assert len({row["id"] for row in rows}) == 310
                assert button.disabled
            elif is_help:
                assert [row["question"] for row in app.help_requests] == ["Fresh help"]
            else:
                assert [row["content"] for row in app.chat_messages] == ["Fresh message"]

    asyncio.run(audit())


@pytest.mark.parametrize("size", [(80, 24), (130, 45)])
def test_terminal_history_buttons_work_at_actual_terminal_sizes(live_server, size):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Button, TabbedContent

    url, c = live_server
    p = project(c)
    for i in range(105):
        assert c.post(f"/api/projects/{p}/help", json={"question": f"Clickable help {i}"}).status_code == 200

    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = "health-tab"
            await pilot.pause(0.2)
            assert len(app.help_requests) == 100
            assert not app.query_one("#older-help", Button).disabled
            assert await pilot.click("#older-help")
            await app.workers.wait_for_complete()
            await pilot.pause(0.3)
            assert len(app.help_requests) == 105
            assert app.query_one("#older-help", Button).disabled
            app.query_one(TabbedContent).active = "chat-tab"
            await pilot.pause(0.2)
            assert len(app.chat_messages) == 100
            assert await pilot.click("#older-chat")
            await app.workers.wait_for_complete()
            await pilot.pause(0.3)
            assert len(app.chat_messages) == 105
            assert app.query_one("#older-chat", Button).disabled
        await app.http.aclose()

    asyncio.run(audit())
