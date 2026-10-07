"""The same permissions and transactions power HTTP and MCP."""

import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .models import MemoryWrite, MessageCreate, PlanFinish, ReviewCreate, TaskCreate, WorkSubmit


def create_mcp(store):
    domain = os.getenv("AGENTCOMMONS_DOMAIN", "").strip()
    extra_hosts = [host.strip() for host in os.getenv("AGENTCOMMONS_MCP_HOSTS", "").split(",") if host.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*",
                       *extra_hosts, *([domain, f"{domain}:*"] if domain else [])],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", *([f"https://{domain}"] if domain else [])],
    )
    mcp = FastMCP("AgentCommons", stateless_http=True, json_response=True, streamable_http_path="/",
                  transport_security=security)

    def who(ctx: Context):
        request = ctx.request_context.request
        return store.authenticate(request.headers.get("authorization") if request else None)

    @mcp.tool()
    def list_projects(ctx: Context) -> list[dict]:
        """Discover the projects this identity may collaborate on."""
        return store.projects(who(ctx))

    @mcp.tool()
    def project_context(project_id: str, ctx: Context) -> dict:
        """Read the goal, peers, tasks, conversation, reviews and shared memory before working."""
        return store.snapshot(who(ctx), project_id)

    @mcp.tool()
    def heartbeat(ctx: Context, status: str = "idle") -> dict:
        """Call every 30 seconds while connected. Status: idle, working or offline."""
        if status not in {"idle", "working", "offline"}:
            raise ValueError("Status must be idle, working or offline")
        return store.heartbeat(who(ctx), status)

    @mcp.tool()
    def team_inbox(project_id: str, ctx: Context, after_event: int = 0) -> dict:
        """Read recent public messages, your private messages, and events after your cursor."""
        principal = who(ctx)
        events = store.events(principal, project_id, max(0, after_event))
        return {"messages": store.messages(principal, project_id), "events": events,
                "cursor": events[-1]["id"] if events else after_event}

    @mcp.tool()
    def send_message(project_id: str, content: str, ctx: Context, channel: str = "general",
                     recipient_id: str | None = None, task_id: str | None = None) -> dict:
        """Talk naturally with teammates. Set recipient_id for a private DM, or leave it empty for team chat."""
        return store.message(who(ctx), project_id, MessageCreate(
            content=content, channel=channel, recipient_id=recipient_id, task_id=task_id))

    @mcp.tool()
    def create_task(project_id: str, title: str, ctx: Context, description: str = "",
                    priority: str = "medium", dependencies: list[str] | None = None) -> dict:
        """Propose a bounded implementation task. Dependencies must be existing task IDs in this project."""
        return store.create_task(who(ctx), project_id, TaskCreate(
            title=title, description=description, priority=priority, dependencies=dependencies or []))

    @mcp.tool()
    def claim_task(project_id: str, task_id: str, ctx: Context) -> dict:
        """Atomically claim an unblocked backlog task. Claim one task at a time."""
        return store.claim_task(who(ctx), project_id, task_id)

    @mcp.tool()
    def release_task(project_id: str, task_id: str, reason: str, ctx: Context) -> dict:
        """Return your in-progress task to the team with an explanation."""
        return store.release_task(who(ctx), project_id, task_id, reason)

    @mcp.tool()
    def finish_plan(project_id: str, task_id: str, summary: str, tasks: list[dict], ctx: Context) -> dict:
        """Complete your planning task and create implementation tasks for your equal teammates."""
        return store.finish_plan(who(ctx), project_id, task_id, PlanFinish(summary=summary, tasks=tasks))

    @mcp.tool()
    def submit_work(project_id: str, task_id: str, summary: str, branch: str, commit_sha: str,
                    ctx: Context, diff: str = "") -> dict:
        """Submit committed work for peer review. Push the branch to the shared repository first."""
        return store.submit_work(who(ctx), project_id, task_id, WorkSubmit(
            summary=summary, branch=branch, commit_sha=commit_sha, diff=diff))

    @mcp.tool()
    def claim_review(project_id: str, task_id: str, ctx: Context) -> dict:
        """Claim someone else's submitted work for review. Self-review is prohibited."""
        return store.claim_review(who(ctx), project_id, task_id)

    @mcp.tool()
    def release_review(project_id: str, task_id: str, ctx: Context) -> dict:
        """Release a peer review you cannot finish so another teammate can help."""
        return store.release_review(who(ctx), project_id, task_id)

    @mcp.tool()
    def review_work(project_id: str, task_id: str, decision: str, comment: str, ctx: Context,
                    integration_sha: str | None = None) -> dict:
        """Finish a claimed review: approve or changes_requested. Explain your evidence and tests."""
        return store.review_work(who(ctx), project_id, task_id, ReviewCreate(
            decision=decision, comment=comment, integration_sha=integration_sha))

    @mcp.tool()
    def read_memory(project_id: str, ctx: Context) -> list[dict]:
        """Read shared decisions, handoffs and project knowledge."""
        return store.memories(who(ctx), project_id)

    @mcp.tool()
    def write_memory(project_id: str, title: str, content: str, ctx: Context,
                     tags: list[str] | None = None, memory_id: str | None = None,
                     expected_version: int | None = None) -> dict:
        """Save a team note. Updates require memory_id and its latest expected_version to avoid overwrites."""
        return store.write_memory(who(ctx), project_id, MemoryWrite(
            title=title, content=content, tags=tags or [], expected_version=expected_version), memory_id)

    return mcp
