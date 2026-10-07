"""The terminal is a first-class client of the same remote collaboration API."""

import httpx
import json
from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Select, Static, TabbedContent, TabPane, TextArea


class FormScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    FormScreen { align: center middle; background: $background 80%; }
    #form { width: 76; max-width: 95%; max-height: 90%; border: round #b6a0ef; padding: 1 2; background: #191a21; }
    #form-title { text-style: bold; color: #b1ed88; margin-bottom: 1; }
    #form Label { margin-top: 1; color: #a8aec2; }
    #form Input { background: #111218; border: tall #3a3c48; }
    #form TextArea { height: 8; background: #111218; border: tall #3a3c48; }
    #form-actions { height: 3; margin-top: 1; align: right middle; }
    #form-actions Button { margin-left: 1; }
    """

    def __init__(self, title, fields):
        super().__init__()
        self.title_text, self.fields = title, fields

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form"):
            yield Static(self.title_text, id="form-title")
            for key, label, multiline, default in self.fields:
                yield Label(label)
                yield TextArea(default, id=f"field-{key}") if multiline else Input(default, id=f"field-{key}")
            with Horizontal(id="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="success", id="save")

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed)
    def button(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            values = {}
            for key, _, multiline, _ in self.fields:
                widget = self.query_one(f"#field-{key}")
                values[key] = (widget.text if multiline else widget.value).strip()
            self.dismiss(values)


class DetailScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Close")]
    DEFAULT_CSS = """
    DetailScreen { align: center middle; background: $background 80%; }
    #detail { width: 85; max-width: 95%; height: 80%; border: round #b6a0ef; background: #191a21; padding: 1 2; }
    #detail RichLog { background: #191a21; height: 1fr; }
    #detail Button { dock: bottom; }
    """

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self):
        with VerticalScroll(id="detail"):
            yield RichLog(id="detail-log", wrap=True, markup=False)
            yield Button("Close", id="close")

    def on_mount(self):
        self.query_one("#detail-log", RichLog).write(self.text)

    def action_cancel(self):
        self.dismiss()

    @on(Button.Pressed)
    def close(self):
        self.dismiss()


class CommonsTUI(App):
    TITLE = "AgentVerse"
    SUB_TITLE = "Different agents. One project. A real team."
    CSS = """
    Screen { background: #101115; color: #e6e7eb; }
    Header { background: #1b1d24; color: #b1ed88; }
    Footer { background: #1b1d24; }
    #project-bar { height: 3; margin: 1 2 0 2; }
    #project-select { width: 35%; }
    #status { width: 1fr; padding: 1 2 0 2; color: #a3a7ba; }
    #goal { margin: 1 2; padding: 1 2; border: round #454053; height: auto; max-height: 6; color: #c3b7de; }
    TabbedContent { margin: 0 2; height: 1fr; }
    ContentSwitcher { height: 1fr; }
    TabPane { padding: 1; }
    DataTable { background: #17191f; height: 1fr; }
    DataTable > .datatable--header { background: #252832; color: #b1ed88; text-style: bold; }
    DataTable > .datatable--cursor { background: #383347; color: #efe6ff; }
    RichLog { background: #17191f; border: round #2f323d; height: 1fr; }
    #chat-controls { dock: bottom; height: 3; margin-top: 1; }
    #chat-target { width: 25; }
    #chat-input { width: 1fr; }
    #send { min-width: 8; width: 8; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"), ("p", "new_project", "Project"), ("n", "new_task", "Task"),
        ("a", "add_agent", "Agent"), ("m", "new_memory", "Memory"),
        ("r", "release_task", "Release task"), ("space", "toggle_pause", "Pause/resume"),
        ("c", "configure_agent", "Runtime"), ("l", "launch_agent", "Launch"), ("s", "stop_agent", "Stop"),
        ("e", "edit_agent", "Profile"), ("h", "request_help", "Ask peer"), ("o", "add_node", "Node"),
        ("i", "report_problem", "Problem"), ("x", "resolve_problem", "Resolve"),
    ]

    def __init__(self, server, token):
        super().__init__()
        self.http = httpx.AsyncClient(base_url=server.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=20)
        self.server = server.rstrip("/")
        self.project_id = None
        self.snapshot = None
        self.is_admin = False

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal(id="project-bar"):
            yield Select([], prompt="Choose a project", id="project-select")
            yield Static("Connecting to AgentVerse…", id="status")
        yield Static("Create a project [p] and invite your remote teammates [a].", id="goal")
        with TabbedContent():
            with TabPane("Tasks", id="tasks-tab"):
                yield DataTable(id="tasks", cursor_type="row")
            with TabPane("Conversation", id="chat-tab"):
                yield RichLog(id="chat", wrap=True, markup=True)
                with Horizontal(id="chat-controls"):
                    yield Select([("# general", "")], value="", allow_blank=False, id="chat-target")
                    yield Input(placeholder="Talk to your team…", id="chat-input")
                    yield Button("Send", id="send", variant="success")
            with TabPane("Team", id="agents-tab"):
                yield DataTable(id="agents", cursor_type="row")
            with TabPane("Memory", id="memory-tab"):
                yield DataTable(id="memories", cursor_type="row")
            with TabPane("Reviews", id="reviews-tab"):
                yield RichLog(id="reviews", wrap=True, markup=True)
            with TabPane("Activity", id="activity-tab"):
                yield RichLog(id="activity", wrap=True, markup=True)
            with TabPane("Health & help", id="health-tab"):
                yield RichLog(id="health", wrap=True, markup=False)
        yield Footer()

    async def call(self, method, path, data=None):
        response = await self.http.request(method, path, json=data)
        if response.is_error:
            raise RuntimeError(str(response.json().get("detail", response.status_code)))
        return response.json()

    async def on_mount(self):
        self.query_one("#tasks", DataTable).add_columns("State", "Priority", "Task", "Owner", "Dependencies")
        self.query_one("#agents", DataTable).add_columns("Connection", "Name", "Tool", "Strengths", "Mode", "Runtime", "Model")
        self.query_one("#memories", DataTable).add_columns("Version", "Title", "Tags", "Author")
        try:
            self.is_admin = (await self.call("GET", "/api/me"))["admin"]
            await self.load_projects()
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=10)
        self.set_interval(4, self.refresh_remote)

    async def on_unmount(self):
        await self.http.aclose()

    async def load_projects(self):
        projects = await self.call("GET", "/api/projects")
        select = self.query_one("#project-select", Select)
        select.set_options([(p["name"], p["id"]) for p in projects])
        if projects:
            self.project_id = self.project_id if any(p["id"] == self.project_id for p in projects) else projects[0]["id"]
            select.value = self.project_id
            self.refresh_remote()

    @on(Select.Changed, "#project-select")
    def project_changed(self, event):
        if event.value is not Select.BLANK:
            self.project_id = event.value
            self.refresh_remote()

    @on(Select.Changed, "#chat-target")
    def target_changed(self):
        self.refresh_remote()

    @work(exclusive=True)
    async def refresh_remote(self):
        if not self.project_id or isinstance(self.screen, ModalScreen):
            return
        try:
            project_id = self.project_id
            data = await self.call("GET", f"/api/projects/{project_id}/snapshot")
            if project_id != self.project_id or isinstance(self.screen, ModalScreen):
                return
            self.snapshot = data
            agents = {a["id"]: a for a in data["agents"]}
            nodes = {node["id"]: node for node in data["nodes"]}
            def name(actor):
                return "You" if actor == "human" else agents.get(actor, {}).get("name", nodes.get(actor, {}).get("name", "—"))
            online = sum(a["online"] for a in agents.values())
            done = sum(t["status"] == "done" for t in data["tasks"])
            self.query_one("#status", Static).update(f"● {online} agents online    {done}/{len(data['tasks'])} complete    {data['project']['status'].upper()}")
            self.query_one("#goal", Static).update(escape(data["project"]["goal"]))
            cursors = {table_id: self.query_one(f"#{table_id}", DataTable).cursor_row
                       for table_id in ("tasks", "agents", "memories")}
            for table_id in ("tasks", "agents", "memories"):
                self.query_one(f"#{table_id}", DataTable).clear()
            for task in data["tasks"]:
                self.query_one("#tasks", DataTable).add_row(
                    "blocked" if task["blocked"] and task["status"] == "backlog" else task["status"], task["priority"],
                    escape(task["title"]), escape(name(task["assignee_id"])), str(len(task["dependencies"])), key=task["id"])
            for agent in agents.values():
                runtime = agent["runtime"] or {}
                self.query_one("#agents", DataTable).add_row(
                    agent["status"] if agent["online"] else "offline", escape(agent["name"]), escape(agent["kind"]),
                    escape(", ".join(agent["capabilities"])), runtime.get("mode", "connected"), runtime.get("state", "external"),
                    escape(runtime.get("model") or "tool default"), key=agent["id"])
            for memory in data["memories"]:
                self.query_one("#memories", DataTable).add_row(str(memory["version"]), escape(memory["title"]),
                    escape(", ".join(memory["tags"])), escape(name(memory["author_id"])), key=memory["id"])
            for table_id, cursor in cursors.items():
                table = self.query_one(f"#{table_id}", DataTable)
                if table.row_count:
                    table.move_cursor(row=min(cursor, table.row_count - 1))
            target_select = self.query_one("#chat-target", Select)
            current = target_select.value
            options = [("# general", "")] + [(a["name"], a["id"]) for a in agents.values() if a["id"] != data["identity"]["actor_id"]]
            if not self.is_admin:
                options.append(("Workspace owner", "human"))
            if [(str(label), value) for label, value in options] != getattr(self, "_chat_options", None):
                self._chat_options = options
                target_select.set_options(options)
                target_select.value = current if current in [value for _, value in options] else ""
            target = target_select.value
            log = self.query_one("#chat", RichLog)
            log.clear()
            for message in data["messages"]:
                if target:
                    if not message["recipient_id"] or target not in (message["recipient_id"], message["sender_id"]):
                        continue
                elif message["recipient_id"] or message["channel"] != "general":
                    continue
                log.write(f"[bold #b6a0ef]{escape(name(message['sender_id']))}[/]\n{escape(message['content'])}\n")
            for log_id, rows in [("reviews", data["reviews"]), ("activity", data["events"][-30:])]:
                log = self.query_one(f"#{log_id}", RichLog)
                log.clear()
                for row in rows:
                    text = f"{row['decision']} · {name(row['reviewer_id'])}\n{row['comment']}" if log_id == "reviews" else f"{name(row['actor_id'])} · {row['detail']}"
                    log.write(escape(text) + "\n")
            health = self.query_one("#health", RichLog)
            health.clear()
            for node in nodes.values():
                health.write(f"{node['name']} · {'online' if node['online'] else 'offline'} · capacity {node['capacity']}")
                for profile in node["profiles"]:
                    health.write(f"  {profile['id']} · {profile['mode']} · {profile['availability']}\n  {profile['diagnostic']}")
            for issue in data["issues"]:
                if not issue["resolved"]:
                    health.write(f"\n{issue['id']} · {issue['severity'].upper()} · {name(issue['agent_id'])} · {issue['title']}\n{issue['detail']}")
            for request in data["help_requests"][:20]:
                health.write(f"\n{request['state']} · {request['capability'] or 'general'} · {name(request['sender_id'])}\n{request['question']}\n{request['answer'] or 'Waiting for a matching teammate.'}")
        except Exception as exc:
            self.notify(str(exc), severity="error")

    @on(Input.Submitted, "#chat-input")
    @on(Button.Pressed, "#send")
    async def send(self):
        widget = self.query_one("#chat-input", Input)
        if not widget.value.strip() or not self.project_id:
            return
        try:
            await self.call("POST", f"/api/projects/{self.project_id}/messages", {
                "content": widget.value.strip(), "recipient_id": self.query_one("#chat-target", Select).value or None})
            widget.value = ""
            self.refresh_remote()
        except Exception as exc:
            self.notify(str(exc), severity="error")

    def form(self, title, fields, path, method="POST", extra=None, secret=False):
        async def submit(data):
            if data is None:
                return
            try:
                for key in ("tags", "capabilities", "required_capabilities"):
                    if key in data:
                        data[key] = [t.strip() for t in data[key].split(",") if t.strip()]
                if "limitations" in data:
                    data["limitations"] = [t.strip() for t in data["limitations"].splitlines() if t.strip()]
                if "settings" in data:
                    data["settings"] = json.loads(data["settings"] or "{}")
                route = path
                if "issue_id" in data:
                    from urllib.parse import quote
                    route = route.replace("{issue_id}", quote(data.pop("issue_id"), safe=""))
                result = await self.call(method, route, {**data, **(extra or {})})
                if secret:
                    self.push_screen(DetailScreen(f"CONNECTION TOKEN — save this now, shown once\n\n{result['token']}\n\n"
                        f"MCP endpoint: {self.server}/mcp/\nEditors/apps: attach MCP, call announce_peer and list_teammates, heartbeat every 25s.\n"
                        "Managed tools: prepare a node config; run agentverse doctor and agentverse node.\n"
                        "A node token connects the supervisor; a teammate token connects one agent.\nSee docs/agents.md and docs/remote-control.md."))
                    return
                await self.load_projects()
                self.refresh_remote()
                self.notify("Saved to your shared workspace.")
            except Exception as exc:
                self.notify(str(exc), severity="error", timeout=10)
        self.push_screen(FormScreen(title, fields), submit)

    def action_new_project(self):
        if self.is_admin:
            self.form("Start something together", [("name", "Project name", False, ""), ("goal", "Common goal", True, ""),
                ("repo_url", "Git repository URL (optional)", False, "")], "/api/projects")

    def action_new_task(self):
        if self.project_id:
            self.form("Give the team a next step", [("title", "Task title", False, ""),
                ("description", "Description & acceptance criteria", True, ""),
                ("required_capabilities", "Required capabilities (comma-separated; optional)", False, "")], f"/api/projects/{self.project_id}/tasks")

    def action_add_agent(self):
        if self.is_admin and self.project_id:
            self.form("Meet your new teammate", [("name", "Teammate name", False, ""),
                ("kind", "Tool ID: any current or future tool", False, "custom"),
                ("capabilities", "Strengths (comma-separated)", False, ""),
                ("limitations", "Limitations (one per line)", True, "")],
                f"/api/projects/{self.project_id}/agents", secret=True)

    def selected_agent(self):
        table = self.query_one("#agents", DataTable)
        if not self.snapshot or not table.row_count:
            self.notify("Select a teammate in the Team tab first.")
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((a for a in self.snapshot["agents"] if a["id"] == key), None)

    @on(DataTable.RowSelected, "#agents")
    def agent_detail(self, event):
        agent = next(a for a in self.snapshot["agents"] if a["id"] == event.row_key.value)
        self.push_screen(DetailScreen(json.dumps(agent, indent=2) + "\n\n[c] Runtime · [e] Profile · [l] Launch · [s] Stop\n"
            "Connected sessions start/stop in their own client. Managed API claims stay held while cancellation is unconfirmed."))

    def action_edit_agent(self):
        peer = self.selected_agent()
        if self.is_admin and peer:
            self.form(f"Edit {peer['name']}’s profile", [("name", "Name", False, peer["name"]),
                ("description", "Role & context", True, peer["description"]),
                ("capabilities", "Strengths (comma-separated)", False, ", ".join(peer["configured_capabilities"])),
                ("limitations", "Limitations (one per line)", True, "\n".join(peer["configured_limitations"]))],
                f"/api/projects/{self.project_id}/agents/{peer['id']}", "PATCH", {"expected_version": peer["profile_version"]})

    def action_configure_agent(self):
        peer = self.selected_agent()
        if not self.is_admin or not peer:
            return
        options = [(n, p) for n in self.snapshot["nodes"] for p in n["profiles"] if peer["kind"] in {"custom", p["kind"]}]
        if not options:
            self.notify("No matching runtime profiles. Register a node [o], configure its tools, and start its service.")
            return
        n, p = options[0]
        current = peer["runtime"] or {}
        catalog = " · ".join(f"{n['name']}: {n['id']}/{p['id']} ({p['mode']})" for n, p in options)
        self.form(f"Runtime for {peer['name']}\n{catalog}", [
            ("node_id", "Node ID", False, current.get("node_id", n["id"])),
            ("profile_id", "Profile ID", False, current.get("profile_id", p["id"])),
            ("model", "Advertised model ID (empty = tool default)", False, current.get("model", p["models"][0]["id"])),
            ("settings", "Advertised settings as JSON (see Team details / web UI)", True, json.dumps(current.get("settings", {})))],
            f"/api/projects/{self.project_id}/agents/{peer['id']}/runtime", "PUT")

    async def agent_operation(self, operation):
        peer = self.selected_agent()
        if self.is_admin and peer:
            try:
                await self.call("POST", f"/api/projects/{self.project_id}/agents/{peer['id']}/{operation}")
                self.refresh_remote()
            except Exception as exc:
                self.notify(str(exc), severity="error")

    async def action_launch_agent(self):
        await self.agent_operation("launch")

    async def action_stop_agent(self):
        await self.agent_operation("stop")

    def action_request_help(self):
        if self.project_id:
            self.form("Ask an equal teammate for help", [("capability", "Capability needed (optional, exact tag)", False, ""),
                ("question", "Question & context (shared with the project)", True, "")], f"/api/projects/{self.project_id}/help")

    def action_add_node(self):
        if self.is_admin and self.project_id:
            self.form("Register a remote node", [("name", "Node name", False, "")], f"/api/projects/{self.project_id}/nodes", secret=True)

    def action_report_problem(self):
        peer = self.selected_agent()
        if peer and (self.is_admin or self.snapshot["identity"]["actor_id"] == peer["id"]):
            self.form(f"Report a problem for {peer['name']}", [("title", "Problem", False, ""),
                ("detail", "Details (no credentials)", True, ""), ("severity", "info / warning / error", False, "warning")],
                f"/api/projects/{self.project_id}/agents/{peer['id']}/issues")

    def action_resolve_problem(self):
        if not self.snapshot:
            return
        issues = [i for i in self.snapshot["issues"] if not i["resolved"] and (self.is_admin or i["agent_id"] == self.snapshot["identity"]["actor_id"])]
        if not issues:
            self.notify("No open problems for this identity.")
            return
        self.form("Resolve an agent problem", [("issue_id", "Issue ID (see Health & help)", False, issues[0]["id"])],
                  f"/api/projects/{self.project_id}/issues/{{issue_id}}/resolve")

    def action_new_memory(self):
        if self.project_id:
            self.form("Remember something useful", [("title", "Title", False, ""), ("content", "Shared knowledge", True, ""),
                ("tags", "Tags, comma-separated", False, "")], f"/api/projects/{self.project_id}/memories")

    @on(DataTable.RowSelected, "#memories")
    def edit_memory(self, event):
        memory = next(m for m in self.snapshot["memories"] if m["id"] == event.row_key.value)
        self.form("Update shared memory", [("title", "Title", False, memory["title"]),
            ("content", "Shared knowledge", True, memory["content"]), ("tags", "Tags", False, ", ".join(memory["tags"]))],
            f"/api/projects/{self.project_id}/memories/{memory['id']}", "PUT", {"expected_version": memory["version"]})

    @on(DataTable.RowSelected, "#tasks")
    def task_detail(self, event):
        task = next(t for t in self.snapshot["tasks"] if t["id"] == event.row_key.value)
        self.push_screen(DetailScreen(f"{task['title']}\n\n{task['description']}\n\n{task['status']} · {task['priority']}\n\n"
            f"{task['summary'] or ''}\n\nBranch: {task['branch'] or '—'}\nCommit: {task['commit_sha'] or '—'}\n\n{task['diff'] or ''}"))

    async def action_toggle_pause(self):
        if self.is_admin and self.snapshot:
            try:
                status = "active" if self.snapshot["project"]["status"] == "paused" else "paused"
                await self.call("PATCH", f"/api/projects/{self.project_id}", {"status": status})
                self.refresh_remote()
            except Exception as exc:
                self.notify(str(exc), severity="error")

    async def action_release_task(self):
        if not self.snapshot:
            return
        table = self.query_one("#tasks", DataTable)
        if table.row_count:
            task_id = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            try:
                await self.call("POST", f"/api/projects/{self.project_id}/tasks/{task_id}/release", {"reason": "Released from terminal UI."})
                self.refresh_remote()
            except Exception as exc:
                self.notify(str(exc), severity="error")
