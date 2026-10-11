# Optional findings: implementation and retest

Date: 2026-10-11. Starting point: `5afe98edd957b10c40b84ef25c05f5fb3d783506` on GitHub main, fetched again before editing. This implements the remaining improvements from [round five](../agentverse-fresh-audit-round-5.md); the earlier defect repairs are documented separately in [the previous repair report](testing-round-5-fixes.md).

## Completed scope

| Finding | Result |
|---|---|
| SDK prerequisite and bounded check | Connection dialog includes the actual Git SDK installation command beside Python setup and a one-shot check using two requests with five-second network timeouts. Output distinguishes HTTP authentication/presence from unverified native readiness. |
| Vendor/version acceptance | [Acceptance matrix](vendor-acceptance.md) covers every advertised native tool and all requested stages, separates fixture results, visibly marks native combinations unverified, and provides a repeatable exact-version evidence procedure. Linked from connection setup and agent documentation. |
| Memory/profile conflict comparison | A project-scoped memory read endpoint supplies latest versions; latest saved values and the rejected draft are shown together. Reapply retains all form values and advances only the compared expected version; Save remains deliberate, and later concurrent edits still produce a new comparison. Failed reads preserve the draft. |
| Ordinary task editing | Owners can edit unclaimed tasks from task details: title, description, priority, dependencies and required capabilities. Self dependencies are omitted; backend validation still rejects cycles and tasks claimed while the form was open. Rejected saves retain the form. |
| Agent/node credential recovery | Agent replacement is available on managed and revoked cards. New admin-only, project-scoped node replacement keeps node identity/configuration, refuses online nodes and all active/uncertain runs, invalidates the prior bearer token and session, and shows replacement once. |
| Failed logout | Failed network/server requests retain the browser session and provide Retry sign out. A retry receiving 401 confirms an already invalid session, including a lost successful logout response. Local state clears only after success or confirmed invalid authentication. Reusable admin/agent access tokens retain their existing lifecycle; logout revokes password-created web sessions. |
| Unset booleans | Boolean settings without defaults offer unset/true/false; required choices use native form validation. Explicit false persists; optional unset stays omitted and existing explicit defaults retain their behavior. |
| Uncertain run recovery | Expandable run evidence shows last node contact/report, last reported journal availability, termination evidence, generation, desired state and frozen execution contract. Only bounded evidence is sent from node journals; provider credentials/journal contents remain local. Relaunch resets old evidence, and stale reports remain fenced. |
| Viewport diagnostics | Settled viewport assertions include measured root/viewport widths and offending elements, and retain a separate root overflow check. Conflict/setup dialogs are checked at 320px. |

## Verification

Fresh locked Python installation and `npm ci` passed. Ruff, TypeScript/Vite production build, wheel and source distribution build passed. The final wheel was installed into a clean virtual environment; both CLI entry points, SDK timeout, memory reads and node credential replacement passed smoke checks with freshly resolved package dependencies.

| Suite | Final result |
|---|---|
| Backend expanded audit | **121 passed**: 96 shipped checks (including 12 new cases) plus 25 independent audit cases |
| Development browser UI | **35 passed**: 18 shipped scenarios (including 8 new cases) plus 17 independent audit scenarios |
| Production browser UI | **35 passed** against compiled assets, with the same 18 shipped and 17 independent scenarios |

The independent cases reuse the source published in the original audit's reproduction appendix. For this round, the old positional Python/PowerShell recipe selectors were changed to select the intended code blocks by content after adding the SDK prerequisite. The portable new regressions are committed in `tests/test_optional_recovery.py` and `web/tests/optional-fixes.spec.ts`; temporary expanded harness/configuration files are not shipped.

The first browser pass caught a missing read route in the new memory comparison flow. The project-scoped GET route and an authorization/version regression were added before the final full reruns. The final development and production suites have no failures. Backend tests report one upstream Starlette/httpx test-client deprecation warning, without a failed check.

Reproduce the shipped checks:

```bash
uv sync --frozen --extra dev
uv run ruff check src tests
uv run pytest -q
cd web
npm ci
npm run build
npx playwright install chromium
npm test
```

Expanded runs used isolated SQLite databases, local HTTP fixtures, Chromium 153, and the original audit overrides for localhost development and compiled assets. Local proxy variables were unset for loopback tests. Development and production suites ran sequentially, after backend tests, with a fresh database per run.

The [GitHub verification workflow](https://github.com/modhack2003/agentverse/actions/workflows/ci.yml) runs the shipped backend and browser suites, production build, Docker build and container smoke checks for the published commit.

## Remaining verification boundary

Live native vendor accounts/models, actual external provider bridges, Windows PowerShell, a real VPS/HTTPS/systemd deployment, Firefox/Safari and physical devices are not available in this environment. The acceptance matrix marks these combinations unverified. A fixture pass does not establish native vendor readiness.

The schema additions are additive; existing databases acquire recovery evidence, report timestamp and retained last-contact columns automatically. Existing nodes without the optional recovery payload display unknown until upgraded; launch/stop semantics and held-claim protection are unchanged.
