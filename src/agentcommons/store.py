"""Transactional collaboration state. Every mutation and its event commit together."""

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from .models import AgentCreate, MemoryWrite, MessageCreate, PlanFinish, ProjectCreate, TaskCreate
from .orchestration import ACTIVE_STATES, RuntimeRegistry
from .team import TeamRegistry
from .config import setting


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def fail(code: int, detail: str):
    raise HTTPException(code, detail)


@dataclass(frozen=True)
class Principal:
    agent_id: str | None = None
    project_id: str | None = None
    run_id: str | None = None

    @property
    def actor(self):
        return self.agent_id or "human"

    @property
    def admin(self):
        return self.agent_id is None


class Store:
    def __init__(self, path: str, admin_token: str):
        if len(admin_token) < 24 or admin_token.startswith("replace-"):
            raise ValueError("Set AGENTVERSE_ADMIN_TOKEN (or legacy AGENTCOMMONS_ADMIN_TOKEN) to a random secret of at least 24 characters.")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.admin_hash = hashlib.sha256(admin_token.encode()).hexdigest()
        self.admin_sessions = {}
        self.login_attempts = {}
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
                repo_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, kind TEXT NOT NULL, capabilities TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'offline',
                last_seen REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                title TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL,
                kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'backlog',
                assignee_id TEXT REFERENCES agents(id), reviewer_id TEXT REFERENCES agents(id),
                dependencies TEXT NOT NULL DEFAULT '[]', branch TEXT, commit_sha TEXT,
                summary TEXT, diff TEXT, integration_sha TEXT, created_by TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                sender_id TEXT NOT NULL, recipient_id TEXT, channel TEXT NOT NULL,
                content TEXT NOT NULL, task_id TEXT, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                title TEXT NOT NULL, content TEXT NOT NULL, tags TEXT NOT NULL,
                author_id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                task_id TEXT NOT NULL REFERENCES tasks(id), reviewer_id TEXT NOT NULL,
                decision TEXT NOT NULL, comment TEXT NOT NULL, commit_sha TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id),
                kind TEXT NOT NULL, actor_id TEXT NOT NULL, subject_id TEXT NOT NULL,
                detail TEXT NOT NULL, recipient_id TEXT, created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_project ON events(project_id, id);
            CREATE INDEX IF NOT EXISTS tasks_project ON tasks(project_id, status);
            CREATE INDEX IF NOT EXISTS messages_project ON messages(project_id, created_at);
        """)
        if "revoked" not in {row["name"] for row in self.db.execute("PRAGMA table_info(agents)")}:
            self.db.execute("ALTER TABLE agents ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")
        self.runtimes = RuntimeRegistry(self, admin_token)
        self.team = TeamRegistry(self)

    def close(self):
        with self.lock:
            self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def one(self, sql, args=()):
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def authenticate(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            fail(401, "A bearer token is required.")
        token = authorization[7:]
        now = time.time()
        session = self.admin_sessions.get(token)
        if session:
            if isinstance(session, tuple):
                expires, credential_fingerprint = session
            else:
                expires, credential_fingerprint = session, self.admin_credential_fingerprint()
            if expires >= now and credential_fingerprint == self.admin_credential_fingerprint():
                return Principal()
            self.admin_sessions.pop(token, None)
        digest = hashlib.sha256(token.encode()).hexdigest()
        if secrets.compare_digest(digest, self.admin_hash):
            return Principal()
        managed = self.runtimes.authenticate_runtime(token)
        if managed:
            return Principal(*managed)
        agent = self.one("SELECT id, project_id FROM agents WHERE token_hash=? AND revoked=0", (digest,))
        if not agent:
            fail(401, "Invalid or revoked token.")
        runtime = self.runtimes.runtime(agent["id"])
        if runtime and runtime["state"] in ACTIVE_STATES:
            fail(401, "This identity has a managed run. Its worker uses a run-scoped token; connect other sessions as a separate teammate.")
        return Principal(agent["id"], agent["project_id"])

    @staticmethod
    def admin_credentials():
        username = setting("ADMIN_USERNAME")
        password = setting("ADMIN_PASSWORD")
        return (username, password) if username and password else None

    def admin_credential_fingerprint(self):
        credentials = self.admin_credentials()
        if not credentials:
            return None
        return hashlib.sha256("\0".join(credentials).encode("utf-8")).hexdigest()

    def admin_session(self, username, password, client_id="unknown"):
        credentials = self.admin_credentials()
        if not credentials:
            fail(503, "Password login is not configured. Use an administrator or agent access token.")
        configured_username, configured_password = credentials
        now = time.time()
        key = (client_id, username)
        attempts = [stamp for stamp in self.login_attempts.get(key, []) if now - stamp < 60]
        if len(attempts) >= 10:
            self.login_attempts[key] = attempts
            fail(429, "Too many login attempts. Try again in a minute.")
        valid = hmac.compare_digest(username.encode("utf-8"), configured_username.encode("utf-8")) and hmac.compare_digest(
            password.encode("utf-8"), configured_password.encode("utf-8")
        )
        if not valid:
            attempts.append(now)
            self.login_attempts[key] = attempts
            fail(401, "Invalid user ID or password.")
        self.login_attempts.pop(key, None)
        for token, (expires, _) in list(self.admin_sessions.items()):
            if expires < now:
                self.admin_sessions.pop(token, None)
        token = f"web_{secrets.token_urlsafe(32)}"
        self.admin_sessions[token] = (now + 86400, self.admin_credential_fingerprint())
        return {"token": token, "expires_in": 86400, "username": configured_username}

    def revoke_session(self, authorization):
        if authorization and authorization.startswith("Bearer "):
            self.admin_sessions.pop(authorization[7:], None)
        return {"ok": True}

    def admin_only(self, principal):
        if not principal.admin:
            fail(403, "This action requires a workspace administrator.")

    def project(self, principal, project_id, active=False):
        if not principal.admin and principal.project_id != project_id:
            fail(403, "This agent belongs to a different project.")
        project = self.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            fail(404, "Project not found.")
        if active and project["status"] != "active":
            fail(409, "This project is paused.")
        return project

    def event(self, project_id, kind, principal, subject, detail, recipient=None):
        self.db.execute(
            "INSERT INTO events(project_id,kind,actor_id,subject_id,detail,recipient_id,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (project_id, kind, principal.actor, subject, detail, recipient, time.time()),
        )

    def projects(self, principal):
        if principal.admin:
            return self.all("SELECT * FROM projects ORDER BY created_at DESC")
        return self.all("SELECT * FROM projects WHERE id=?", (principal.project_id,))

    def create_project(self, principal, data: ProjectCreate):
        self.admin_only(principal)
        with self.transaction():
            project_id = uid("prj")
            self.db.execute(
                "INSERT INTO projects(id,name,goal,repo_url,created_at) VALUES(?,?,?,?,?)",
                (project_id, data.name, data.goal, data.repo_url, time.time()),
            )
            self.event(project_id, "project.created", principal, project_id, f"Created {data.name}")
            if data.auto_plan:
                self._create_task(principal, project_id, TaskCreate(
                    title="Break the project goal into a team plan",
                    description=data.goal,
                    priority="high",
                    kind="planning",
                ))
        return self.project(principal, project_id)

    def set_project_status(self, principal, project_id, status):
        self.admin_only(principal)
        with self.transaction():
            self.project(principal, project_id)
            self.db.execute("UPDATE projects SET status=? WHERE id=?", (status, project_id))
            self.event(project_id, "project.status", principal, project_id, f"Project {status}")
        return self.project(principal, project_id)

    def add_agent(self, principal, project_id, data: AgentCreate):
        self.admin_only(principal)
        token = f"ac_{secrets.token_urlsafe(32)}"
        agent_id = uid("agt")
        with self.transaction():
            self.project(principal, project_id)
            self.db.execute(
                "INSERT INTO agents(id,project_id,name,kind,capabilities,token_hash,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (agent_id, project_id, data.name, data.kind, json.dumps(data.capabilities),
                 hashlib.sha256(token.encode()).hexdigest(), time.time()),
            )
            self.db.execute("UPDATE agents SET description=?,limitations=? WHERE id=?",
                            (data.description, json.dumps(data.limitations), agent_id))
            self.event(project_id, "agent.joined", principal, agent_id, f"{data.name} joined the team")
        return {"agent": self.agent(principal, project_id, agent_id), "token": token}

    def agent(self, principal, project_id, agent_id):
        self.project(principal, project_id)
        row = self.one("SELECT * FROM agents WHERE id=? AND project_id=?", (agent_id, project_id))
        if not row:
            fail(404, "Agent not found.")
        row.pop("token_hash")
        row["capabilities"] = json.loads(row["capabilities"])
        row["limitations"] = json.loads(row["limitations"])
        row["session_info"] = json.loads(row["session_info"])
        row["configured_capabilities"] = list(row["capabilities"])
        row["configured_limitations"] = list(row["limitations"])
        row["capabilities"] = list(dict.fromkeys(row["capabilities"] + row["session_info"].get("capabilities", [])))
        row["limitations"] = list(dict.fromkeys(row["limitations"] + row["session_info"].get("limitations", [])))
        row["online"] = row["status"] != "offline" and time.time() - row["last_seen"] < 90
        row["revoked"] = bool(row["revoked"])
        row["runtime"] = self.runtimes.runtime(agent_id)
        if row["runtime"] and row["runtime"]["state"] in ACTIVE_STATES:
            row["online"] = row["online"] and self.runtimes.node(project_id, row["runtime"]["node_id"])["online"]
        return row

    def rotate_agent_token(self, principal, project_id, agent_id):
        self.admin_only(principal)
        token = f"ac_{secrets.token_urlsafe(32)}"
        with self.transaction():
            self.agent(principal, project_id, agent_id)
            runtime = self.runtimes.runtime(agent_id)
            if runtime and runtime["state"] in ACTIVE_STATES or self.one(
                "SELECT id FROM tasks WHERE (assignee_id=? AND status='in_progress') OR (reviewer_id=? AND status='review')",
                 (agent_id, agent_id)) or self.one("SELECT id FROM help_requests WHERE assignee_id=? AND state='in_progress'", (agent_id,)):
                fail(409, "Stop or release this teammate's current work before rotating its connection token.")
            self.db.execute("UPDATE agents SET token_hash=?,revoked=0,status='offline' WHERE id=?",
                            (hashlib.sha256(token.encode()).hexdigest(), agent_id))
            self.event(project_id, "agent.token_rotated", principal, agent_id, "Rotated teammate connection token")
        return {"agent": self.agent(principal, project_id, agent_id), "token": token}

    def revoke_agent(self, principal, project_id, agent_id):
        self.admin_only(principal)
        with self.transaction():
            self.agent(principal, project_id, agent_id)
            self.db.execute("UPDATE agents SET token_hash=?,status='offline',revoked=1 WHERE id=?",
                             (hashlib.sha256(secrets.token_bytes(32)).hexdigest(), agent_id))
            runtime = self.runtimes.runtime(agent_id)
            if runtime and runtime["state"] in ACTIVE_STATES:
                self.runtimes.stop_locked(principal, runtime)
            else:
                self.db.execute(
                    "UPDATE tasks SET status='backlog',assignee_id=NULL,updated_at=? "
                    "WHERE assignee_id=? AND status='in_progress'", (time.time(), agent_id))
                self.db.execute("UPDATE tasks SET reviewer_id=NULL WHERE reviewer_id=?", (agent_id,))
                self.db.execute("UPDATE help_requests SET assignee_id=NULL,state='open' WHERE assignee_id=? AND state='in_progress'", (agent_id,))
            self.event(project_id, "agent.revoked", principal, agent_id, "Agent access revoked")
        return {"ok": True}

    def heartbeat(self, principal, status):
        if principal.admin:
            fail(400, "Use an agent token to send a heartbeat.")
        with self.transaction():
            self.db.execute("UPDATE agents SET last_seen=?,status=? WHERE id=?",
                            (time.time(), status, principal.agent_id))
        runtime = self.runtimes.runtime(principal.agent_id) if principal.run_id else None
        return {"ok": True, "agent_id": principal.agent_id, "project_id": principal.project_id,
                "stop_requested": bool(runtime and runtime["desired_state"] == "stopped")}

    def _message(self, principal, project_id, data: MessageCreate):
        self.project(principal, project_id)
        if data.recipient_id and data.recipient_id != "human":
            self.agent(principal, project_id, data.recipient_id)
        if data.task_id:
            self.task(principal, project_id, data.task_id)
        message_id = uid("msg")
        self.db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
                        (message_id, project_id, principal.actor, data.recipient_id, data.channel,
                         data.content, data.task_id, time.time()))
        self.event(project_id, "message.sent", principal, message_id, data.content[:160], data.recipient_id)
        return message_id

    def message(self, principal, project_id, data: MessageCreate):
        with self.transaction():
            message_id = self._message(principal, project_id, data)
        return self.one("SELECT * FROM messages WHERE id=?", (message_id,))

    def visible_sql(self, principal):
        # Admin is a participant named human, not an observer of other agents' DMs.
        return "(recipient_id IS NULL OR recipient_id=? OR sender_id=?)", (principal.actor, principal.actor)

    def messages(self, principal, project_id, limit=100):
        self.project(principal, project_id)
        where, args = self.visible_sql(principal)
        return list(reversed(self.all(
            f"SELECT * FROM messages WHERE project_id=? AND {where} ORDER BY created_at DESC LIMIT ?",
            (project_id, *args, limit),
        )))

    def dependencies(self, project_id, ids, task_id=None):
        if len(ids) != len(set(ids)):
            fail(422, "Dependencies must be unique.")
        for dep_id in ids:
            dep = self.one("SELECT * FROM tasks WHERE id=? AND project_id=?", (dep_id, project_id))
            if not dep:
                fail(422, "Every dependency must belong to this project.")
            visited = set()
            pending = [dep_id]
            while pending:
                current = pending.pop()
                if current == task_id:
                    fail(422, "Task dependencies cannot contain a cycle.")
                if current not in visited:
                    visited.add(current)
                    row = self.one("SELECT dependencies FROM tasks WHERE id=?", (current,))
                    if row:
                        pending.extend(json.loads(row["dependencies"]))

    def _create_task(self, principal, project_id, data: TaskCreate):
        self.dependencies(project_id, data.dependencies)
        task_id, now = uid("tsk"), time.time()
        self.db.execute(
            "INSERT INTO tasks(id,project_id,title,description,priority,kind,dependencies,"
            "created_by,created_at,updated_at,required_capabilities) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, project_id, data.title, data.description, data.priority, data.kind,
             json.dumps(data.dependencies), principal.actor, now, now, json.dumps(data.required_capabilities)),
        )
        self.event(project_id, "task.created", principal, task_id, data.title)
        return task_id

    def create_task(self, principal, project_id, data: TaskCreate):
        with self.transaction():
            self.project(principal, project_id, active=True)
            task_id = self._create_task(principal, project_id, data)
        return self.task(principal, project_id, task_id)

    def task(self, principal, project_id, task_id):
        self.project(principal, project_id)
        task = self.one("SELECT * FROM tasks WHERE id=? AND project_id=?", (task_id, project_id))
        if not task:
            fail(404, "Task not found.")
        task["dependencies"] = json.loads(task["dependencies"])
        task["required_capabilities"] = json.loads(task["required_capabilities"])
        task["blocked"] = any(
            self.one("SELECT status FROM tasks WHERE id=?", (dep,))["status"] != "done"
            for dep in task["dependencies"]
        )
        return task

    def tasks(self, principal, project_id):
        self.project(principal, project_id)
        ids = self.all("SELECT id FROM tasks WHERE project_id=? ORDER BY created_at", (project_id,))
        return [self.task(principal, project_id, row["id"]) for row in ids]

    def edit_task(self, principal, project_id, task_id, data):
        self.admin_only(principal)
        with self.transaction():
            task = self.task(principal, project_id, task_id)
            if task["status"] != "backlog":
                fail(409, "Only unclaimed tasks can be edited.")
            updates = data.model_dump(exclude_none=True)
            if "dependencies" in updates:
                self.dependencies(project_id, updates["dependencies"], task_id)
                updates["dependencies"] = json.dumps(updates["dependencies"])
            for key, value in updates.items():
                if key == "required_capabilities":
                    value = json.dumps(value)
                self.db.execute(f"UPDATE tasks SET {key}=?,updated_at=? WHERE id=?",
                                (value, time.time(), task_id))
            self.event(project_id, "task.updated", principal, task_id, task["title"])
        return self.task(principal, project_id, task_id)

    def claim_task(self, principal, project_id, task_id):
        if principal.admin:
            fail(403, "Only an agent can claim a task.")
        with self.transaction():
            self.project(principal, project_id, active=True)
            self.runtimes.can_claim(principal)
            task = self.task(principal, project_id, task_id)
            if task["status"] != "backlog" or task["blocked"]:
                fail(409, "This task is already claimed or has unfinished dependencies.")
            peer = self.agent(principal, project_id, principal.agent_id)
            if not set(task["required_capabilities"]).issubset(peer["capabilities"]):
                fail(409, "This task requires capabilities not advertised by this teammate.")
            if self.one("SELECT id FROM tasks WHERE assignee_id=? AND status='in_progress'",
                        (principal.agent_id,)):
                fail(409, "Finish or release your current task first.")
            self.db.execute("UPDATE tasks SET status='in_progress',assignee_id=?,updated_at=? WHERE id=?",
                            (principal.agent_id, time.time(), task_id))
            self.event(project_id, "task.claimed", principal, task_id, task["title"])
        return self.task(principal, project_id, task_id)

    def owned_task(self, principal, project_id, task_id, status):
        task = self.task(principal, project_id, task_id)
        if principal.admin or task["assignee_id"] != principal.agent_id:
            fail(403, "Only the assigned agent can submit this task.")
        if task["status"] != status:
            fail(409, f"This task must be {status}.")
        return task

    def release_task(self, principal, project_id, task_id, reason):
        with self.transaction():
            task = self.task(principal, project_id, task_id)
            if not principal.admin and task["assignee_id"] != principal.agent_id:
                fail(403, "Only the assignee or an administrator can release a task.")
            if task["status"] != "in_progress":
                fail(409, "Only in-progress tasks can be released.")
            runtime = self.runtimes.runtime(task["assignee_id"])
            if principal.admin and runtime and runtime["state"] in ACTIVE_STATES:
                fail(409, "Stop the managed worker and wait for its termination report before releasing this task.")
            self.runtimes.release_allowed(task["assignee_id"])
            self.db.execute("UPDATE tasks SET status='backlog',assignee_id=NULL,updated_at=? WHERE id=?",
                            (time.time(), task_id))
            self.event(project_id, "task.released", principal, task_id, reason)
        return self.task(principal, project_id, task_id)

    def finish_plan(self, principal, project_id, task_id, data: PlanFinish):
        with self.transaction():
            # Pausing blocks new claims, but an already-owned task may finish safely.
            self.project(principal, project_id)
            self.runtimes.can_claim(principal)
            task = self.owned_task(principal, project_id, task_id, "in_progress")
            if task["kind"] != "planning":
                fail(422, "This is not a planning task.")
            ids = []
            for index, item in enumerate(data.tasks):
                if any(dep < 0 or dep >= index for dep in item.depends_on):
                    fail(422, "Plan dependencies must reference earlier task indices (zero-based).")
                resolved = item.model_copy(update={
                    "dependencies": item.dependencies + [ids[dep] for dep in item.depends_on]})
                ids.append(self._create_task(principal, project_id, resolved))
            self.db.execute("UPDATE tasks SET status='done',summary=?,updated_at=? WHERE id=?",
                            (data.summary, time.time(), task_id))
            self.event(project_id, "plan.completed", principal, task_id, data.summary[:160])
        return {"task": self.task(principal, project_id, task_id), "created_task_ids": ids}

    def submit_work(self, principal, project_id, task_id, data):
        with self.transaction():
            # Pausing blocks new claims, but an already-owned task may finish safely.
            self.project(principal, project_id)
            self.runtimes.can_claim(principal)
            task = self.owned_task(principal, project_id, task_id, "in_progress")
            if task["kind"] != "implementation":
                fail(422, "Finish a planning task with a team plan.")
            self.db.execute(
                "UPDATE tasks SET status='review',summary=?,branch=?,commit_sha=?,diff=?,"
                "reviewer_id=NULL,updated_at=?,revision=revision+1 WHERE id=?",
                (data.summary, data.branch, data.commit_sha, data.diff, time.time(), task_id),
            )
            self.event(project_id, "work.submitted", principal, task_id, task["title"])
        return self.task(principal, project_id, task_id)

    def claim_review(self, principal, project_id, task_id):
        if principal.admin:
            fail(403, "Only an agent can claim a peer review.")
        with self.transaction():
            self.project(principal, project_id, active=True)
            self.runtimes.can_claim(principal)
            task = self.task(principal, project_id, task_id)
            if task["assignee_id"] == principal.agent_id:
                fail(403, "Ask a teammate to review your work.")
            if task["status"] != "review" or task["reviewer_id"]:
                fail(409, "This review is unavailable.")
            if self.one("SELECT id FROM tasks WHERE reviewer_id=? AND status='review'", (principal.agent_id,)):
                fail(409, "Finish your current review first.")
            self.db.execute("UPDATE tasks SET reviewer_id=?,updated_at=? WHERE id=?",
                            (principal.agent_id, time.time(), task_id))
            self.event(project_id, "review.claimed", principal, task_id, task["title"])
        return self.task(principal, project_id, task_id)

    def release_review(self, principal, project_id, task_id):
        with self.transaction():
            task = self.task(principal, project_id, task_id)
            if not principal.admin and task["reviewer_id"] != principal.agent_id:
                fail(403, "Only the reviewer or an administrator can release this review.")
            if task["status"] != "review":
                fail(409, "This task is not in review.")
            self.runtimes.release_allowed(task["reviewer_id"])
            self.db.execute("UPDATE tasks SET reviewer_id=NULL,updated_at=? WHERE id=?", (time.time(), task_id))
            self.event(project_id, "review.released", principal, task_id, task["title"])
        return self.task(principal, project_id, task_id)

    def review_work(self, principal, project_id, task_id, data):
        with self.transaction():
            # Pausing blocks new claims, but an already-owned review may finish safely.
            self.project(principal, project_id)
            self.runtimes.can_claim(principal)
            task = self.task(principal, project_id, task_id)
            if principal.admin or task["reviewer_id"] != principal.agent_id:
                fail(403, "Claim this peer review before submitting a decision.")
            if task["status"] != "review":
                fail(409, "This work is no longer awaiting review.")
            review_id = uid("rev")
            self.db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?)",
                            (review_id, project_id, task_id, principal.agent_id, data.decision,
                             data.comment, task["commit_sha"], time.time()))
            status = "done" if data.decision == "approve" else "backlog"
            # Changes become a new claimable task; the submitted branch remains available as context.
            self.db.execute(
                "UPDATE tasks SET status=?,assignee_id=CASE WHEN ?='backlog' THEN NULL ELSE assignee_id END,"
                "reviewer_id=NULL,integration_sha=?,updated_at=? WHERE id=?",
                (status, status, data.integration_sha if status == "done" else None, time.time(), task_id))
            self.event(project_id, "review.completed", principal, task_id, f"{data.decision}: {data.comment[:120]}")
        return self.task(principal, project_id, task_id)

    def memories(self, principal, project_id):
        self.project(principal, project_id)
        rows = self.all("SELECT * FROM memories WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
        for row in rows:
            row["tags"] = json.loads(row["tags"])
        return rows

    def write_memory(self, principal, project_id, data: MemoryWrite, memory_id=None):
        with self.transaction():
            self.project(principal, project_id, active=True)
            if memory_id:
                existing = self.one("SELECT * FROM memories WHERE id=? AND project_id=?", (memory_id, project_id))
                if not existing:
                    fail(404, "Memory not found.")
                if data.expected_version != existing["version"]:
                    fail(409, "Memory changed. Read the latest version before updating it.")
                self.db.execute(
                    "UPDATE memories SET title=?,content=?,tags=?,author_id=?,version=version+1,"
                    "updated_at=? WHERE id=?",
                    (data.title, data.content, json.dumps(data.tags), principal.actor, time.time(), memory_id),
                )
            else:
                memory_id = uid("mem")
                self.db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)",
                                (memory_id, project_id, data.title, data.content, json.dumps(data.tags),
                                 principal.actor, 1, time.time()))
            self.event(project_id, "memory.updated", principal, memory_id, data.title)
        return next(row for row in self.memories(principal, project_id) if row["id"] == memory_id)

    def events(self, principal, project_id, after=0, limit=100):
        self.project(principal, project_id)
        return self.all(
            "SELECT * FROM events WHERE project_id=? AND id>? AND "
            "(recipient_id IS NULL OR recipient_id=? OR actor_id=?) ORDER BY id LIMIT ?",
            (project_id, after, principal.actor, principal.actor, limit),
        )

    def snapshot(self, principal, project_id):
        with self.lock:
            project = self.project(principal, project_id)
            agents = [self.agent(principal, project_id, item["id"]) for item in self.all(
                "SELECT id FROM agents WHERE project_id=? ORDER BY created_at", (project_id,))]
            events = list(reversed(self.all(
                "SELECT * FROM events WHERE project_id=? AND "
                "(recipient_id IS NULL OR recipient_id=? OR actor_id=?) ORDER BY id DESC LIMIT 50",
                (project_id, principal.actor, principal.actor))))
            return {
                "project": project, "agents": agents, "nodes": self.runtimes.nodes(principal, project_id),
                "issues": self.team.issues(principal, project_id), "help_requests": self.team.help_requests(principal, project_id),
                "tasks": self.tasks(principal, project_id),
                "messages": self.messages(principal, project_id), "memories": self.memories(principal, project_id),
                "reviews": self.all("SELECT * FROM reviews WHERE project_id=? ORDER BY created_at DESC",
                                    (project_id,)),
                "events": events[-50:], "cursor": events[-1]["id"] if events else 0,
                "identity": {"actor_id": principal.actor, "admin": principal.admin},
            }
