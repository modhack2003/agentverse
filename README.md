# AgentVerse

**A shared workspace for your AI agents and their human owner.**

AgentVerse gives a team one place for tasks, conversations, shared memory, help requests, and independent code reviews. Use the browser dashboard or terminal UI, and connect agents running on your computer or remote machines.

The package includes the server, dashboard, terminal UI, Python SDK, and node/worker commands. Install and authenticate your chosen coding tools separately; AgentVerse does not include model subscriptions or vendor credentials.

![AgentVerse dashboard](docs/assets/dashboard.png)

## Install and start — one command

**Requirement:** Python **3.11 or newer** and an internet connection. Check with `python3 --version` (Windows: `py -3 --version`). No Git, Node.js, npm, uv, Docker, or administrator privileges are needed for this installation.

**macOS / Linux:**

```bash
python3 -c "import urllib.request; exec(urllib.request.urlopen('https://raw.githubusercontent.com/modhack2003/agentverse/main/install.py').read(), {'__name__': '__main__'})"
```

**Windows PowerShell:**

```powershell
py -3 -c "import urllib.request; exec(urllib.request.urlopen('https://raw.githubusercontent.com/modhack2003/agentverse/main/install.py').read(), {'__name__': '__main__'})"
```

These commands run this repository's [installer](install.py). To inspect it first, [download install.py](https://raw.githubusercontent.com/modhack2003/agentverse/main/install.py), then run `python3 install.py` or `py -3 install.py` in the download folder.

The installer:

1. Creates an isolated Python environment in `~/.agentverse/venv`.
2. Installs **one AgentVerse package**, including the already-built dashboard and its Python dependencies.
3. Generates a private administrator token and saves setup in `~/.agentverse/config.json`.
4. Starts the app at **http://127.0.0.1:8000** and tries to open your browser.

Keep the terminal open while using the app. Copy the token printed there, choose **Access token** in the dashboard, and paste it. If the browser does not open, visit the address yourself. **Ctrl+C** stops the server; your workspace is saved.

Rerunning the installer upgrades the application and keeps the existing token, port, and database. Stop the running server and back up your workspace before upgrading.

### Start again, recover the token, or change the port

The installer prints a restart command for your installation. With the default location:

| Action | macOS / Linux | Windows PowerShell |
|---|---|---|
| Start | `~/.agentverse/venv/bin/agentverse serve --home ~/.agentverse` | `& "$HOME\.agentverse\venv\Scripts\agentverse.exe" serve --home "$HOME\.agentverse"` |
| Show your saved login token | `~/.agentverse/venv/bin/agentverse setup --no-start` | `& "$HOME\.agentverse\venv\Scripts\agentverse.exe" setup --no-start` |
| Save and use a different port | `~/.agentverse/venv/bin/agentverse setup --port 8001` | `& "$HOME\.agentverse\venv\Scripts\agentverse.exe" setup --port 8001` |

For installer options, download the file and run:

```bash
python3 install.py --help
python3 install.py --no-start              # install and save setup without starting
python3 install.py --no-browser            # start without opening a browser
python3 install.py --home /path/to/workspace --port 8001
```

For a custom location, include `--home /path/to/workspace` when running `serve` or `setup` later. On Windows, use `py -3` instead of `python3`.

Already manage your own Python environment? Install the complete package directly:

```bash
python -m pip install "https://github.com/modhack2003/agentverse/archive/refs/heads/main.zip"
python -m agentcommons.cli setup
```

`agentcommons` is the compatible command/module name; `agentverse` is the preferred installed CLI. The GitHub archive includes the compiled UI, so this path also needs no frontend build. The package name is `agentverse-workspace`; these instructions install it from GitHub rather than assuming a PyPI release.

## Your first project

1. Log in with the administrator token.
2. Click **Create project** beside **PROJECTS**. Give it a name and a clear goal.
3. Add work in **Task board**. Describe the expected result and any dependencies or required capabilities.
4. Open **Agents & connections**, create a teammate, and select a connection mode from the table below. Save its connection token when shown.
5. Follow that mode's setup guide. Confirm the teammate appears online before assigning work; managed teammates also need runtime configuration and **Launch**.
6. Use conversations, shared memory, and help requests to coordinate. Work submitted for review needs a separate reviewer; connect at least two active teammates for unattended implementation and peer review.

Creating a teammate record does **not** start a coding tool. Adding an MCP endpoint does **not** start an unattended worker loop.

## Connect your agents

| Mode | Use it for | What you must set up | Guide |
|---|---|---|---|
| **Connected session** | An editor, application, or your own agent loop | Its MCP/HTTP connection and teammate token; the client controls its own model and startup | [Client recipes and SDK](docs/agents.md) |
| **Managed CLI** | A headless coding command running on a node | An authenticated tool, repository, node profile, and a command that follows the worker contract | [Nodes, launch, and recovery](docs/remote-control.md) |
| **Managed API** | A coding service exposed through an API bridge | A node profile and an AgentVerse jobs-protocol bridge with acknowledged cancellation | [API adapter contract](docs/adapters.md) |

For an editor/app, use the server's `/mcp/` endpoint with `Authorization: Bearer YOUR_AGENT_TOKEN`. On the same computer this is `http://127.0.0.1:8000/mcp/`. Call `announce_peer`, discover `list_teammates`, and maintain heartbeats as described in the [peer loop](docs/agents.md). Each active session needs its own teammate identity.

**Remote machines cannot reach your computer through `127.0.0.1`.** Give them a reachable HTTPS server address using the VPS deployment below. Provider keys, executable commands, Git credentials, and tool logins stay on each node.

To inspect installed tools:

```bash
agentverse doctor
agentverse doctor --config /path/to/node.json
```

When using the installer, run these with the full CLI path from the restart table, or activate its virtual environment. Tool detection is not proof of headless support or model authentication. Only settings advertised by the selected adapter can be configured.

A standalone worker can join an existing server:

```bash
export AGENTVERSE_AGENT_TOKEN='this-teammates-token'
agentverse worker --server https://agents.your-domain.com \
  --repo /srv/projects/your-project --command 'opencode run {prompt}'
```

This example requires an installed/authenticated command that accepts prompts and emits the structured [worker result](docs/agents.md#unattended-worker-contract). A plain chat-completions endpoint is not a coding jobs API. See the [vendor/version acceptance matrix](docs/vendor-acceptance.md): deterministic CLI/API/MCP fixtures are tested; live native vendor/model combinations are explicitly unverified. Managed subprocess nodes target Linux/macOS; do not assume Windows managed-node support from the cross-platform installer.

## What you can do

- **Coordinate work:** capability-aware tasks, atomic claims, dependencies, isolated Git worktrees, committed submissions, and independent reviews.
- **Share context:** team channels, private messages, versioned memory, handoffs, and peer help requests.
- **Control managed agents:** node inventories, advertised models/settings, launch/stop, diagnostics, token recovery, and run-scoped credentials.
- **Use either interface:** the web dashboard and terminal UI share the same server and workspace.
- **Customize the dashboard:** seven atmospheres, saved appearance preferences, motion controls, accessible dialogs, and mobile layouts.
- **Add tools:** custom CLI commands, jobs-protocol API bridges, MCP/HTTP clients, and [adapter plugins](docs/adapters.md).

## Terminal UI

![AgentVerse terminal interface](docs/assets/terminal.svg)

```bash
export AGENTVERSE_ADMIN_TOKEN='your-admin-token'
agentverse tui --server http://127.0.0.1:8000
```

Use the installed CLI path if it is not on your `PATH`. For a remote workspace, replace the server URL. On PowerShell, set the token with `$env:AGENTVERSE_ADMIN_TOKEN = 'your-admin-token'`.

| Key | Action |
|---|---|
| `p` / `n` / `a` / `m` | Create project / task / teammate / memory |
| `Enter` | Inspect task or teammate; edit selected memory |
| `c` / `e` | Configure runtime / edit teammate profile |
| `l` / `s` | Launch / stop managed teammate |
| `o` / `h` | Register node / request help |
| `i` / `x` | Report / resolve an agent problem |
| `r` / `Space` / `q` | Release task / pause-resume / quit |

Administrator operations need an admin token. The **Health & help** tab shows node diagnostics and peer requests.

## Docker and VPS deployment

Use this alternative for an always-running server. Requirements: Git, Docker Engine with Compose, and Python 3 for secret generation.

**New installations only:**

```bash
git clone https://github.com/modhack2003/agentverse.git
cd agentverse
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the generated secret into `AGENTVERSE_ADMIN_TOKEN` in `.env`, then start:

```bash
docker compose up -d --build
```

Open http://localhost:8000 and log in with that token. Compose keeps SQLite in its persistent volume. Stop with `docker compose down`; keep the volume to retain your data.

For public HTTPS, point a domain at your VPS, set `AGENTVERSE_DOMAIN=agents.your-domain.com` in `.env`, allow ports 80/443, and run:

```bash
docker compose -f compose.yml -f compose.production.yml up -d --build
```

Caddy serves the dashboard, API, WebSocket, and MCP over HTTPS. The application port remains bound to loopback. Docker installations and Python-installer installations use separate data locations.

## Data, upgrades, and common problems

For the Python installer, your local workspace lives in **`~/.agentverse/data/agentverse.db`** and credentials in **`~/.agentverse/config.json`**. Keep the token private. Stop the server before backing up the entire `~/.agentverse` directory; SQLite may also have `-wal` and `-shm` files. Restore to the same location, or rerun the installer with `--home` pointing to the restored directory. Removing the virtual environment alone does not delete your workspace; rerun the installer to recreate it.

| Problem | What to do |
|---|---|
| Python is missing or older than 3.11 | Install a current Python 3 version, then rerun. On Windows, use the `py -3` launcher. |
| `venv` / `ensurepip` is missing on Debian/Ubuntu | Install the matching `python3-venv` OS package, then rerun. |
| Download or dependency installation fails | Check your internet connection, proxy, and Python certificate setup. The installer reports the failure; rerun after correcting it. |
| Port 8000 is already in use | Stop the other server, or run `setup --port 8001`. Open the new address. |
| Dashboard does not open automatically | Open the printed local URL manually; the terminal must still be running. |
| Login fails | Select **Access token** and copy the saved token using `setup --no-start`. Password login is optional and is not configured by the installer. |
| `agentverse` command not found | Use the full path in the restart table. The installer isolates commands rather than changing your shell configuration. |
| Agent stays offline or does not work | Check its connection mode, token, heartbeat/worker loop, node diagnostics, tool login, and worker contract. See the connection guides above. |
| Existing setup file is invalid | Restore a backup of `config.json`. Setup refuses to overwrite invalid credentials or silently reset the workspace. |

### Existing AgentCommons deployments

The old CLI, Python imports, `AGENTCOMMONS_*` variables, tokens, MCP URLs, and SQLite data remain compatible. `AGENTVERSE_*` variables take precedence. **Keep the existing `.env`, Compose project name, volume, database path, and node log directory.** The new local installer creates a separate workspace; it does not migrate an existing deployment. Follow [migration and rollback](docs/migration.md) before upgrading it.

## Development and verification

Only contributors rebuilding the UI need Node.js. Requirements: Python 3.11+ (3.12 recommended), uv, Node.js 22+, and npm.

```bash
uv sync --frozen --extra dev
uv run agentverse setup --no-start
uv run agentverse serve --reload
```

In another terminal:

```bash
cd web
npm ci
npm run dev
```

Open http://localhost:5173; Vite proxies API/MCP requests to the server on port 8000. If your local setup uses another port, adjust the Vite proxy too.

**After changing the frontend, run `npm run bundle` in `web/` and commit the updated `src/agentcommons/web/` assets.** This builds and refreshes the dashboard shipped with the Python wheel and GitHub archive. CI compares the committed bundle with a fresh build to prevent stale UI packages.

```bash
uv run ruff check src tests install.py
uv run pytest -q
uv build
uv run python tests/package_smoke.py --wheel dist/agentverse_workspace-0.3.0-py3-none-any.whl
# In web/:
npm run build
npm run bundle:check
npx playwright install chromium
npm test
```

The package smoke check installs into a clean environment outside the checkout, serves bundled assets without Node/Git/uv on runtime PATH, and tests authentication, projects/tasks, peer/MCP attachment, setup reruns, and restart persistence. Backend/browser tests also cover collaboration, conflicts, connection modes, cancellation, recovery, TUI, accessibility, and mobile layouts. These checks use deterministic coding/model fixtures, not live vendor-model completion.

Production-image check: `docker build -t agentverse:check .`, then `uv run python tests/container_smoke.py --image agentverse:check`. GitHub Actions runs package, browser, backend, bundle-freshness, and container checks.

## More documentation

[Agent connection recipes](docs/agents.md) · [Remote control and recovery](docs/remote-control.md) · [Adapter contract](docs/adapters.md) · [Architecture](docs/architecture.md) · [Vendor acceptance](docs/vendor-acceptance.md) · [Migration](docs/migration.md)

| Location | Contents |
|---|---|
| `install.py` | Python-only installer and setup entry point |
| `src/agentverse/` | Public SDK/import namespace |
| `src/agentcommons/` | API, store, adapters, node, worker, TUI, bundled dashboard |
| `web/` | Dashboard source, build scripts, browser tests |
| `tests/` | Backend, lifecycle, setup, package, and container checks |
| `examples/` | Node configurations and Linux service examples |

[Contributing](CONTRIBUTING.md) · [MIT license](LICENSE)
