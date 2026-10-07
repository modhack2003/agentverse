"""Node-local adapters. A new vendor needs a descriptor or an installed entry-point plugin."""

import importlib.metadata
import os
import re
import shutil
import sys
from pathlib import Path

from .config import PROTOCOL_VERSION


class CLIDriver:
    protocol_version = PROTOCOL_VERSION
    mode = "managed_cli"

    def check(self, profile):
        if not profile.argv:
            return "needs_setup", "Configure this tool's headless command or use connected-session mode."
        if not shutil.which(profile.argv[0]):
            return "unavailable", f"Executable {profile.argv[0]} is not installed or not on the node's PATH."
        return "available", "Headless command found. Model authentication is configured in the tool's own client."

    def command(self, profile, model, settings):
        argv = []
        skip = False
        for index, argument in enumerate(profile.argv):
            if skip:
                skip = False
                continue
            if not model and argument in {"--model", "-m"} and index + 1 < len(profile.argv) and profile.argv[index + 1] == "{model}":
                skip = True
                continue
            def replace(match):
                key = match.group(1)
                if key not in settings:
                    raise ValueError(f"Command expects an unconfigured setting: {key}")
                value = settings[key]
                return str(value).lower() if isinstance(value, bool) else str(value)
            argv.append(re.sub(r"\{setting:([a-z][a-z0-9_]*)\}", replace, argument))
        return argv


class HTTPDriver:
    protocol_version = PROTOCOL_VERSION
    mode = "managed_api"

    def check(self, profile):
        if not profile.http:
            return "needs_setup", "Configure an AgentVerse jobs-protocol endpoint for this API adapter."
        if profile.http.token_env and not os.getenv(profile.http.token_env):
            return "needs_setup", f"Set {profile.http.token_env} on the node to authenticate this API adapter."
        return "available", "API jobs adapter configured. Endpoint reachability is verified when a job is started."

    def command(self, profile, model, settings):
        return [sys.executable, "-m", "agentcommons.http_adapter", "{prompt_file}"]


class ConnectedDriver:
    protocol_version = PROTOCOL_VERSION
    mode = "connected"

    def check(self, profile):
        return "available", "Start a session in this tool's client and attach it using MCP or the HTTP SDK."

    def command(self, profile, model, settings):
        raise ValueError("Connected sessions are controlled by their own client.")


def drivers():
    available = {"cli": CLIDriver(), "http": HTTPDriver(), "connected": ConnectedDriver()}
    for plugin in importlib.metadata.entry_points(group="agentverse.adapters"):
        if plugin.name in available:
            continue
        try:
            adapter = plugin.load()()
            if adapter.protocol_version == PROTOCOL_VERSION:
                available[plugin.name] = adapter
        except Exception:
            # A broken optional adapter does not prevent other tools from connecting.
            continue
    return available


def discover_tools():
    candidates = {
        "opencode": ["opencode"], "omnirush": ["omnirush"], "cline": ["cline"],
        "claude": ["claude"], "codex": ["codex"], "kiro": ["kiro-cli", "kiro"],
        "antigravity": ["antigravity"], "agentzero": ["agent-zero", "agentzero"],
    }
    found = []
    for kind, commands in candidates.items():
        executable = next((shutil.which(command) for command in commands if shutil.which(command)), None)
        found.append({"kind": kind, "executable": executable, "detected": bool(executable),
                      "note": "Executable detected; verify its headless/API interface before choosing a launch command." if executable else "Not found on PATH. An editor extension, source installation, API, or custom adapter may still be available."})
    return {"protocol_version": PROTOCOL_VERSION, "tools": found,
            "adapter_plugins": sorted(drivers()), "python": sys.version.split()[0],
            "git_detected": bool(shutil.which("git")), "platform": sys.platform,
            "home": str(Path.home())}
