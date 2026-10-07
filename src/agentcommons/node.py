"""Outbound-only remote supervisor. Commands and project paths stay on the node."""

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, model_validator

from .models import RuntimeProfile
from .orchestration import NODE_LEASE_SECONDS


class LocalProfile(RuntimeProfile):
    argv: list[str] = Field(min_length=1, max_length=100)
    base: str = Field(default="main", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    push: bool = True
    timeout: int = Field(default=1800, ge=1, le=86400)

    @model_validator(mode="after")
    def executable(self):
        if not self.argv[0].strip():
            raise ValueError("A profile needs a nonempty executable.")
        return self


class NodeConfig(BaseModel):
    repo: str = Field(min_length=1)
    profiles: list[LocalProfile] = Field(min_length=1, max_length=30)
    max_workers: int = Field(default=4, ge=1, le=32)
    log_dir: str = "~/.local/state/agentcommons/logs"

    @model_validator(mode="after")
    def unique_profiles(self):
        if len({p.id for p in self.profiles}) != len(self.profiles):
            raise ValueError("Profile IDs must be unique.")
        return self


@dataclass
class Child:
    run_id: str
    process: subprocess.Popen
    log: object


class NodeService:
    def __init__(self, server, token, config: NodeConfig, interval=3):
        self.server, self.config = server.rstrip("/"), config
        self.http = httpx.Client(base_url=self.server, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        self.repo = Path(config.repo).expanduser().resolve()
        self.logs = Path(config.log_dir).expanduser().resolve()
        self.profiles = {p.id: p for p in config.profiles}
        self.session_id = uuid.uuid4().hex
        self.interval, self.stop = interval, threading.Event()
        self.children: dict[str, Child] = {}
        self.pending_reports: dict[str, dict] = {}
        self.last_success = time.monotonic()

    def request(self, route, payload):
        response = self.http.post(f"/api/nodes/me/{route}", json={"session_id": self.session_id, **payload})
        response.raise_for_status()
        self.last_success = time.monotonic()
        return response.json()

    def register(self):
        check = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=self.repo, capture_output=True, timeout=10)
        if check.returncode:
            raise ValueError("The node repository must be an existing Git clone with an initial commit.")
        for profile in self.profiles.values():
            if not shutil.which(profile.argv[0]):
                raise ValueError(f"Profile {profile.id}: executable {profile.argv[0]} is not installed on this node.")
        self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.request("register", {"profiles": [
            RuntimeProfile(**profile.model_dump()).model_dump() for profile in self.profiles.values()]})

    def queue_report(self, row, state, pid=None, error=""):
        self.pending_reports[row["agent_id"]] = {
            "agent_id": row["agent_id"], "run_id": row["run_id"], "state": state, "pid": pid, "error": error[:2000]}

    def flush_reports(self):
        for agent_id, payload in list(self.pending_reports.items()):
            try:
                self.request("report", payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 409:
                    raise
                # An old generation cannot change a newer run's state.
            self.pending_reports.pop(agent_id, None)

    def launch(self, row):
        profile = self.profiles.get(row["profile_id"])
        if not profile or row["model"] not in {m.id for m in profile.models}:
            self.queue_report(row, "failed", error="This tool/model is no longer configured on the remote node.")
            return
        if len(self.children) >= self.config.max_workers:
            self.queue_report(row, "failed", error="Remote node worker capacity reached. Stop a worker and relaunch.")
            return
        argv = [sys.executable, "-m", "agentcommons.cli", "worker", "--server", self.server,
                "--repo", str(self.repo), "--command", shlex.join(profile.argv), "--base", profile.base,
                "--model", row["model"], "--timeout", str(profile.timeout)]
        if not profile.push:
            argv.append("--no-push")
        env = {**os.environ, "AGENTCOMMONS_AGENT_TOKEN": row["token"], "AGENTCOMMONS_MODEL": row["model"]}
        env.pop("AGENTCOMMONS_ADMIN_TOKEN", None)
        env.pop("AGENTCOMMONS_NODE_TOKEN", None)
        log_path = self.logs / f"{row['run_id']}.log"
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        log = os.fdopen(descriptor, "w")
        try:
            process = subprocess.Popen(argv, cwd=self.repo, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        except BaseException:
            log.close()
            raise
        self.children[row["agent_id"]] = Child(row["run_id"], process, log)
        self.queue_report(row, "running", process.pid)

    @staticmethod
    def terminate(child):
        if child.process.poll() is None:
            try:
                os.killpg(child.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.process.wait(timeout=5)
        child.log.close()

    def step(self):
        state = self.request("poll", {})
        desired = {row["agent_id"]: row for row in state["runtimes"]}
        stopping = []
        for agent_id, child in list(self.children.items()):
            row = desired.get(agent_id)
            if not row or row["run_id"] != child.run_id or row["desired_state"] == "stopped":
                stopping.append((agent_id, child))
            elif child.process.poll() is not None:
                code = child.process.returncode
                child.log.close()
                del self.children[agent_id]
                self.queue_report(row, "failed", error=f"Worker exited with code {code}. Inspect {child.run_id}.log on this node.")
        if stopping:
            with ThreadPoolExecutor(max_workers=len(stopping)) as pool:
                list(pool.map(self.terminate, [child for _, child in stopping]))
            for agent_id, child in stopping:
                del self.children[agent_id]
                self.queue_report({"agent_id": agent_id, "run_id": child.run_id}, "stopped")
        # A finished report must be delivered before the same run can be considered for launch again.
        self.flush_reports()
        for row in desired.values():
            if row["desired_state"] == "stopped":
                if row["agent_id"] not in self.children:
                    self.queue_report(row, "stopped")
                continue
            if row["agent_id"] not in self.children and row["state"] in {"starting", "queued"}:
                # A process that already exited during this step is never relaunched implicitly.
                if any(child.run_id == row["run_id"] for child in self.children.values()):
                    continue
                current = self.request("poll", {})
                fresh = next((item for item in current["runtimes"] if item["agent_id"] == row["agent_id"]), None)
                if not fresh or fresh["desired_state"] != "running":
                    continue
                try:
                    self.launch(fresh)
                except (OSError, ValueError) as exc:
                    self.queue_report(fresh, "failed", error=f"Could not start the worker: {exc}")
        self.flush_reports()
        return state

    def shutdown(self):
        if self.http.is_closed:
            return
        children = list(self.children.items())
        if children:
            with ThreadPoolExecutor(max_workers=len(children)) as pool:
                list(pool.map(self.terminate, [child for _, child in children]))
        for agent_id, child in children:
            self.queue_report({"agent_id": agent_id, "run_id": child.run_id}, "stopped")
            del self.children[agent_id]
        try:
            self.flush_reports()
            self.request("disconnect", {})
        except httpx.HTTPError:
            # Credentials and connection ownership expire if the server is unreachable.
            pass
        self.http.close()

    def run(self):
        if os.name != "posix":
            raise RuntimeError("Remote node process management currently requires Linux or macOS.")
        previous = {}
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, lambda *_: self.stop.set())
        try:
            registered = self.register()
            print(f"Node connected: {registered['node']['name']}. Dashboard launch/stop controls are ready.", flush=True)
            while not self.stop.is_set():
                try:
                    self.step()
                except httpx.HTTPError as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 409}:
                        raise RuntimeError("Node credentials/session are no longer valid. Stopping managed workers.") from exc
                    if time.monotonic() - self.last_success >= NODE_LEASE_SECONDS:
                        raise RuntimeError("Node connection lease expired. Stopping managed workers.")
                self.stop.wait(self.interval)
        finally:
            self.shutdown()
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def load_config(path):
    return NodeConfig.model_validate(json.loads(Path(path).expanduser().read_text()))
