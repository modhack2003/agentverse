# AgentCommons → AgentVerse 0.2

## What stays compatible

- `agentcommons` CLI and imports; new `agentverse` CLI/SDK alias the same implementation.
- `AGENTCOMMONS_*` variables; corresponding `AGENTVERSE_*` values take precedence when set.
- Existing project/agent/node tokens, MCP `/mcp/`, HTTP endpoints, SQLite IDs, projects, tasks, memory, messages, review/Git history.
- Legacy `agentcommons` JSON result fences alongside new `agentverse` fences.
- Existing node JSON with CLI profiles; new descriptor fields receive defaults.
- Compose service `commons`, volume key `commons-data`, and `/data/agentcommons.db`. These storage names deliberately remain stable.

The distribution changes to `agentverse-workspace` and version 0.2.0. `uv sync --frozen` replaces the previous distribution in the environment. Additive startup migrations add profiles, settings/modes, diagnostics, task capabilities, peer issues, and help requests.

## Upgrade safely with existing data

1. Stop managed workers cleanly. For API work, confirm cancellation before proceeding. Keep their node log directories/journals.
2. Keep the existing clone directory and `.env`. Do not copy the new `.env.example` over it or generate a new admin token during this upgrade.
3. Keep the exact Compose project name. If moving/renaming the directory, set `COMPOSE_PROJECT_NAME` to the **existing** project name (find it with `docker compose ls`). Otherwise Compose will select a new empty volume. Do not use `down -v`.
4. Back up the database using SQLite backup, not a bare copy of a live WAL database. For a default Docker deployment:

```bash
docker compose stop commons
docker compose run --rm --no-deps --entrypoint python commons -c \
  "import sqlite3; sqlite3.connect('/data/agentcommons.db').backup(sqlite3.connect('/data/before-agentverse.db'))"
```

5. Update the remote URL and rebuild in the **existing clone**:

```bash
git remote set-url origin https://github.com/modhack2003/agentverse.git
git pull
docker compose up -d --build
```

Use your existing `-p NAME`, environment, and `-f compose.yml -f compose.production.yml` flags if that is how the deployment was started. The production overlay accepts either domain-variable prefix.

6. Verify `/api/health` reports AgentVerse 0.2.0, log in with the same token, and check existing projects/teammates/tasks. Refresh the browser.
7. Update each node checkout with `uv sync --frozen`; run `agentverse doctor --config ...`. Reuse its node token and config/log directory. Stop the old systemd unit before replacing it; one node token cannot have two supervisors.

New installations may use `COMPOSE_PROJECT_NAME=agentverse`. Existing installations should retain their old name. Standalone servers retain the legacy default database filename unless you explicitly set a different path.

## Recovery and rollback

Keep backups outside the running database as well as in a protected deployment backup location. For rollback, stop the upgraded server/nodes and restore the pre-upgrade database to its original path/ownership, then deploy the previous revision using the original environment and Compose project name. Do not assume a previous release understands new help/API-runtime state.

Do not restore a server backup while API jobs continue writing. Reconcile those jobs and retain their journals first; database rollback does not stop a remote executor.
