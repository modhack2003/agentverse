import argparse
import os

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
    args = parser.parse_args()
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
                    open_when_ready(data["port"])
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
        import json
        from .node import doctor, load_config
        try:
            print(json.dumps(doctor(load_config(args.config) if args.config else None), indent=2))
        except (ValueError, OSError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            raise SystemExit(1)
    elif args.action in {"serve", "setup"}:
        import uvicorn
        uvicorn.run("agentcommons.server:create_app", factory=True,
                    host=getattr(args, "host", "127.0.0.1"), port=args.port, reload=getattr(args, "reload", False))
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
