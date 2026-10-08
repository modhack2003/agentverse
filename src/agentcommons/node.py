"""Outbound-only remote supervisor. Commands and project paths stay on the node."""

import json
import hashlib
import os
import re
import shlex
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
from pydantic import BaseModel, Field, model_validator, field_validator

from .models import RuntimeProfile, Diagnostic, validate_settings, execution_contract
from .orchestration import NODE_LEASE_SECONDS
from .config import identity_env, agent_environment, PROTOCOL_VERSION
from .drivers import drivers, discover_tools
from .http_adapter import read_state, reconcile, write_state
from .processes import terminate_process


class HTTPConfig(BaseModel):
    url: str
    token_env: str = Field(default="", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$|^$")
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def http_url(cls, value):
        from urllib.parse import urlsplit
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Use an HTTP(S) API URL without embedded credentials.")
        return value.rstrip("/")


class LocalProfile(RuntimeProfile):
    argv: list[str] = Field(default_factory=list, max_length=100)
    http: HTTPConfig | None = None
    driver_options: dict = Field(default_factory=dict)
    base: str = Field(default="main", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    push: bool = True
    timeout: int = Field(default=1800, ge=1, le=86400)

    @model_validator(mode="after")
    def executable(self):
        if self.argv and not self.argv[0].strip():
            raise ValueError("A profile needs a nonempty executable.")
        if self.mode == "connected":
            self.driver = "connected"
        if self.driver == "http":
            self.mode = "managed_api"
        return self


class NodeConfig(BaseModel):
    repo: str = ""
    profiles: list[LocalProfile] = Field(min_length=1, max_length=30)
    max_workers: int = Field(default=4, ge=1, le=32)
    log_dir: str = "~/.local/state/agentverse/logs"

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
    profile: LocalProfile | None = None


class NodeService:
    def __init__(self, server, token, config: NodeConfig, interval=3, config_path=None):
        self.server, self.config = server.rstrip("/"), config
        self.http = httpx.Client(base_url=self.server, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        self.repo = Path(config.repo).expanduser().resolve()
        self.logs = Path(config.log_dir).expanduser().resolve()
        self.profiles = {p.id: p for p in config.profiles}
        self.session_id = uuid.uuid4().hex
        self.interval, self.stop = max(0.1, interval), threading.Event()
        self.children: dict[str, Child] = {}
        self.pending_reports: dict[str, dict] = {}
        self.last_success = time.monotonic()
        self.adapters = drivers()
        self.config_path = Path(config_path).expanduser().resolve() if config_path else None
        self.config_mtime = self.config_path.stat().st_mtime_ns if self.config_path else None
        self.inventory = []
        self.diagnostics = []
        self.last_inventory = 0
        self.config_warning = ""

    def inspect(self):
        repo_error = ""
        try:
            result = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=self.repo, capture_output=True, timeout=10)
            if not self.config.repo or result.returncode:
                repo_error = "Prepare a project Git clone with an initial commit before launching coding workers."
        except (OSError, subprocess.TimeoutExpired):
            repo_error = "The Git clone is unavailable, Git is missing, or the repository check timed out."
        profiles, diagnostics = [], []
        for profile in self.profiles.values():
            public = RuntimeProfile(**profile.model_dump())
            public.required_settings = sorted(set(profile.required_settings) | {
                key for argument in profile.argv for key in re.findall(r"\{setting:([a-z][a-z0-9_]*)\}", argument)
            })
            local_contract = profile.model_dump(exclude={"availability", "diagnostic", "execution_revision"})
            public.execution_revision = hashlib.sha256(json.dumps(
                {"profile": local_contract, "repo": str(self.repo)}, sort_keys=True
            ).encode()).hexdigest()
            adapter = self.adapters.get(profile.driver)
            if profile.protocol_version != PROTOCOL_VERSION:
                availability, reason = "unavailable", "This adapter uses an unsupported protocol version."
            elif not adapter:
                availability, reason = "needs_setup", f"Install the node-local '{profile.driver}' adapter plugin. Other tools can still connect."
            elif getattr(adapter, "mode", profile.mode) != profile.mode:
                availability, reason = "needs_setup", "This driver does not support the configured connection mode. Use the HTTP jobs driver for managed API execution."
            else:
                try:
                    availability, reason = adapter.check(profile)
                    if profile.mode != "connected" and repo_error:
                        availability, reason = "needs_setup", repo_error
                    elif availability == "available" and profile.mode != "connected":
                        base_check = subprocess.run(
                            ["git", "rev-parse", "--verify", f"refs/heads/{profile.base}"],
                            cwd=self.repo, capture_output=True, timeout=10,
                        )
                        if base_check.returncode:
                            base_check = subprocess.run(
                                ["git", "rev-parse", "--verify", f"refs/remotes/origin/{profile.base}"],
                                cwd=self.repo, capture_output=True, timeout=10,
                            )
                        if base_check.returncode:
                            availability, reason = "needs_setup", f"Git base branch '{profile.base}' is missing on this node."
                        elif profile.push:
                            remote_check = subprocess.run(
                                ["git", "remote", "get-url", "origin"],
                                cwd=self.repo, capture_output=True, timeout=10,
                            )
                            if remote_check.returncode:
                                availability, reason = "needs_setup", "Git push is enabled but the repository has no origin remote."
                except Exception:
                    availability, reason = "unavailable", "The adapter's local health check failed. Check its installation or configuration."
            public.availability, public.diagnostic = availability, reason
            profiles.append(public)
            diagnostics.append(Diagnostic(code=f"tool.{availability}", severity="info" if availability == "available" else "warning",
                                          message=reason, profile_id=profile.id))
        self.inventory, self.diagnostics = profiles, diagnostics
        if self.config_warning:
            self.diagnostics.append(Diagnostic(code="config.pending", severity="warning", message=self.config_warning))
        return {"protocol_version": PROTOCOL_VERSION, "profiles": [p.model_dump() for p in profiles],
                "diagnostics": [d.model_dump() for d in self.diagnostics], "capacity": self.config.max_workers}

    def request(self, route, payload):
        response = self.http.post(f"/api/nodes/me/{route}", json={"session_id": self.session_id, **payload})
        response.raise_for_status()
        self.last_success = time.monotonic()
        return response.json()

    def register(self):
        self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = self.request("register", self.inspect())
        self.last_inventory = time.monotonic()
        return result

    def refresh(self):
        warning = ""
        try:
            changed = self.config_path and self.config_path.stat().st_mtime_ns != self.config_mtime
        except OSError:
            changed, warning = False, "The node configuration file is unavailable. Keeping the last working inventory."
        if changed:
            try:
                updated = load_config(self.config_path)
                profiles = {p.id: p for p in updated.profiles}
                if self.children and (updated.repo != self.config.repo or any(
                    not child.profile or profiles.get(child.profile.id) != child.profile
                    for child in self.children.values()
                )):
                    warning = "Execution-profile changes are waiting for active workers to stop."
                else:
                    self.config, self.profiles = updated, {p.id: p for p in updated.profiles}
                    self.repo = Path(updated.repo).expanduser().resolve()
                    self.config_mtime = self.config_path.stat().st_mtime_ns
                    self.adapters = drivers()
                    self.last_inventory = 0
            except (OSError, ValueError):
                # Keep a working inventory if an administrator is midway through editing the file.
                warning = "The edited configuration did not validate. Keeping the last working inventory; run doctor for local details."
        if warning != self.config_warning:
            self.config_warning, self.last_inventory = warning, 0
        if time.monotonic() - self.last_inventory >= 30:
            self.request("inventory", self.inspect())
            self.last_inventory = time.monotonic()

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
        public = next((p for p in self.inventory if p.id == profile.id), None)
        if not public or row.get("run_contract") != execution_contract(public.model_dump()) or row["mode"] != profile.mode:
            self.queue_report(row, "failed", error="The local execution profile changed after launch. Refresh inventory and launch a new generation.")
            return
        if profile.mode == "connected" or public and public.availability != "available":
            self.queue_report(row, "failed", error=public.diagnostic if public else "This profile is not a managed runtime.")
            return
        if len(self.children) >= self.config.max_workers:
            self.queue_report(row, "failed", error="Remote node worker capacity reached. Stop a worker and relaunch.")
            return
        settings = validate_settings(public.model_dump(), row.get("settings", {}), require=True)
        adapter = self.adapters.get(profile.driver)
        if not adapter:
            self.queue_report(row, "failed", error="The configured adapter is unavailable on this node.")
            return
        command = adapter.command(profile, row["model"], settings)
        if profile.mode == "managed_api":
            # Before a job starts, cancellation is safe. The adapter must journal uncertainty before POST.
            write_state(self.logs / f"{row['run_id']}.json", {"confirmed": profile.driver == "http"})
        argv = [sys.executable, "-m", "agentcommons.cli", "worker", "--server", self.server,
                "--repo", str(self.repo), "--command", shlex.join(command), "--base", profile.base,
                "--model", row["model"], "--timeout", str(profile.timeout)]
        if not profile.push:
            argv.append("--no-push")
        env = agent_environment({**os.environ, **identity_env(self.server, row["token"], row["model"], settings),
                "AGENTVERSE_RUN_ID": row["run_id"], "AGENTVERSE_RUNTIME_MODE": profile.mode,
                "AGENTVERSE_ADAPTER_STATE": str(self.logs / f"{row['run_id']}.json")})
        if profile.http:
            env["AGENTVERSE_HTTP_CONFIG"] = profile.http.model_dump_json()
        log_path = self.logs / f"{row['run_id']}.log"
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        log = os.fdopen(descriptor, "w")
        try:
            process = subprocess.Popen(argv, cwd=self.repo, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        except BaseException:
            log.close()
            raise
        self.children[row["agent_id"]] = Child(row["run_id"], process, log, profile)
        self.queue_report(row, "running", process.pid)

    @staticmethod
    def terminate(child):
        try:
            terminate_process(child.process, grace=15)
        finally:
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
                self.terminate(child)
                del self.children[agent_id]
                confirmed = self.confirmed(child)
                self.queue_report(row, "failed" if confirmed else "unconfirmed", error=f"Worker exited with code {code}. Inspect {child.run_id}.log on this node." if confirmed else "The API adapter has not confirmed its remote job ended. Work stays held while cancellation is checked.")
        if stopping:
            with ThreadPoolExecutor(max_workers=len(stopping)) as pool:
                list(pool.map(self.terminate, [child for _, child in stopping]))
            for agent_id, child in stopping:
                del self.children[agent_id]
                self.queue_report({"agent_id": agent_id, "run_id": child.run_id}, "stopped" if self.confirmed(child) else "unconfirmed")
        # A finished report must be delivered before the same run can be considered for launch again.
        self.flush_reports()
        uncertain = [row for row in desired.values() if row["state"] == "unconfirmed"]
        confirmed_runs = set()
        if uncertain:
            # Bounded parallel retries keep several unreachable APIs from starving healthy workers' lease.
            with ThreadPoolExecutor(max_workers=min(8, len(uncertain))) as pool:
                results = list(pool.map(lambda row: reconcile(self.logs / f"{row['run_id']}.json"), uncertain))
            confirmed_runs = {row["run_id"] for row, confirmed in zip(uncertain, results) if confirmed}
        for row in desired.values():
            if row["state"] == "unconfirmed":
                if row["run_id"] in confirmed_runs:
                    self.queue_report(row, "stopped")
                continue
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
                except Exception:
                    self.queue_report(fresh, "failed", error="The node-local adapter failed to start. Check its installation and configuration; other tools remain connected.")
        self.flush_reports()
        return state

    def confirmed(self, child):
        if not child.profile or child.profile.mode != "managed_api":
            return True
        state = read_state(self.logs / f"{child.run_id}.json")
        return state.get("confirmed") is True

    def shutdown(self):
        if self.http.is_closed:
            return
        children = list(self.children.items())
        if children:
            with ThreadPoolExecutor(max_workers=len(children)) as pool:
                list(pool.map(self.terminate, [child for _, child in children]))
        for agent_id, child in children:
            self.queue_report({"agent_id": agent_id, "run_id": child.run_id}, "stopped" if self.confirmed(child) else "unconfirmed")
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
                    self.refresh()
                    self.step()
                except httpx.HTTPError as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 409}:
                        raise RuntimeError("Node credentials/session are no longer valid. Stopping managed workers.") from exc
                    if time.monotonic() - self.last_success >= NODE_LEASE_SECONDS:
                        raise RuntimeError("Node connection lease expired. Stopping managed workers.")
                self.stop.wait(self.interval)
        finally:
            try:
                self.shutdown()
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)


def load_config(path):
    return NodeConfig.model_validate(json.loads(Path(path).expanduser().read_text()))


def doctor(config=None):
    report = discover_tools()
    if config:
        service = NodeService("http://127.0.0.1:1", "diagnostics-only", config)
        try:
            report.update(service.inspect())
        finally:
            service.http.close()
    return report
