"""Durable desired state and leased, project-scoped remote-node sessions."""

import hashlib
import hmac
import json
import secrets
import time
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from .config import PROTOCOL_VERSION
from .models import validate_settings, RuntimeProfile

NODE_LEASE_SECONDS = 45
NODE_TAKEOVER_SECONDS = 90
ACTIVE_STATES = {"queued", "starting", "running", "stopping", "unconfirmed"}


def fail(code, detail):
    raise HTTPException(code, detail)


class RuntimeRegistry:
    def __init__(self, store, admin_token):
        self.store = store
        self.key = hashlib.sha256(("runtime:" + admin_token).encode()).digest()
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, profiles TEXT NOT NULL DEFAULT '[]',
                session_id TEXT, last_seen REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_runtimes (
                agent_id TEXT PRIMARY KEY REFERENCES agents(id),
                project_id TEXT NOT NULL REFERENCES projects(id), node_id TEXT NOT NULL REFERENCES nodes(id),
                profile_id TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                desired_state TEXT NOT NULL DEFAULT 'stopped', state TEXT NOT NULL DEFAULT 'stopped',
                run_id TEXT, pid INTEGER, error TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS runtimes_node ON agent_runtimes(node_id);
        """)
        for table, additions in {
            "nodes": {"diagnostics": "TEXT NOT NULL DEFAULT '[]'", "capacity": "INTEGER NOT NULL DEFAULT 4", "protocol_version": "INTEGER NOT NULL DEFAULT 1"},
            "agent_runtimes": {"settings": "TEXT NOT NULL DEFAULT '{}'", "mode": "TEXT NOT NULL DEFAULT 'managed_cli'"},
        }.items():
            existing = {row["name"] for row in store.db.execute(f"PRAGMA table_info({table})")}
            for key, definition in additions.items():
                if key not in existing:
                    store.db.execute(f"ALTER TABLE {table} ADD COLUMN {key} {definition}")

    def runtime(self, agent_id):
        row = self.store.one("SELECT * FROM agent_runtimes WHERE agent_id=?", (agent_id,))
        if row:
            row["settings"] = json.loads(row["settings"])
        return row

    def node(self, project_id, node_id):
        row = self.store.one("SELECT * FROM nodes WHERE id=? AND project_id=?", (node_id, project_id))
        if not row:
            fail(404, "Remote node not found in this project.")
        row.pop("token_hash")
        row.pop("session_id")
        row["profiles"] = [RuntimeProfile.model_validate(p).model_dump() for p in json.loads(row["profiles"])]
        row["diagnostics"] = json.loads(row["diagnostics"])
        row["online"] = time.time() - row["last_seen"] < NODE_LEASE_SECONDS
        return row

    def nodes(self, principal, project_id):
        self.store.project(principal, project_id)
        return [self.node(project_id, row["id"]) for row in self.store.all(
            "SELECT id FROM nodes WHERE project_id=? ORDER BY created_at", (project_id,))]

    def add_node(self, principal, project_id, data):
        self.store.admin_only(principal)
        node_id, token = f"node_{uuid.uuid4().hex[:16]}", f"acn_{secrets.token_urlsafe(32)}"
        with self.store.transaction():
            self.store.project(principal, project_id)
            self.store.db.execute(
                "INSERT INTO nodes(id,project_id,name,token_hash,created_at) VALUES(?,?,?,?,?)",
                (node_id, project_id, data.name, hashlib.sha256(token.encode()).hexdigest(), time.time()))
            self.store.event(project_id, "node.created", principal, node_id, f"Registered remote node {data.name}")
        return {"node": self.node(project_id, node_id), "token": token}

    def authenticate_node(self, authorization):
        if not authorization or not authorization.startswith("Bearer acn_"):
            fail(401, "Use the remote node's bearer token.")
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        node = self.store.one("SELECT * FROM nodes WHERE token_hash=?", (digest,))
        if not node:
            fail(401, "Invalid node token.")
        return node

    def _session(self, node, session_id):
        current = self.store.one("SELECT * FROM nodes WHERE id=?", (node["id"],))
        if current["session_id"] != session_id:
            fail(409, "This node session no longer owns the connection. Register again.")
        return current

    def register(self, node, data):
        if data.protocol_version != PROTOCOL_VERSION:
            fail(426, f"Unsupported node protocol. AgentVerse supports version {PROTOCOL_VERSION}.")
        with self.store.transaction():
            current = self.store.one("SELECT * FROM nodes WHERE id=?", (node["id"],))
            if current["session_id"] and current["session_id"] != data.session_id:
                if time.time() - current["last_seen"] < NODE_TAKEOVER_SECONDS:
                    fail(409, "Another service owns this node. Stop it, or wait 90 seconds after disconnection.")
                # The old connection and worker credentials have expired before takeover.
                for row in self.store.all("SELECT * FROM agent_runtimes WHERE node_id=?", (node["id"],)):
                    if row["state"] in ACTIVE_STATES:
                        if row["mode"] == "managed_api":
                            self._unconfirmed(row, "Previous API job needs cancellation confirmation from its adapter.")
                        else:
                            self._finished(row, "failed", "Previous node session disconnected.")
            self.store.db.execute("UPDATE nodes SET profiles=?,session_id=?,last_seen=? WHERE id=?",
                                  (json.dumps([p.model_dump() for p in data.profiles]), data.session_id,
                                   time.time(), node["id"]))
            self.store.db.execute("UPDATE nodes SET diagnostics=?,capacity=?,protocol_version=? WHERE id=?",
                                  (json.dumps([item.model_dump() for item in data.diagnostics]), data.capacity,
                                   data.protocol_version, node["id"]))
            self.store.event(node["project_id"], "node.connected", SimpleNamespace(actor=node["id"]), node["id"],
                             f"{node['name']} connected · {len(data.profiles)} runtime tools")
        return {"node": self.node(node["project_id"], node["id"]), "lease_seconds": NODE_LEASE_SECONDS}

    def refresh_inventory(self, node, data):
        self._session(node, data.session_id)
        return self.register(node, data)

    def _validate_config(self, project_id, agent_id, data):
        agent = self.store.one("SELECT * FROM agents WHERE id=? AND project_id=?", (agent_id, project_id))
        if not agent:
            fail(404, "Agent not found.")
        if agent["revoked"]:
            fail(409, "This agent's access was revoked. Invite a new teammate.")
        node = self.node(project_id, data.node_id)
        profile = next((p for p in node["profiles"] if p["id"] == data.profile_id), None)
        if not profile or not any(m["id"] == data.model for m in profile["models"]):
            fail(422, "Choose a tool and model advertised by this node.")
        if agent["kind"] != "custom" and agent["kind"] != profile["kind"]:
            fail(422, "The runtime tool must match this teammate's agent tool.")
        if profile.get("protocol_version", 1) != PROTOCOL_VERSION:
            fail(426, "This tool advertises an unsupported adapter protocol.")
        try:
            validate_settings(profile, data.settings)
        except ValueError as exc:
            fail(422, str(exc))
        return node

    def configure(self, principal, project_id, agent_id, data):
        self.store.admin_only(principal)
        with self.store.transaction():
            self.store.project(principal, project_id)
            node = self._validate_config(project_id, agent_id, data)
            profile = next(p for p in node["profiles"] if p["id"] == data.profile_id)
            current = self.runtime(agent_id)
            if current and current["state"] in ACTIVE_STATES:
                fail(409, "Stop the agent before changing its node, tool, or model.")
            values = validate_settings(profile, data.settings)
            self.store.db.execute(
                "INSERT INTO agent_runtimes(agent_id,project_id,node_id,profile_id,model,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET node_id=excluded.node_id,"
                "profile_id=excluded.profile_id,model=excluded.model,state='stopped',desired_state='stopped',"
                "run_id=NULL,pid=NULL,error='',updated_at=excluded.updated_at",
                (agent_id, project_id, data.node_id, data.profile_id, data.model, time.time()))
            self.store.db.execute("UPDATE agent_runtimes SET settings=?,mode=?,state=? WHERE agent_id=?",
                                  (json.dumps(values), profile.get("mode", "managed_cli"),
                                   "external" if profile.get("mode") == "connected" else "stopped", agent_id))
            agent = self.store.one("SELECT capabilities FROM agents WHERE id=?", (agent_id,))
            if not json.loads(agent["capabilities"]) and profile.get("capabilities"):
                self.store.db.execute("UPDATE agents SET capabilities=?,profile_version=profile_version+1 WHERE id=?",
                                      (json.dumps(profile["capabilities"]), agent_id))
            self.store.event(project_id, "runtime.configured", principal, agent_id,
                             f"Configured remote runtime · {data.model or 'tool default model'}")
        return self.runtime(agent_id)

    def launch(self, principal, project_id, agent_id):
        from .models import RuntimeConfig

        self.store.admin_only(principal)
        with self.store.transaction():
            self.store.project(principal, project_id, active=True)
            row = self.runtime(agent_id)
            if not row or row["project_id"] != project_id:
                fail(409, "Configure a remote node, tool, and model first.")
            node = self._validate_config(project_id, agent_id, RuntimeConfig(**row))
            profile = next(p for p in node["profiles"] if p["id"] == row["profile_id"])
            if row["mode"] == "connected":
                fail(409, "Start this session in its own client and connect it with MCP or HTTP.")
            if profile.get("availability", "available") != "available":
                fail(409, profile.get("diagnostic") or "This tool needs setup on its node before it can launch.")
            if row["state"] == "unconfirmed":
                fail(409, "The remote API adapter has not confirmed cancellation of its previous job.")
            if not node["online"]:
                fail(409, "The remote node is offline. Start its node service before launching an agent.")
            if row["state"] == "stopping":
                fail(409, "Wait for the previous process to stop before relaunching.")
            if row["state"] in {"queued", "starting", "running"}:
                return row
            agent = self.store.agent(principal, project_id, agent_id)
            if agent["online"] or self.store.one(
                "SELECT id FROM tasks WHERE (assignee_id=? AND status='in_progress') "
                "OR (reviewer_id=? AND status='review')", (agent_id, agent_id)):
                fail(409, "This teammate still has an external session or active claim. Stop/release it before launching.")
            self.store.db.execute(
                "UPDATE agent_runtimes SET desired_state='running',state='queued',run_id=?,pid=NULL,"
                "error='',updated_at=? WHERE agent_id=?",
                (f"run_{uuid.uuid4().hex}", time.time(), agent_id))
            self.store.event(project_id, "runtime.launch", principal, agent_id, "Requested remote agent launch")
        return self.runtime(agent_id)

    def stop_locked(self, principal, row):
        state = "unconfirmed" if row["state"] == "unconfirmed" else "stopping" if row["state"] in {"starting", "running", "stopping"} else "stopped"
        self.store.db.execute("UPDATE agent_runtimes SET desired_state='stopped',state=?,updated_at=? WHERE agent_id=?",
                              (state, time.time(), row["agent_id"]))
        self.store.event(row["project_id"], "runtime.stop", principal, row["agent_id"], "Requested remote agent stop")

    def stop(self, principal, project_id, agent_id):
        self.store.admin_only(principal)
        with self.store.transaction():
            self.store.project(principal, project_id)
            row = self.runtime(agent_id)
            if not row or row["project_id"] != project_id:
                fail(404, "Managed runtime not found.")
            if row["mode"] == "connected":
                fail(409, "This session is controlled by its own client; disconnect it there.")
            self.stop_locked(principal, row)
        return self.runtime(agent_id)

    def _token(self, row):
        digest = hmac.new(self.key, f"{row['agent_id']}:{row['run_id']}".encode(), hashlib.sha256).hexdigest()
        return f"acr_{row['run_id']}.{digest}"

    def authenticate_runtime(self, token):
        if not token.startswith("acr_") or "." not in token:
            return None
        run_id = token[4:].split(".", 1)[0]
        row = self.store.one(
            "SELECT r.*, n.last_seen, a.revoked FROM agent_runtimes r JOIN nodes n ON n.id=r.node_id "
            "JOIN agents a ON a.id=r.agent_id WHERE r.run_id=?", (run_id,))
        if not row or row["revoked"] or row["state"] not in {"starting", "running", "stopping"}:
            return None
        if time.time() - row["last_seen"] >= NODE_LEASE_SECONDS:
            return None
        if not secrets.compare_digest(token, self._token(row)):
            return None
        return row["agent_id"], row["project_id"], row["run_id"]

    def can_claim(self, principal):
        if principal.run_id:
            row = self.runtime(principal.agent_id)
            if not row or row["run_id"] != principal.run_id or row["desired_state"] != "running":
                fail(409, "This managed worker is stopping.")

    def release_allowed(self, agent_id):
        row = self.runtime(agent_id) if agent_id else None
        if row and row["state"] == "unconfirmed":
            fail(409, "The API job's cancellation is unconfirmed. Its claims stay held until the adapter confirms termination.")

    def poll(self, node, data):
        with self.store.transaction():
            self._session(node, data.session_id)
            self.store.db.execute("UPDATE nodes SET last_seen=? WHERE id=?", (time.time(), node["id"]))
            runtimes = []
            for row in self.store.all("SELECT * FROM agent_runtimes WHERE node_id=?", (node["id"],)):
                row["settings"] = json.loads(row["settings"])
                if row["state"] == "queued":
                    self.store.db.execute("UPDATE agent_runtimes SET state='starting',updated_at=? WHERE agent_id=?",
                                          (time.time(), row["agent_id"]))
                    row["state"] = "starting"
                if row["state"] in ACTIVE_STATES:
                    row["token"] = self._token(row) if row["desired_state"] == "running" else None
                    runtimes.append(row)
        return {"runtimes": runtimes, "lease_seconds": NODE_LEASE_SECONDS}

    def _unconfirmed(self, row, error):
        self.store.db.execute("UPDATE agent_runtimes SET state='unconfirmed',desired_state='stopped',pid=NULL,error=?,updated_at=? WHERE agent_id=?",
                              (error, time.time(), row["agent_id"]))
        self.store.db.execute("UPDATE agents SET status='offline' WHERE id=?", (row["agent_id"],))

    def _finished(self, row, state, error=""):
        self.store.db.execute(
            "UPDATE agent_runtimes SET state=?,desired_state='stopped',pid=NULL,error=?,updated_at=? WHERE agent_id=?",
            (state, error, time.time(), row["agent_id"]))
        self.store.db.execute("UPDATE agents SET status='offline' WHERE id=?", (row["agent_id"],))
        self.store.db.execute("UPDATE tasks SET status='backlog',assignee_id=NULL,updated_at=? "
                              "WHERE assignee_id=? AND status='in_progress'", (time.time(), row["agent_id"]))
        self.store.db.execute("UPDATE tasks SET reviewer_id=NULL WHERE reviewer_id=? AND status='review'",
                              (row["agent_id"],))
        self.store.db.execute("UPDATE help_requests SET assignee_id=NULL,state='open' WHERE assignee_id=? AND state='in_progress'", (row["agent_id"],))

    def report(self, node, data):
        with self.store.transaction():
            self._session(node, data.session_id)
            row = self.runtime(data.agent_id)
            if not row or row["node_id"] != node["id"] or row["run_id"] != data.run_id:
                fail(409, "Stale or foreign run report.")
            if row["state"] not in ACTIVE_STATES:
                if data.state not in {"stopped", "failed"}:
                    fail(409, "This run has already finished.")
                return row
            if data.state == "unconfirmed":
                if row["mode"] != "managed_api":
                    fail(422, "Unconfirmed cancellation is only valid for a remote API adapter.")
                state = "unconfirmed"
                self._unconfirmed(row, data.error or "The remote API adapter has not confirmed that its job ended.")
            elif data.state in {"stopped", "failed"}:
                # Called only after the node has reaped the process and its child process groups.
                state = "stopped" if row["desired_state"] == "stopped" else data.state
                self._finished(row, state, data.error)
            else:
                state = data.state if row["desired_state"] == "running" else "stopping"
                self.store.db.execute("UPDATE agent_runtimes SET state=?,pid=?,error='',updated_at=? WHERE agent_id=?",
                                      (state, data.pid, time.time(), data.agent_id))
            self.store.event(row["project_id"], "runtime.status", SimpleNamespace(actor=node["id"]),
                             data.agent_id, f"Remote agent {state}" + (f" · {data.error}" if data.error else ""))
        return self.runtime(data.agent_id)

    def disconnect(self, node, data):
        with self.store.transaction():
            self._session(node, data.session_id)
            if self.store.one("SELECT agent_id FROM agent_runtimes WHERE node_id=? AND state IN ('starting','running','stopping','unconfirmed')",
                              (node["id"],)):
                fail(409, "Stop and report all processes before disconnecting this node.")
            self.store.db.execute("UPDATE nodes SET session_id=NULL,last_seen=0 WHERE id=?", (node["id"],))
            self.store.event(node["project_id"], "node.disconnected", SimpleNamespace(actor=node["id"]), node["id"],
                             f"{node['name']} disconnected")
        return {"ok": True}
