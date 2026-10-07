"""Peer discovery, explicit capabilities, per-agent health, and durable help requests."""

import json
import time
import uuid

from fastapi import HTTPException

from .config import PROTOCOL_VERSION
from .models import MessageCreate


def fail(code, detail):
    raise HTTPException(code, detail)


class TeamRegistry:
    def __init__(self, store):
        self.store = store
        columns = {row["name"] for row in store.db.execute("PRAGMA table_info(agents)")}
        for key, declaration in {"description": "TEXT NOT NULL DEFAULT ''", "limitations": "TEXT NOT NULL DEFAULT '[]'",
                                 "profile_version": "INTEGER NOT NULL DEFAULT 1", "session_info": "TEXT NOT NULL DEFAULT '{}'"}.items():
            if key not in columns:
                store.db.execute(f"ALTER TABLE agents ADD COLUMN {key} {declaration}")
        columns = {row["name"] for row in store.db.execute("PRAGMA table_info(tasks)")}
        if "required_capabilities" not in columns:
            store.db.execute("ALTER TABLE tasks ADD COLUMN required_capabilities TEXT NOT NULL DEFAULT '[]'")
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS agent_issues (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                agent_id TEXT NOT NULL REFERENCES agents(id), severity TEXT NOT NULL, title TEXT NOT NULL,
                detail TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS help_requests (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                sender_id TEXT NOT NULL, capability TEXT NOT NULL, question TEXT NOT NULL, task_id TEXT,
                recipient_id TEXT, assignee_id TEXT, state TEXT NOT NULL DEFAULT 'open',
                answer TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS help_project ON help_requests(project_id,state);
        """)

    def peers(self, principal, project_id, capability=""):
        self.store.project(principal, project_id)
        agents = [self.store.agent(principal, project_id, row["id"]) for row in self.store.all(
            "SELECT id FROM agents WHERE project_id=? ORDER BY name", (project_id,))]
        return [agent for agent in agents if not agent["revoked"] and (not capability or capability in agent["capabilities"])]

    def edit(self, principal, project_id, agent_id, data):
        self.store.admin_only(principal)
        with self.store.transaction():
            agent = self.store.agent(principal, project_id, agent_id)
            if data.expected_version != agent["profile_version"]:
                fail(409, "This teammate's profile changed. Reload it before saving your edits.")
            self.store.db.execute("UPDATE agents SET name=?,description=?,capabilities=?,limitations=?,"
                                  "profile_version=profile_version+1 WHERE id=?",
                                  (data.name, data.description, json.dumps(list(dict.fromkeys(data.capabilities))),
                                   json.dumps(data.limitations), agent_id))
            self.store.event(project_id, "agent.profile", principal, agent_id, f"Updated {data.name}'s capabilities and profile")
        return self.store.agent(principal, project_id, agent_id)

    def announce(self, principal, data):
        if principal.admin:
            fail(403, "Announce with a teammate's own token.")
        if data.protocol_version != PROTOCOL_VERSION:
            fail(426, f"Unsupported peer protocol; AgentVerse supports version {PROTOCOL_VERSION}.")
        with self.store.transaction():
            self.store.db.execute("UPDATE agents SET session_info=?,last_seen=?,status='idle' WHERE id=?",
                                  (data.model_dump_json(), time.time(), principal.agent_id))
            self.store.event(principal.project_id, "agent.announced", principal, principal.agent_id,
                             f"Connected through {data.connection} · protocol {PROTOCOL_VERSION}")
        return {"agent": self.store.agent(principal, principal.project_id, principal.agent_id),
                "peers": self.peers(principal, principal.project_id), "protocol_version": PROTOCOL_VERSION,
                "heartbeat_seconds": 25}

    def issues(self, principal, project_id):
        self.store.project(principal, project_id)
        return self.store.all("SELECT * FROM agent_issues WHERE project_id=? ORDER BY created_at DESC LIMIT 100", (project_id,))

    def issue(self, principal, project_id, agent_id, data):
        with self.store.transaction():
            self.store.agent(principal, project_id, agent_id)
            if not principal.admin and principal.agent_id != agent_id:
                fail(403, "Report issues for your own identity.")
            issue_id = f"issue_{uuid.uuid4().hex[:16]}"
            self.store.db.execute("INSERT INTO agent_issues VALUES(?,?,?,?,?,?,0,?)",
                                  (issue_id, project_id, agent_id, data.severity, data.title, data.detail, time.time()))
            self.store.event(project_id, "agent.issue", principal, agent_id, data.title)
        return self.store.one("SELECT * FROM agent_issues WHERE id=?", (issue_id,))

    def resolve(self, principal, project_id, issue_id):
        with self.store.transaction():
            self.store.project(principal, project_id)
            row = self.store.one("SELECT * FROM agent_issues WHERE id=? AND project_id=?", (issue_id, project_id))
            if not row:
                fail(404, "Issue not found.")
            if not principal.admin and principal.agent_id != row["agent_id"]:
                fail(403, "Resolve issues for your own identity.")
            self.store.db.execute("UPDATE agent_issues SET resolved=1 WHERE id=?", (issue_id,))
            self.store.event(project_id, "agent.issue_resolved", principal, row["agent_id"], row["title"])
        return {"ok": True}

    def help_requests(self, principal, project_id):
        self.store.project(principal, project_id)
        return self.store.all("SELECT * FROM help_requests WHERE project_id=? ORDER BY created_at DESC LIMIT 100", (project_id,))

    def ask(self, principal, project_id, data):
        with self.store.transaction():
            self.store.project(principal, project_id)
            if data.task_id:
                self.store.task(principal, project_id, data.task_id)
            candidates = [a for a in self.peers(principal, project_id, data.capability) if a["id"] != principal.actor]
            candidates.sort(key=lambda a: (not a["online"], a["status"] == "working", a["name"]))
            recipient = candidates[0]["id"] if candidates else None
            help_id, now = f"help_{uuid.uuid4().hex[:16]}", time.time()
            self.store.db.execute("INSERT INTO help_requests(id,project_id,sender_id,capability,question,task_id,"
                                  "recipient_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (help_id, project_id, principal.actor, data.capability, data.question, data.task_id, recipient, now, now))
            self.store.event(project_id, "help.requested", principal, help_id,
                             f"Asked the team for {data.capability or 'general'} help: {data.question[:100]}")
            self.store._message(principal, project_id, MessageCreate(
                content=f"I could use a teammate’s {data.capability or 'general'} help: {data.question}", task_id=data.task_id))
        return self.store.one("SELECT * FROM help_requests WHERE id=?", (help_id,))

    def claim_help(self, principal, project_id, help_id):
        if principal.admin:
            fail(403, "A teammate must claim this request.")
        with self.store.transaction():
            self.store.project(principal, project_id, active=True)
            self.store.runtimes.can_claim(principal)
            row = self.store.one("SELECT * FROM help_requests WHERE id=? AND project_id=?", (help_id, project_id))
            if not row:
                fail(404, "Help request not found.")
            if row["state"] != "open" or row["sender_id"] == principal.actor:
                fail(409, "This request is unavailable for this teammate.")
            peer = self.store.agent(principal, project_id, principal.agent_id)
            if row["capability"] and row["capability"] not in peer["capabilities"]:
                fail(409, "This request needs a different capability.")
            if self.store.one("SELECT id FROM help_requests WHERE assignee_id=? AND state='in_progress'", (principal.agent_id,)):
                fail(409, "Finish your current help request first.")
            self.store.db.execute("UPDATE help_requests SET assignee_id=?,state='in_progress',updated_at=? WHERE id=?",
                                  (principal.agent_id, time.time(), help_id))
        return self.store.one("SELECT * FROM help_requests WHERE id=?", (help_id,))

    def answer(self, principal, project_id, help_id, data):
        with self.store.transaction():
            self.store.project(principal, project_id)
            row = self.store.one("SELECT * FROM help_requests WHERE id=? AND project_id=?", (help_id, project_id))
            if not row:
                fail(404, "Help request not found.")
            if principal.admin or row["assignee_id"] != principal.agent_id or row["state"] != "in_progress":
                fail(403, "Claim this request before answering it.")
            self.store.db.execute("UPDATE help_requests SET state='answered',answer=?,updated_at=? WHERE id=?",
                                  (data.answer, time.time(), help_id))
            self.store.event(project_id, "help.answered", principal, help_id, data.answer[:160])
            self.store._message(principal, project_id, MessageCreate(content=data.answer, task_id=row["task_id"]))
        return self.store.one("SELECT * FROM help_requests WHERE id=?", (help_id,))

    def release_help(self, principal, project_id, help_id):
        with self.store.transaction():
            self.store.project(principal, project_id)
            row = self.store.one("SELECT * FROM help_requests WHERE id=? AND project_id=?", (help_id, project_id))
            if not row or row["state"] != "in_progress":
                fail(409, "This request is not claimed.")
            if not principal.admin and row["assignee_id"] != principal.agent_id:
                fail(403, "Only its owner can release this help request.")
            self.store.runtimes.release_allowed(row["assignee_id"])
            self.store.db.execute("UPDATE help_requests SET assignee_id=NULL,state='open',updated_at=? WHERE id=?",
                                  (time.time(), help_id))
        return {"ok": True}
