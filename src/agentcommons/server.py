import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .mcp_bridge import create_mcp
from .models import (
    AgentCreate, Heartbeat, MemoryWrite, MessageCreate, PlanFinish, ProjectCreate, ProjectUpdate,
    NodeCreate, NodePoll, NodeRegister, ReleaseTask, ReviewCreate, RuntimeConfig, RuntimeReport,
    TaskCreate, TaskEdit, WorkSubmit, LoginRequest,
)
from .store import Store
from .config import PRODUCT, VERSION, PROTOCOL_VERSION, setting
from .models import AgentEdit, AgentAnnounce, HelpCreate, HelpAnswer, IssueCreate


class SPAFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                return response
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
        if path.startswith(("api/", "mcp/", "assets/")):
            raise HTTPException(404, "Not found.")
        return await super().get_response("index.html", scope)


def create_app(db_path=None, admin_token=None, web_dir=None):
    store = Store(db_path or setting("DB", "data/agentcommons.db"), admin_token or setting("ADMIN_TOKEN"))
    mcp = create_mcp(store)
    mcp_app = mcp.streamable_http_app()
    tickets = {}

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield
        store.close()

    app = FastAPI(title=PRODUCT, version=VERSION, lifespan=lifespan)
    app.state.store = store
    origins = [x.strip() for x in setting("ORIGINS").split(",") if x.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"],
                           allow_headers=["Authorization", "Content-Type"])

    def principal(authorization: str | None = Header(default=None)):
        return store.authenticate(authorization)

    def node_identity(authorization: str | None = Header(default=None)):
        return store.runtimes.authenticate_node(authorization)

    @app.middleware("http")
    async def protect_mcp(request, call_next):
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            try:
                store.authenticate(request.headers.get("authorization"))
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION, "product": PRODUCT}

    @app.get("/api/protocol")
    def protocol():
        return {"product": PRODUCT, "version": VERSION, "protocol_version": PROTOCOL_VERSION,
                "connection_modes": ["managed_cli", "managed_api", "connected"],
                "peer_transports": ["mcp", "http"], "mcp_path": "/mcp/",
                 "features": ["peer-discovery", "capabilities", "versioned-profiles", "settings-schema", "health", "help-requests"]}

    @app.post("/api/login")
    def login(data: LoginRequest, request: Request):
        return store.admin_session(data.username, data.password, request.client.host if request.client else "unknown")

    @app.post("/api/logout")
    def logout(authorization: str | None = Header(default=None), p=Depends(principal)):
        return store.revoke_session(authorization)

    @app.get("/api/me")
    def me(p=Depends(principal)):
        return {"actor_id": p.actor, "project_id": p.project_id, "admin": p.admin}

    @app.get("/api/projects")
    def projects(p=Depends(principal)):
        return store.projects(p)

    @app.post("/api/projects", status_code=201)
    def create_project(data: ProjectCreate, p=Depends(principal)):
        return store.create_project(p, data)

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, data: ProjectUpdate, p=Depends(principal)):
        return store.set_project_status(p, project_id, data.status)

    @app.get("/api/projects/{project_id}/snapshot")
    def snapshot(project_id: str, p=Depends(principal)):
        return store.snapshot(p, project_id)

    @app.post("/api/projects/{project_id}/agents", status_code=201)
    def agent_create(project_id: str, data: AgentCreate, p=Depends(principal)):
        return store.add_agent(p, project_id, data)

    @app.delete("/api/projects/{project_id}/agents/{agent_id}")
    def revoke_agent(project_id: str, agent_id: str, p=Depends(principal)):
        return store.revoke_agent(p, project_id, agent_id)

    @app.patch("/api/projects/{project_id}/agents/{agent_id}")
    def edit_agent(project_id: str, agent_id: str, data: AgentEdit, p=Depends(principal)):
        return store.team.edit(p, project_id, agent_id, data)

    @app.post("/api/projects/{project_id}/agents/{agent_id}/token")
    def rotate_token(project_id: str, agent_id: str, p=Depends(principal)):
        return store.rotate_agent_token(p, project_id, agent_id)

    @app.post("/api/agents/announce")
    def announce(data: AgentAnnounce, p=Depends(principal)):
        return store.team.announce(p, data)

    @app.get("/api/projects/{project_id}/teammates")
    def teammates(project_id: str, capability: str = "", p=Depends(principal)):
        return store.team.peers(p, project_id, capability)

    @app.post("/api/projects/{project_id}/agents/{agent_id}/issues")
    def issue(project_id: str, agent_id: str, data: IssueCreate, p=Depends(principal)):
        return store.team.issue(p, project_id, agent_id, data)

    @app.post("/api/projects/{project_id}/issues/{issue_id}/resolve")
    def resolve_issue(project_id: str, issue_id: str, p=Depends(principal)):
        return store.team.resolve(p, project_id, issue_id)

    @app.post("/api/projects/{project_id}/help")
    def ask_help(project_id: str, data: HelpCreate, p=Depends(principal)):
        return store.team.ask(p, project_id, data)

    @app.post("/api/projects/{project_id}/help/{help_id}/claim")
    def claim_help(project_id: str, help_id: str, p=Depends(principal)):
        return store.team.claim_help(p, project_id, help_id)

    @app.post("/api/projects/{project_id}/help/{help_id}/answer")
    def answer_help(project_id: str, help_id: str, data: HelpAnswer, p=Depends(principal)):
        return store.team.answer(p, project_id, help_id, data)

    @app.post("/api/projects/{project_id}/help/{help_id}/release")
    def release_help(project_id: str, help_id: str, p=Depends(principal)):
        return store.team.release_help(p, project_id, help_id)

    @app.get("/api/projects/{project_id}/nodes")
    def nodes(project_id: str, p=Depends(principal)):
        return store.runtimes.nodes(p, project_id)

    @app.post("/api/projects/{project_id}/nodes", status_code=201)
    def create_node(project_id: str, data: NodeCreate, p=Depends(principal)):
        return store.runtimes.add_node(p, project_id, data)

    @app.put("/api/projects/{project_id}/agents/{agent_id}/runtime")
    def configure_runtime(project_id: str, agent_id: str, data: RuntimeConfig, p=Depends(principal)):
        return store.runtimes.configure(p, project_id, agent_id, data)

    @app.post("/api/projects/{project_id}/agents/{agent_id}/launch")
    def launch_runtime(project_id: str, agent_id: str, p=Depends(principal)):
        return store.runtimes.launch(p, project_id, agent_id)

    @app.post("/api/projects/{project_id}/agents/{agent_id}/stop")
    def stop_runtime(project_id: str, agent_id: str, p=Depends(principal)):
        return store.runtimes.stop(p, project_id, agent_id)

    @app.post("/api/nodes/me/register")
    def register_node(data: NodeRegister, node=Depends(node_identity)):
        return store.runtimes.register(node, data)

    @app.post("/api/nodes/me/inventory")
    def node_inventory(data: NodeRegister, node=Depends(node_identity)):
        return store.runtimes.refresh_inventory(node, data)

    @app.post("/api/nodes/me/poll")
    def poll_node(data: NodePoll, node=Depends(node_identity)):
        return store.runtimes.poll(node, data)

    @app.post("/api/nodes/me/report")
    def report_node(data: RuntimeReport, node=Depends(node_identity)):
        return store.runtimes.report(node, data)

    @app.post("/api/nodes/me/disconnect")
    def disconnect_node(data: NodePoll, node=Depends(node_identity)):
        return store.runtimes.disconnect(node, data)

    @app.post("/api/agents/heartbeat")
    def heartbeat(data: Heartbeat, p=Depends(principal)):
        return store.heartbeat(p, data.status)

    @app.get("/api/projects/{project_id}/messages")
    def messages(project_id: str, limit: int = Query(default=100, ge=1, le=500), p=Depends(principal)):
        return store.messages(p, project_id, limit)

    @app.post("/api/projects/{project_id}/messages", status_code=201)
    def message(project_id: str, data: MessageCreate, p=Depends(principal)):
        return store.message(p, project_id, data)

    @app.get("/api/projects/{project_id}/tasks")
    def tasks(project_id: str, p=Depends(principal)):
        return store.tasks(p, project_id)

    @app.post("/api/projects/{project_id}/tasks", status_code=201)
    def create_task(project_id: str, data: TaskCreate, p=Depends(principal)):
        return store.create_task(p, project_id, data)

    @app.patch("/api/projects/{project_id}/tasks/{task_id}")
    def edit_task(project_id: str, task_id: str, data: TaskEdit, p=Depends(principal)):
        return store.edit_task(p, project_id, task_id, data)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/claim")
    def claim_task(project_id: str, task_id: str, p=Depends(principal)):
        return store.claim_task(p, project_id, task_id)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/release")
    def release_task(project_id: str, task_id: str, data: ReleaseTask, p=Depends(principal)):
        return store.release_task(p, project_id, task_id, data.reason)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/plan")
    def finish_plan(project_id: str, task_id: str, data: PlanFinish, p=Depends(principal)):
        return store.finish_plan(p, project_id, task_id, data)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/submit")
    def submit_work(project_id: str, task_id: str, data: WorkSubmit, p=Depends(principal)):
        return store.submit_work(p, project_id, task_id, data)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/review-claim")
    def claim_review(project_id: str, task_id: str, p=Depends(principal)):
        return store.claim_review(p, project_id, task_id)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/review-release")
    def release_review(project_id: str, task_id: str, p=Depends(principal)):
        return store.release_review(p, project_id, task_id)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/review")
    def review_work(project_id: str, task_id: str, data: ReviewCreate, p=Depends(principal)):
        return store.review_work(p, project_id, task_id, data)

    @app.post("/api/projects/{project_id}/memories", status_code=201)
    def create_memory(project_id: str, data: MemoryWrite, p=Depends(principal)):
        return store.write_memory(p, project_id, data)

    @app.put("/api/projects/{project_id}/memories/{memory_id}")
    def update_memory(project_id: str, memory_id: str, data: MemoryWrite, p=Depends(principal)):
        return store.write_memory(p, project_id, data, memory_id)

    @app.get("/api/projects/{project_id}/events")
    def events(project_id: str, after: int = Query(default=0, ge=0),
               limit: int = Query(default=100, ge=1, le=500), p=Depends(principal)):
        return store.events(p, project_id, after, limit)

    @app.post("/api/realtime-ticket")
    async def realtime_ticket(project_id: str, p=Depends(principal),
                              authorization: str | None = Header(default=None)):
        store.project(p, project_id)
        now = time.time()
        for key in list(tickets):
            if tickets[key][0] < now:
                del tickets[key]
        ticket = secrets.token_urlsafe(32)
        tickets[ticket] = (now + 30, authorization, project_id)
        return {"ticket": ticket}

    @app.websocket("/api/live")
    async def live(ws: WebSocket, ticket: str, after: int = 0):
        entry = tickets.pop(ticket, None)
        if not entry or entry[0] < time.time():
            await ws.close(code=4401)
            return
        _, authorization, project_id = entry
        await ws.accept()
        cursor = max(0, after)
        try:
            while True:
                p = store.authenticate(authorization)
                batch = store.events(p, project_id, cursor)
                if batch:
                    cursor = batch[-1]["id"]
                    await ws.send_json({"type": "events", "events": batch, "cursor": cursor})
                else:
                    await ws.send_json({"type": "ping", "cursor": cursor})
                await asyncio.sleep(1)
        except HTTPException:
            await ws.close(code=4401)
        except (WebSocketDisconnect, RuntimeError):
            pass

    app.mount("/mcp", mcp_app)
    dist = Path(web_dir or setting("WEB_DIR", Path(__file__).resolve().parents[2] / "web/dist"))
    if (dist / "index.html").is_file():
        app.mount("/", SPAFiles(directory=dist, html=True), name="web")
    return app
