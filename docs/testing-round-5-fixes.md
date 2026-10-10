# Round-five fixes and retest

These fixes start from `01c178a8f6dd32c2f86e6984ab4874813661f87e`.
The [original audit](../agentverse-fresh-audit-round-5.md) remains a historical record of the failures before this change.

## Repairs

| Finding | Corrected behavior |
| --- | --- |
| AV-21: terminal history gaps | Refreshes page back to the loaded conversation before merging, so bursts larger than 100 messages do not leave an inaccessible gap. General, engineering, reviews, and private messages retain their normal pagination. |
| AV-21: help history | Refreshes update the entire loaded help window, including answers and state changes on older requests. Pagination reflects the oldest fetched help page. |
| Related delayed-response cases | Responses from a previous project or conversation visit are ignored, including switching away and back. A four-second polling tick does not cancel an unfinished multi-page refresh. |
| AV-26: duplicate terminal creations | A successful mutation is handled separately from a failed subsequent refresh. The client retries the project-list GET rather than reopening the creation form. Newly created projects remain selected. This is covered for project, task, and memory creation. |
| AV-27: lost invitation drafts | Rejected agent and node invitations reopen with the submitted fields intact. Correcting validation errors creates one invitation and presents its connection token. |
| Browser resize checks | Width assertions wait for layout to settle and still fail if overflow persists. Each browser run uses a fresh database filename. |

Memory conflict recovery still preserves the draft and protects the concurrent version; a plain retry does not silently overwrite another user's edit.

## Validation

A clean checkout received fresh Python and web dependency installations with `uv sync --frozen --extra dev` and `npm ci`. Each expanded browser run uses a new database.

| Check | Result |
| --- | --- |
| Ruff, project source and shipped tests | Passed |
| Expanded backend suite | **109 passed**, including the **84-test project suite** and 25 independent audit checks |
| New terminal regression cases | **29 passed** as part of the backend run |
| Expanded development-browser suite | **27 passed** |
| Expanded compiled-production-browser suite | **27 passed** |
| Vite production build | Passed |
| Python wheel and source distribution | Built successfully |
| Wheel installation in a separate clean environment | Passed; both `agentverse` and `agentcommons` CLI entry points work |
| Built wheel source | Matches the tested terminal source exactly |

The independent audit tooling adds 25 backend checks and 17 browser scenarios to the default project suites. It was used for this retest; it is separate from the shipped test files. The project gains 29 portable terminal regression cases in `tests/test_terminal_recovery.py`.

The expanded checks cover all 23 MCP tools over HTTP, the native MCP Python client's transport initialization and announcement, runtime contracts, process cleanup, credential filtering, worker/Git execution, authentication, persistence, owner/scoped UI permissions, copied HTTP Python setup for eight tool identities, failed saves and sends, history recovery, keyboard controls, themes, and narrow layouts.

The existing GitHub Actions workflow runs the shipped Python and browser suites, builds the Docker image, and runs the container smoke checks on the published commit. Its result is available in the repository's Actions page.

## Reproduce the shipped checks

```bash
uv sync --frozen --extra dev
uv run ruff check src tests
uv run pytest -q
uv build
cd web
npm ci
npm run build
npx playwright install --with-deps chromium
npm test
```

## Limits and follow-up suggestions

Copied setup and native MCP transport checks establish connectivity; they do not establish full readiness of every vendor's authenticated agent and model. Live vendor accounts/models, PowerShell, real VPS/HTTPS/systemd deployment, Firefox/Safari, and physical mobile devices require separate verification.

The optional UX suggestions in the original audit—setup guidance, a vendor/version acceptance matrix, conflict comparison controls, ordinary task editing, credential recovery, failed-logout retry, and explicit unset boolean settings—remain separate follow-up work. They are not represented as implemented by this patch.
