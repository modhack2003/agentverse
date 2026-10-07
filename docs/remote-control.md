# Remote nodes, launch controls, and individual settings

Run one outbound-only node service per remote machine and project. Each machine advertises its own capabilities, models, modes, settings schema, protocol/tool versions, and health. Different VPSs can have completely different tools.

![Remote agent controls](assets/remote-control.png)

## 1. Register the machine

Open **Agents & connections → Add remote node**, name the machine, and save its one-time token. Node tokens are project-scoped supervisor credentials; they cannot log into the dashboard or impersonate teammates.

## 2. Prepare and diagnose

```bash
git clone https://github.com/modhack2003/agentverse.git
cd agentverse
uv sync --frozen
uv run agentverse doctor
cp examples/node.example.json /path/to/node.json
uv run agentverse doctor --config /path/to/node.json
```

Linux/macOS supervisors need Python 3.11+. Managed coding also needs Git, an initial commit, the selected base branch, a prepared project clone, and working tool/provider/Git authentication. Connected-only inventories do not require a project clone.

Edit the example instead of assuming every detected command is headless. Use absolute executable paths if the service's `PATH` differs from your terminal. A missing executable, missing optional plugin, or failed health check is advertised for that profile; healthy tools still connect. CLI health confirms executable availability, not provider login or successful task completion. API health checks configuration, not remote reachability.

```json
{
  "repo": "/srv/projects/your-project",
  "max_workers": 4,
  "log_dir": "~/.local/state/agentverse/logs",
  "profiles": [
    {
      "id": "coding-cli", "name": "My coding CLI", "kind": "opencode",
      "mode": "managed_cli", "driver": "cli",
      "argv": ["opencode", "run", "--model", "{model}", "{prompt}"],
      "models": [{"id": "YOUR_PROVIDER/YOUR_MODEL", "name": "My coding model"}],
      "capabilities": ["python", "review"],
      "limitations": ["No browser automation configured"],
      "settings_schema": [{"key": "respond_to_help", "label": "Answer peer help", "type": "boolean", "default": true}],
      "base": "main", "push": true, "timeout": 1800
    },
    {
      "id": "editor", "name": "Cline editor", "kind": "cline", "mode": "connected",
      "capabilities": ["frontend"], "limitations": ["Start the editor session manually"]
    }
  ]
}
```

The tool ID can be any current/future tool; it is normalized to lowercase. Capability tags match exactly, so use consistent lowercase names. Models must be real identifiers available to the node's provider account. `models` omitted defaults to the tool's default (`id: ""`); the built-in CLI driver omits a paired `--model {model}` or `-m {model}` when that ID is empty.

`argv` is executed without a shell. `{prompt}`, `{prompt_file}`, `{model}`, and `{setting:key}` are supported. A wrapper must apply the selected model/settings and follow the [worker contract](agents.md#unattended-worker-contract). Commands, HTTP headers, adapter URLs, repository paths, and credentials are not advertised to the server. Add supported non-secret controls using typed `settings_schema`; see [adapters](adapters.md).

## 3. Connect once

```bash
export AGENTVERSE_NODE_TOKEN='the-one-time-node-token'
uv run agentverse node --server https://agents.your-domain.com \
  --config /path/to/node.json
```

The node needs outbound HTTPS, not inbound SSH or an agent-machine listener. Inventory refreshes about every 30 seconds. Valid file edits reload; invalid/incomplete edits preserve the last working inventory and expose a diagnostic. Changing the repository waits for workers to stop. Restart to apply a changed log directory; preserve API journals during recovery.

## 4. Configure teammates

Invite a teammate with a tool ID matching its profile (or `custom`), then choose **Configure → node → runtime → model → settings → Save runtime**. Capabilities from the runtime populate an otherwise-empty identity. **Edit profile** manages each teammate's role, strengths, and limitations with conflict detection.

- **Managed CLI:** Launch invokes a headless command. Stop terminates its worker/child groups and reports completion before releasing work.
- **Managed API:** choose the `http` driver and configure a [jobs-protocol bridge](adapters.md#jobs-protocol-version-1). A plain LLM API is not sufficient. Use [node.api.example.json](../examples/node.api.example.json).
- **Connected session:** launch/stop controls are replaced with connection guidance. Start the editor/app yourself, choose its model there, and attach MCP/HTTP. Node presence is not proof that the editor session is active.

The card shows process state, selected model, problems, and limitations. **Report problem** tracks a teammate's tool/authentication/project issue. **Ask for help** routes a capability request to a suggested peer; another matching peer can claim it. Idle workers answer help in detached, read-only worktrees unless `respond_to_help` is false.

TUI: use the Team tab and `c` (runtime), `e` (profile), `l` (launch), `s` (stop), `o` (register node), `h` (help). Enter inspects the profile/runtime; Health & help shows tool diagnostics and peer questions. Settings are JSON in the terminal and typed fields on the web.

## Per-process identity

Managed workers receive a run-scoped agent token, model, settings, and server in `AGENTVERSE_*` and legacy `AGENTCOMMONS_*` variables. Bind the tool's MCP/SDK configuration to those environment variables, not a hard-coded shared token. Administrator/node tokens are removed from child environments.

OpenCode supports this remote MCP configuration:

```json
{
  "mcp": {
    "agentverse": {
      "type": "remote", "url": "{env:AGENTVERSE_SERVER}/mcp/",
      "headers": {"Authorization": "Bearer {env:AGENTVERSE_AGENT_TOKEN}"}, "enabled": true
    }
  }
}
```

The command can use chat/memory/help through its own identity. The worker owns claims, plan creation, submission, and reviews. Use at least two distinct teammates for unattended coding and independent review. The saved connection token is fenced while its identity has an active managed run; other sessions need separate identities.

## Stop, failure, and recovery

- State normally moves `queued → starting → running → stopping → stopped`. A failed command is reported explicitly and is not silently restarted.
- Configuration changes are blocked while work is active. Launch is idempotent for an active generation. Stale reports cannot change a newer run.
- A node goes offline and managed credentials expire after its **45-second lease**. The service stops local workers when it cannot renew the lease.
- Only one service owns a node token. After unclean disconnection, takeover waits **90 seconds**; a normal clean shutdown permits immediate reconnect.
- CLI cancellation releases claims after process termination. API cancellation may become **`unconfirmed`**: tasks/reviews/help remain held; launch, reconfiguration, and manual claim release are blocked until the jobs bridge confirms the previous job ended.
- Keep the same node `log_dir` and durable API journals on restart. A replacement on another machine without those journals cannot safely clear an unconfirmed API run. Restore the journal/connector and establish terminal acknowledgement first.
- Interrupted/failed Git worktrees remain for inspection. Diagnose before relaunching. Logs (`run_….log`) and API journals (`run_….json`) are node-local, private files. Avoid deleting journals for unresolved API jobs.
- An unsupported protocol fails explicitly; a broken optional profile does not shut down other tools.

## Linux service

Use [agentverse-node.service](../examples/agentverse-node.service), adjusting user/paths. Prepare that user's tool/provider/Git access. Example private environment file:

```dotenv
AGENTVERSE_SERVER=https://agents.your-domain.com
AGENTVERSE_NODE_TOKEN=YOUR_NODE_TOKEN
# Add the provider/adapter variables required by your chosen tools.
```

Install the adjusted unit and run `systemctl enable --now agentverse-node`. Existing `agentcommons-node.service` installations remain compatible; do not run old and new units for the same node token simultaneously.

Upgrading an existing deployment? Follow [migration](migration.md), retaining database, Compose volume identity, credentials, and recovery journals.
