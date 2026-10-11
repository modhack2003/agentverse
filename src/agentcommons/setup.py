"""Persistent local setup for the single-package installation."""

import json
import os
import secrets
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def home_path(value=None):
    return Path(value).expanduser().resolve() if value else Path.home() / ".agentverse"


def valid_port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Port must be a number from 1 to 65535.")
    return value


def read_setup(home):
    path = home / "config.json"
    if path.is_symlink():
        raise ValueError(f"Refusing a symlink for the credentials file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"Invalid setup file: {path}. Restore your backup; it has not been overwritten.") from exc
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("admin_token"), str) or len(data["admin_token"]) < 24
            or data["admin_token"].startswith("replace-")
            or data.get("database") != "data/agentverse.db"):
        raise ValueError(f"Invalid setup file: {path}. Restore your backup; it has not been overwritten.")
    valid_port(data.get("port"))
    login = data.get("login")
    if login is not None:
        import re
        if (not isinstance(login, dict) or not isinstance(login.get("username"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,100}", login["username"])
                or not re.fullmatch(r"scrypt\$[a-f0-9]{32}\$[a-f0-9]{128}", str(login.get("password_hash", "")))):
            raise ValueError(f"Invalid login in {path}; it has not been overwritten.")
    if "onboarding_complete" in data and type(data["onboarding_complete"]) is not bool:
        raise ValueError(f"Invalid setup file: {path}; it has not been overwritten.")
    return data


def write_setup(home, data):
    path = home / "config.json"
    temporary = home / f".config-{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_setup(home, port=None):
    """Create once; reruns preserve the token and database."""
    if port is not None:
        valid_port(port)
    new_home = not home.exists()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt" and new_home:
        import getpass
        import subprocess
        user = os.getenv("USERDOMAIN", "")
        user = (user + "\\" if user else "") + getpass.getuser()
        subprocess.run([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/icacls.exe"), str(home), "/inheritance:r", "/grant:r", user + ":(OI)(CI)F"],
                       check=True, capture_output=True)
    path = home / "config.json"
    if path.exists() or path.is_symlink():
        data = read_setup(home)
        if port is not None and port != data["port"]:
            data["port"] = port
            write_setup(home, data)
    else:
        data = {"version": 1, "admin_token": secrets.token_urlsafe(32),
                "database": "data/agentverse.db", "port": port or 8000}
        write_setup(home, data)
    (home / "data").mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o600)
    return data


def apply_setup(home, data, override=False):
    for name, value in (("ADMIN_TOKEN", data["admin_token"]), ("DB", str(home / data["database"]))):
        if override or not any(f"{prefix}_{name}" in os.environ for prefix in ("AGENTVERSE", "AGENTCOMMONS")):
            os.environ[f"AGENTVERSE_{name}"] = value
    os.environ["AGENTVERSE_LOCAL_HOME"] = str(home)


def show_setup(home, data):
    print(f"\nLocal dashboard URL: http://127.0.0.1:{data['port']}")
    print("In the dashboard, choose Access token and paste this administrator token:")
    print(data["admin_token"])
    print(f"Credentials: {home / 'config.json'}")
    print(f"Workspace database: {home / data['database']}")
    print("Keep the token private. Setup reruns keep the same token and workspace.", flush=True)


def open_when_ready(port, fragment=""):
    def open_browser():
        url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(50):
            try:
                with opener.open(url + "/api/health", timeout=0.2) as response:
                    if response.status == 200:
                        webbrowser.open(url + fragment)
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
    threading.Thread(target=open_browser, daemon=True).start()
