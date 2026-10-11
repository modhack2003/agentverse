import argparse
import os
import json
import sys

from dotenv import load_dotenv
from .config import setting, agent_environment


def main():
    if os.getenv("PYTHON_DOTENV_DISABLED") != "1":
        load_dotenv()
    parser = argparse.ArgumentParser(description="AgentVerse — independent agents, connected intelligence")
    sub = parser.add_subparsers(dest="action", required=True)
    serve = sub.add_parser("serve", help="Run the collaboration server and built web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int)
    serve.add_argument("--home", help="Use a saved local setup directory (default ~/.agentverse)")
    serve.add_argument("--reload", action="store_true")
    setup = sub.add_parser("setup", help="Create local credentials and storage, then start the complete app")
    setup.add_argument("--home", help="Local setup directory (default ~/.agentverse)")
    setup.add_argument("--port", type=int)
    setup.add_argument("--no-start", action="store_true", help="Save setup and show login details without starting")
    setup.add_argument("--no-browser", action="store_true")
    for name in ("tui", "worker"):
        command = sub.add_parser(name, help="Open the terminal UI" if name == "tui" else "Run a remote peer worker")
        command.add_argument("--server", default=setting("SERVER", "http://127.0.0.1:8000"))
        command.add_argument("--token", default=setting("AGENT_TOKEN") or setting("ADMIN_TOKEN"))
        if name == "worker":
            command.add_argument("--repo", required=True)
            command.add_argument("--command", required=True, help="Agent command, with {prompt} or {prompt_file}; executed without a shell")
            command.add_argument("--base", default="main")
            command.add_argument("--no-push", action="store_true", help="Local/testing only: retain branches on this node")
            command.add_argument("--once", action="store_true")
            command.add_argument("--interval", type=int, default=5)
            command.add_argument("--timeout", type=int, default=1800)
            command.add_argument("--model", default=setting("MODEL"),
                                 help="Model ID, exposed as {model}, AGENTVERSE_MODEL, and task context")
    node = sub.add_parser("node", help="Run a remote service controlled from the dashboard")
    node.add_argument("--server", default=setting("SERVER", "http://127.0.0.1:8000"))
    node.add_argument("--token", default=setting("NODE_TOKEN"))
    node.add_argument("--config", required=True, help="Local JSON with repository, tool commands, and model options")
    node.add_argument("--interval", type=int, default=3)
    inspect = sub.add_parser("doctor", help="Inspect installed tools, adapter plugins and node setup")
    inspect.add_argument("--config")
    inspect.add_argument("--server", help="Run a bounded read-only connection check")
    inspect.add_argument("--token", default=setting("AGENT_TOKEN") or setting("NODE_TOKEN"))
    inspect.add_argument("--node-token", action="store_true", help="Check a node supervisor token rather than a peer token")
    inspect.add_argument("--mcp", action="store_true", help="Also check the MCP handshake with an agent token")
    for name in ("launch", "start", "stop", "restart", "status", "backup", "restore", "shortcut", "autostart", "service", "uninstall", "update", "rollback"):
        command = sub.add_parser(name, help=f"{name.capitalize()} the local installation")
        command.add_argument("--home", help="Workspace directory (default ~/.agentverse)")
        if name in {"launch", "start", "restart"}:
            command.add_argument("--no-browser", action="store_true")
            command.add_argument("--port", type=int)
        if name == "backup":
            command.add_argument("--output")
        if name == "restore":
            command.add_argument("archive")
        if name in {"autostart", "service", "shortcut"}:
            command.add_argument("--remove", action="store_true")
        if name == "uninstall":
            command.add_argument("--delete-data", action="store_true", help="Also delete workspace data and saved backups")
        if name == "update":
            command.add_argument("--source", help="Trusted local wheel or archive for offline/manual updates")
            command.add_argument("--sha256", help="Expected checksum for a manually supplied portable archive")
    inspect.add_argument("--home")
    inspect.add_argument("--export", help="Save a shareable report without secrets or local paths")
    args = parser.parse_args(sys.argv[1:] or ["launch"])
    if args.action in {"launch", "start", "stop", "restart", "status", "backup", "restore", "shortcut", "autostart", "service", "uninstall", "update", "rollback"}:
        from . import local
        from .setup import home_path, prepare_setup
        home = home_path(args.home)
        try:
            if args.action in {"launch", "start", "restart"}:
                if args.port is not None:
                    from .setup import valid_port
                    valid_port(args.port)
                if args.action == "restart":
                    local.stop(home)
                result = local.start(home, browser=not args.no_browser, port=args.port)
            elif args.action == "stop":
                result = local.stop(home)
            elif args.action == "status":
                result = local.status(home)
            elif args.action == "backup":
                result = {"backup": str(local.backup(home, args.output)), "contains_credentials": True}
            elif args.action == "restore":
                result = local.restore(home, args.archive)
            elif args.action in {"shortcut", "autostart", "service"}:
                from .startup import shortcut, service
                prepare_setup(home)
                path = service(home, remove=args.remove) if args.action == "service" else shortcut(home, autostart=args.action == "autostart", remove=args.remove)
                result = {"path": str(path), "removed": args.remove}
            elif args.action == "uninstall":
                from .startup import shortcut, service, identifier
                from pathlib import Path
                unit = Path.home() / '.config/systemd/user' / (identifier(home) + '.service')
                if unit.exists():
                    service(home, remove=True)
                local.stop(home)
                for automatic in (True, False):
                    shortcut(home, autostart=automatic, remove=True)
                result = local.uninstall(home, args.delete_data)
            else:
                from .updates import update, rollback
                result = rollback(home) if args.action == "rollback" else update(home, args.source, args.sha256)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, __import__('subprocess').CalledProcessError) as exc:
            parser.error(str(exc))
        return
    if args.action in {"setup", "serve"}:
        from .setup import apply_setup, home_path, prepare_setup, read_setup, show_setup, valid_port
        home = home_path(args.home)
        try:
            if args.port is not None:
                valid_port(args.port)
            data = None
            if args.action == "setup":
                data = prepare_setup(home, args.port)
                apply_setup(home, data, override=True)
                show_setup(home, data)
                if args.no_start:
                    return
                if not args.no_browser:
                    from .setup import open_when_ready
                    import secrets
                    welcome = secrets.token_urlsafe(32) if not data.get("onboarding_complete") else ""
                    os.environ["AGENTVERSE_WELCOME_TOKEN"] = welcome
                    open_when_ready(data["port"], "#setup=" + welcome if welcome else "")
            elif args.home or (not setting("ADMIN_TOKEN") and (home / "config.json").exists()):
                data = read_setup(home)
                apply_setup(home, data, override=bool(args.home))
            args.port = args.port or (data["port"] if data else 8000)
        except (ValueError, OSError) as exc:
            parser.error(f"{exc} Run 'agentverse setup' for a new installation.")
    if args.action in {"worker", "node"}:
        # Arguments captured node/agent identity; clear inherited coordinator secrets.
        filtered = agent_environment(os.environ)
        for key in set(os.environ) - set(filtered):
            os.environ.pop(key, None)
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    if args.action == "doctor":
        from .node import doctor, load_config
        try:
            config = load_config(args.config) if args.config else None
            if args.export or args.home:
                from .local import diagnostics, private_write
                from .setup import home_path
                report = diagnostics(home_path(args.home), config)
                if args.export:
                    from pathlib import Path
                    private_write(Path(args.export), json.dumps(report, indent=2).encode())
            else:
                report = doctor(config)
            if args.server:
                from .connection_check import check
                if not args.token:
                    raise ValueError("Set AGENTVERSE_AGENT_TOKEN or AGENTVERSE_NODE_TOKEN for a connection check.")
                report['connection'] = check(args.server, args.token, node=args.node_token, mcp=args.mcp)
                if args.export:
                    private_write(Path(args.export), json.dumps(report, indent=2).encode())
            print(json.dumps(report, indent=2))
            if args.server and not report['connection']['ok']:
                raise SystemExit(1)
        except (ValueError, OSError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            raise SystemExit(1)
    elif args.action in {"serve", "setup"}:
        import uvicorn
        if getattr(args, "reload", False):
            uvicorn.run("agentcommons.server:create_app", factory=True, host=args.host, port=args.port, reload=True)
        else:
            from .server import create_app
            from contextlib import nullcontext
            from .local import exclusive
            context = exclusive(home) if data else nullcontext()
            try:
                with context:
                    app = create_app()
                    server = uvicorn.Server(uvicorn.Config(app, host=getattr(args, "host", "127.0.0.1"), port=args.port))
                    app.state.shutdown = lambda: setattr(server, "should_exit", True)
                    server.run()
            except ValueError as exc:
                parser.error(str(exc))
    elif args.action == "node":
        if not args.token:
            parser.error("Set AGENTVERSE_NODE_TOKEN (legacy AGENTCOMMONS_NODE_TOKEN also works).")
        from .node import NodeService, load_config
        NodeService(args.server, args.token, load_config(args.config), args.interval, args.config).run()
    else:
        if not args.token:
            parser.error("Set AGENTVERSE_AGENT_TOKEN or AGENTVERSE_ADMIN_TOKEN.")
        if args.action == "tui":
            from .tui import CommonsTUI
            CommonsTUI(args.server, args.token).run()
        else:
            from .worker import Worker
            Worker(args.server, args.token, args.repo, args.command, args.base, not args.no_push,
                   args.interval, args.timeout, model=args.model).run(once=args.once)


if __name__ == "__main__":
    main()
