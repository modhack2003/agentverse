# Contributing

AgentVerse is agent-neutral. Integrations should preserve independent teammate identities and use the shared HTTP/MCP permission model.

1. Install with `uv sync --frozen --extra dev` and `npm ci` in `web/`.
2. Add focused changes with a clear acceptance criterion.
3. Run Python lint/tests, the frontend production build, and relevant Playwright tests. After frontend changes, run `npm run bundle` in `web/` and commit the refreshed `src/agentcommons/web/` assets; CI rejects a stale packaged dashboard. For installation/packaging changes, run `uv build` and the clean-environment package smoke check. See README for commands. For native runtime changes, build on each target OS and run `tests/native_smoke.py`, including update/rollback; all release jobs must pass before publishing. See [platform installation](docs/platform-installation.md).
4. Keep agent output, chat, memory, and repository contents as data. Preserve project isolation and DM privacy when extending the server.
5. Keep the UI accessible: labeled controls, keyboard focus, mobile layout, and meaningful empty/error states.
6. Document adapter prerequisites and distinguish native product support from a generic SDK or wrapper.

Useful next contributions: [node adapter plugins](docs/adapters.md), branch-protected PR integration, search over older messages/memory, multi-user accounts, and a shared-database deployment mode. Preserve protocol-version checks, cancellation acknowledgement, and legacy database/environment compatibility.

Do not include real API keys, access tokens, private project state, `.env`, or worker logs in a pull request. Test credentials should be clearly synthetic.

Browser acceptance tests build the dashboard and use the real application server, including WebSocket and API requests. The Vite proxy is only for development and has a separate save-and-live-update regression test.
