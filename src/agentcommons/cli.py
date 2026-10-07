import argparse
import os

from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="AgentCommons — a shared home for autonomous agent teams")
    sub = parser.add_subparsers(dest="action", required=True)
    serve = sub.add_parser("serve", help="Run the collaboration server and built web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    for name in ("tui", "worker"):
        command = sub.add_parser(name, help="Open the terminal UI" if name == "tui" else "Run a remote peer worker")
        command.add_argument("--server", default=os.getenv("AGENTCOMMONS_SERVER", "http://127.0.0.1:8000"))
        command.add_argument("--token", default=os.getenv("AGENTCOMMONS_AGENT_TOKEN") or os.getenv("AGENTCOMMONS_ADMIN_TOKEN"))
        if name == "worker":
            command.add_argument("--repo", required=True)
            command.add_argument("--command", required=True, help="Agent command, with {prompt} or {prompt_file}; executed without a shell")
            command.add_argument("--base", default="main")
            command.add_argument("--no-push", action="store_true", help="Local/testing only: retain branches on this node")
            command.add_argument("--once", action="store_true")
            command.add_argument("--interval", type=int, default=5)
            command.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    if args.action == "serve":
        import uvicorn
        uvicorn.run("agentcommons.server:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)
    else:
        if not args.token:
            parser.error("Set AGENTCOMMONS_AGENT_TOKEN or AGENTCOMMONS_ADMIN_TOKEN.")
        if args.action == "tui":
            from .tui import CommonsTUI
            CommonsTUI(args.server, args.token).run()
        else:
            from .worker import Worker
            Worker(args.server, args.token, args.repo, args.command, args.base, not args.no_push,
                   args.interval, args.timeout).run(once=args.once)
