#!/usr/bin/env python3
"""Install the complete AgentVerse package in an isolated environment, then set it up.

Download this file from the official repository and run: python3 install.py
No Git, Node.js, uv, Docker, or administrator privileges are required.
"""

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import venv

SOURCE = "https://github.com/modhack2003/agentverse/archive/refs/heads/main.zip"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home() / ".agentverse")
    parser.add_argument("--port", type=int, help="Local dashboard port (default 8000; reruns keep your saved port)")
    parser.add_argument("--no-start", action="store_true", help="Install and configure without running the server")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open a browser")
    parser.add_argument("--source", default=SOURCE, help="Package archive, local wheel, or source directory")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required. Install it, then run this installer again.")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("Port must be from 1 to 65535.")
    home = args.home.expanduser().resolve()
    environment = home / "venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not python.is_file():
            print(f"Creating an isolated Python environment in {environment}", flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)
        print("Installing AgentVerse, including its dashboard and Python dependencies…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", args.source], check=True)
        command = [str(python), "-m", "agentcommons.cli", "setup", "--home", str(home)]
        if args.port is not None:
            command += ["--port", str(args.port)]
        if args.no_start:
            command.append("--no-start")
        if args.no_browser:
            command.append("--no-browser")
        if os.name == "nt":
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            restart = f"& {quote(python)} -m agentcommons.cli serve --home {quote(home)}"
        else:
            restart = shlex.join([str(python), "-m", "agentcommons.cli", "serve", "--home", str(home)])
        print(f"\nTo restart later: {restart}", flush=True)
        setup_env = dict(os.environ, PYTHON_DOTENV_DISABLED="1")
        subprocess.run(command, check=True, env=setup_env)
    except KeyboardInterrupt:
        print("\nStopped. Existing workspace files are kept. Rerun the installer to continue.")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"\nInstallation/setup did not complete: {exc}", file=sys.stderr)
        print("Your existing config and database were not deleted. Check the error above and rerun.\n"
              "If venv/ensurepip is missing on Debian/Ubuntu, install python3-venv first.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
