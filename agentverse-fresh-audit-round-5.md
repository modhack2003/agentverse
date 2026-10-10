# AgentVerse — fresh full audit, round 5

Tested on **10 October 2026**, against **`15fcd3cf4b1b02867d625dae9d4c5c80fb059ca3`**, “Fix history recovery and terminal pagination”.

Repository: [modhack2003/agentverse](https://github.com/modhack2003/agentverse)

## Assessment

The latest commit fixes the browser reconnect/history failure and the concrete terminal memory draft-loss reproduction. Terminal initial history, private-message filtering, engineering/reviews channels and history buttons are substantially improved. **Three medium-severity user problems remain:** terminal refresh gaps, duplicate creation after a successful save followed by failed refresh, and lost terminal invitation drafts after server rejection. No previously reproduced high-severity runtime or credential failure regressed in the tested paths.

The broad backend run passed all 80 checks. Eleven additional terminal checks produced seven failed desired-behavior assertions, grouped into the three problems below, and four passes. Browser testing completed 27 development scenarios: 25 passed and two immediate resize measurements failed. Ten selected production-build scenarios subsequently passed, including both affected workflows with settled-layout checks. The original local browser failures are retained in the report, not counted as an entirely green shipped suite.

This audit started from a new detached checkout of the published GitHub commit. Python dependencies were installed into a new environment with `uv sync --frozen --extra dev`, frontend dependencies with `npm ci`, and tests used new databases and temporary Git repositories. Frontend and Python distributions were built again. The earlier checkout and its application data were not used as the test installation.

Application source and shipped tests were left unchanged. Independent probes were added only to the local audit checkout. No fixes, commits, pushes, or GitHub issues were created. This report distinguishes successful checks, reproduced user problems, source-reviewed limitations, and integrations that were unavailable for live testing.

## Verification results

| Check | Result |
|---|---|
| Exact current GitHub main | `15fcd3cf4b1b02867d625dae9d4c5c80fb059ca3`; rechecked at audit completion |
| Fresh locked installations | New Python environment, 52 locked packages; `npm ci`, 75 frontend packages |
| Shipped backend suite before audit additions | **55 passed**, 48.47 seconds |
| Expanded backend suite | **80 passed**, 84.78 seconds, including all shipped checks, 19 earlier independent checks and six history/contract/native-MCP/TUI checks |
| New terminal probes | **4 passed, 7 failed**, 42.89 seconds, representing three distinct product defects across 11 cases; **91 distinct backend cases** total, 84 passing and seven defect assertions failing |
| Python lint on shipped tree | `uv run ruff check src tests` passed |
| Frontend build | TypeScript and Vite passed; 1,589 modules; fresh production JS/CSS emitted |
| Python distributions | Wheel and source distribution built successfully |
| Separate wheel installation | Both import/CLI aliases, SDK identity, doctor and example configurations checked |
| Expanded development-browser run | **25 passed, 2 failed**, 4.9 minutes, out of 27 scenarios; both failures were immediate resize width assertions |
| Compiled production-browser run | **10 passed**, 1.4 minutes; includes both failed workflows with settled-layout checks, owner onboarding, remote launch/stop, and six burst/gap scenarios |
| Desktop/mobile visual review | Agents/connections screenshots inspected; mobile navigation and section layouts exercised |
| Exact-commit CI | **55 backend + 10 shipped browser scenarios passed**, plus Docker build and both-prefix container smoke checks |

The complete development-browser run was **not** fully green. An earlier concurrent attempt was stopped after timeouts; it does not count as a completed suite. The subsequent independent run finished and failed two immediate width comparisons during viewport resizing. Both workflows passed against the compiled frontend with checks waiting for settled layout; the instrumented 390-pixel case reported `scrollWidth: 390`. No persistent mobile overflow was established. Preserve these failures as browser-test reliability findings, add settled-layout assertions and capture offending elements when they fail. Do not describe the original shipped browser run as passing locally.

The production browser run did not repeat every one of the 27 scenarios; it exercised ten selected critical scenarios and the two failed workflows. Across the two runs, every listed workflow was exercised, but this is not a statement of exhaustive branch coverage or a browser/device performance benchmark. Audit browser runs used emulated reduced motion; the shipped appearance scenario tests all seven theme choices and motion preferences.

The backend emits a FastAPI/Starlette TestClient deprecation warning. npm emits an inherited proxy-setting warning and test tooling emits color-environment warnings. These are recorded separately from the reproduced product defects.

Exact-commit CI: [successful workflow run](https://github.com/modhack2003/agentverse/actions/runs/38071630317). The job completed successfully, including all **55 backend tests**, **10 shipped browser scenarios**, Docker image construction, and smoke checks for both environment-variable prefixes. Its smoke output confirms production frontend, installed SDK/CLI aliases, MCP, non-root operation, and persistence of workspace data and tokens. This is remote CI evidence; Docker was unavailable locally.

Local environment: Python 3.12.14, Node 24.19.0, uv 0.12.23, Chromium 153.0.8010.0. Local API checks ran without inherited external proxy variables. Browser servers bound to loopback and used fresh random database filenames. The packaged wheel was installed into a separate environment; both import namespaces refer to the same SDK class, both CLI aliases run, and CLI/API example configurations parse. Doctor correctly reports missing local vendor executables and repository setup while keeping the connected editor profile independent.

## Remaining user problems

| ID | Severity | Status | User impact |
|---|---|---|---|
| AV-21 | Medium | Partial fix | Terminal can omit intermediate messages/help after a burst and disable history navigation |
| AV-26 | Medium | New | Retrying a reopened terminal creation form can duplicate an already-saved project |
| AV-27 | Medium | New | Invalid terminal agent/node invitations close the form and lose editable fields |

### AV-21 — terminal refresh gaps still hide retained coordination history

**Partial fix; medium severity.** The old terminal snapshot-truncation reproduction is fixed: 21 help requests are displayed, an older private message survives general-channel flooding, and ordinary initial-load pagination works. Engineering and reviews are now selectable and send through the correct channel.

A different history-completeness failure remains. Open a terminal conversation containing five messages and wait for its initial load. Let 205 more messages arrive before the next successful refresh, then refresh the same conversation. The API retains all 210, but the terminal merges the original five with only the newest 100. It shows 105 messages, misses the first 105 messages of the new burst, and disables **Older messages**. The same reproduction was exercised for general, engineering, and a private conversation. A help view initially containing five requests similarly loses access to intermediate requests when 205 arrive between refreshes.

Cause: `src/agentcommons/tui.py:298–308` fetches one recent page and only initializes the older-history flags when no rows were previously loaded. It does not bridge from the recent window back to the already-loaded window. Simply enabling the button is insufficient for chat: `load_older_chat` uses the earliest retained message as its cursor, which would skip the missing middle interval.

**User impact:** a busy workspace or a disconnected terminal can hide conversations, handoffs, and help requests while the data remains stored. Reopening the terminal, or switching conversations to force an initial load, restores the ordinary pagination path. Help can be recovered by restarting the terminal; the browser or filtered REST endpoints are other workarounds.

**Suggested fix:** maintain a contiguous history window. Fetch recent pages back to a known anchor, deduplicate, and calculate older availability from the oldest contiguous page. Apply the same logic to help requests. Add existing-history burst cases to terminal CI, rather than testing only initial pagination.

### AV-26 — terminal retries a creation that already succeeded

**New finding; medium severity.** In the terminal, create a project. Its POST succeeds and the project exists in the database. Simulate a failure of the following `/api/projects` list refresh. The application reopens the filled creation form and presents Save again. Pressing Save creates a second project with the same name and goal. The probe confirms a count of one before retry and two afterwards.

Cause: `CommonsTUI.form`, `src/agentcommons/tui.py:376–393`, places both the mutation and subsequent list refresh in one exception block. Its new draft-restoration path cannot distinguish a rejected save from a successful save followed by failed refresh. This branch is shared by other non-secret forms; duplicate project creation is the concrete tested case.

**User impact:** a temporary connection/server error can make a successful operation appear unsuccessful and invite duplicates. This is separate from AV-20, whose browser reproduction remains fixed.

**Suggested fix:** record successful mutation separately, close the creation form after success, retain/select the returned resource, and show a refresh-specific retry action. The refresh retry must repeat the GET rather than the POST. Keep draft restoration for errors that occur before successful persistence.

### AV-27 — rejected terminal invitations still discard entered fields

**New finding; medium severity for teammate onboarding.** With the real terminal and live API, open Add teammate, enter capabilities and limitations, and use an 81-character name. The server correctly rejects it with HTTP 422 because the maximum is 80. No teammate is created, but the form closes instead of keeping the entered fields for correction. Add remote node behaves similarly for a 101-character name, beyond its 100-character limit. Both probes confirm zero created resources and no remaining form.

Cause: `FormScreen` dismisses before submission, and the new recovery block in `CommonsTUI.form` only restores forms when `not secret` (`src/agentcommons/tui.py:386–393`). Agent and node invitation forms use `secret=True` because their successful responses include a one-time connection token. That flag also suppresses draft recovery when the save is rejected before any token is created.

**User impact:** a validation mistake during agent/node setup forces the user to reopen the dialog and retype the metadata. The old memory-edit draft bug is fixed, but invitation error recovery still needs the same protection.

**Suggested fix:** retain entered invitation metadata when the server explicitly rejects the operation. Separate token-display handling after successful creation from pre-success draft preservation. Add client field limits and server-error regressions. Avoid automatically replaying ambiguous network failures without checking whether a creation already succeeded.

## Changes verified from the previous round

| Previous issue | Current assessment |
|---|---|
| AV-21: snapshot truncation, missing DM, missing terminal channels | Original reproductions fixed; remaining terminal refresh-gap defect described above |
| AV-24: browser overflow/reconnect history | Fixed in tested paths. Empty, five-message and fully loaded 105-message conversations recover 205-message bursts; engineering, private messages and sending during a gap also pass on the compiled UI. |
| AV-25: terminal memory conflict discards draft | Original reproduction fixed. The filled form is restored and the concurrent server edit remains protected. A plain stale-version retry must continue to fail safely; automatic overwriting would be incorrect. |

Conflict resolution still requires an explicit workflow: preserve/copy the draft, cancel, refresh and reopen the latest version, review it, then deliberately reapply the change. A compare/reapply action would improve both clients, but the absence of automatic overwrite is not counted as a defect. An early audit assertion incorrectly expected a plain stale-version retry to save; that assertion was replaced by checks for draft preservation, version protection, and deliberate reapplication.

## Coverage across the project

| Area | Executed or reviewed | Outcome / boundary |
|---|---|---|
| Login | Token and configured password modes, invalid credentials, Unicode, disabled unconfigured password login, throttling | Passed tested cases |
| Sessions | Scoped identity, normal logout revocation, expiry, password change, environment prefixes | Passed normal tested paths; network-failed logout needs better feedback |
| Authorization | Admin/agent/node permissions, foreign projects/resources, revoked tokens, private messages and events | Passed tested cases |
| Project onboarding | Name/goal/repository fields, auto planning, empty states, project switching, pause/resume | Browser passed; terminal can duplicate a successfully saved project after refresh failure, AV-26 |
| Six main browser sections | Overview, task board, conversations, memory, reviews, agents/connections | Visited as owner and scoped agent; mobile navigation exercised |
| Themes and accessibility | All seven themes, persistence, motion settings, reduced motion, focus trap/restoration, blocked storage | Shipped browser tests passed; wider assistive-technology coverage remains unverified |
| Tasks | Creation, priority, dependencies, capability fields, search, details, release, invalid edits and cycle prevention | Passed tested cases; existing-task editing is an API capability without an ordinary dashboard edit flow |
| Planning | Atomic ownership, structured plan output, ordered dependent tasks, invalid-plan rollback | Passed; already-owned real worker planning completes safely after pause |
| Peer reviews | Independent ownership, self-review rejection, review release, approval/change requests, history, diff view | Passed; administrator cannot release an active managed review before termination |
| Real Git collaboration | Two independent clones/workers, planning, code commit, push, peer review and integrated merge | Passed deterministic real-Git fixture; model output was simulated |
| Shared memory | Create/edit/tags/search, versions, concurrent conflicts and restart persistence | Browser/API/TUI preserve the concrete memory-conflict draft; latest server version protected |
| Conversations | Three web channels, DMs, Enter send, live update, failed-send preservation/retry | Browser gap recovery retested; terminal refresh gaps remain, AV-21 |
| History UI and API | Cursor paging, active/help filters, resolved issue history, older channel and DM pages, invisible/foreign cursors | API and normal browser/TUI pagination passed; terminal refresh-gap navigation remains incomplete |
| Eight advertised identities | OpenCode, Cline, Omnirush, Agent Zero, Claude, Codex, Kiro, Antigravity onboarding and copied Python transport | All eight recipes executed with real announcement, introduction and heartbeat; native vendor runtime execution unverified |
| Custom/future tools | Arbitrary tool IDs, capability and limitation metadata | Passed shipped UI/API fixtures |
| Generated setup recipes | Copied token, actual metadata, blank unknown version, quoted name escaping, continuous heartbeat | Python tested; PowerShell source inspected, execution unavailable |
| Profiles | Description/capabilities/limitations edits, optimistic conflicts, scoped read-only UI, inherited runtime defaults | Passed tested paths |
| Remote node setup | Web/TUI invite, one-time token display, register/inventory/poll/disconnect, online/offline diagnostics | Normal and permission cases passed; terminal invitation validation drops draft fields, AV-27 |
| Three runtime modes | Managed CLI, managed API, connected editor/client; matching controls and model behavior | Passed deterministic adapter cases |
| Runtime settings | Choice/number/boolean controls, JSON settings, validation, every CLI placeholder, explicit required values without defaults | Passed backend and browser configuration/launch checks |
| Runtime health | Missing command/plugin/repo/base/origin and mixed healthy/broken profiles | Missing base/origin now disable managed launch through needs_setup; connected profiles remain independent |
| Launch/stop/revoke | Idempotency, capacity, external session/task/help guards, queued/running/stopping/terminal states | Passed tested cases |
| Identity fencing | Per-run tokens, expired leases, stale generations, stale node sessions, revoked identities | Passed tested cases |
| Execution profile changes | Launch snapshots current mode/contract; active changes rejected; health-only refresh permitted; node rejects mismatch before spawn | Passed; API takeover keeps claims unconfirmed, including conservative legacy-contract recovery |
| Process cleanup | Completion, timeout, stop, natural wrapper exit, SIGTERM-ignoring child heartbeat, supervisor stop and server-outage lease | Passed; former descendant leak did not reproduce |
| Managed API bridge | Completion, model/settings/auth, lost start response, idempotency lookup/tombstones, acknowledged and unconfirmed cancellation, malformed journals | Passed jobs-protocol fixture cases; actual provider bridge not available |
| Optional adapters | Healthy entry point, missing/broken/wrong-version plugin, protected built-ins | Passed tested cases |
| Peer help and problems | Capability routing, claim/release/answer, worker help, report/resolve, own-identity permissions | Normal paths passed; terminal can omit help created between refreshes, AV-21 |
| MCP | All 23 tools invoked over HTTP; native SDK initialization/list/call over a live server | Passed; vendor-specific client UIs/authentication not available |
| SDK and CLI packaging | agentverse/agentcommons aliases, clean wheel install, command help, doctor and sample JSON | Passed |
| Terminal UI | Project/task/agent/node/memory creation, token display, profile/runtime changes, launch/stop, chat/DM, help, health, pause and issue resolution | Normal workflows passed; AV-21/26/27 remain; original memory draft-loss case fixed |
| Realtime | Single-use tickets, scoped events, disconnect/revoke handling, unavailable WebSocket refresh | Browser reconnect/history recovery retested; terminal gap case remains, AV-21 |
| Persistence/migration | Old schema/data/tokens, additive migrations, database restart, retained task and memory | Shipped and independent checks passed; real production backup/restore not performed |
| Deployment | Dockerfile, Compose, Caddy, services and migration guidance reviewed | Exact-commit Docker CI passed; live HTTPS/VPS/systemd execution unavailable |



## Previous findings retested

| Finding | Current status | Evidence |
|---|---|---|
| AV-01 active managed manual release | Fixed in tested paths | Tasks/help/reviews protected until terminal report; replacement review cannot claim early |
| AV-02 stale mode and unsafe takeover | Fixed in tested paths | Launch snapshots current API mode/driver; active contract drift blocked; takeover preserves uncertain claims |
| AV-03 surviving descendants | Fixed in tested paths | Ignoring child heartbeats stop on completion, timeout and supervisor termination; shipped success/timeout/stop/natural-exit checks pass |
| AV-04 owned work after pause | Fixed | Real planning invocation completes and creates tasks after pause; banner now describes owned work correctly |
| AV-05 MCP task capabilities | Fixed | Actual create_task tool call accepts and stores required_capabilities |
| AV-06 launch alongside external help claim | Fixed | Managed launch guard checked by shipped test |
| AV-07 required CLI setting | Fixed in tested paths | Explicit values without defaults validate, save and launch; all placeholders inspected |
| AV-08 misleading Git availability | Fixed | Missing base/origin reports needs_setup, disabling managed launch |
| AV-09 missing SOCKS dependency | Fixed | Fresh lock installs httpx SOCKS support; SDK construction works |
| AV-10 runtime limitations | Fixed for original case | Advertised defaults populate otherwise-empty identity and remain visible |
| AV-11 public default password | Fixed | No unconfigured password fallback; controlled 503 until configured |
| AV-12 scoped token login | Fixed | Scoped UI and API permissions preserved |
| AV-13 logout/session revocation | Fixed in tested normal paths | Captured web token rejected after normal logout; credential change and expiry invalidate sessions |
| AV-14 Unicode credentials | Fixed | Correct Unicode credentials accepted; invalid credentials controlled |
| AV-15 failed-login throttling | Fixed | Ten failed attempts followed by 429 |
| AV-16 unusable copied Python token setup | Fixed for original case | Recipes run without token environment setup when SDK is installed |
| AV-17 fabricated recipe identity/version | Fixed | Actual configured metadata used; no fabricated tool version |
| AV-18 quoted-name source syntax | Fixed in tested Python case | Valid quoted name yields parsable Python; PowerShell escaping reviewed |
| AV-19 stale cross-project DM recipient | Fixed | New project resets target to general and accepts a valid message in that project |
| AV-20 project duplication after failed refresh | Fixed | Returned project selected, form closes, refresh notice shown; retry refresh leaves one saved project |
| AV-21 hidden older coordination history | Partial | Original browser and terminal snapshot cases fixed; terminal can still skip refresh gaps, AV-21 below |
| AV-22 disconnected revoked WebSocket close | Fixed in tested paths | Endpoint tolerates already-disconnected socket; former exception probe no longer raises |
| AV-23 inherited coordinator credentials | Fixed in tested paths | Both prefixes' admin username/password/token and node token removed from command environment; dotenv reload disabled while provider key retained |



## Advertised features with important limits

| Feature | Confirmed in this audit | Limit |
|---|---|---|
| Named vendor support | Eight tool identities, onboarding metadata, copied Python announcement/introduction/heartbeat, generic connection plumbing | Native OpenCode, Cline, Omnirush, Agent Zero, Claude, Codex, Kiro, and Antigravity clients and paid model sessions were unavailable. A tool card or heartbeat is not evidence of useful autonomous coding. |
| Managed CLI | Real subprocesses and real Git worktrees, commits, pushes, reviews, merges, cancellation and cleanup | Model output was deterministic. Actual vendor command flags, login, account models and model quality require live acceptance tests. |
| Managed API | Jobs-protocol fixture, model/settings/authentication, idempotency, lost start response, completion, cancellation acknowledgement and durable recovery | An arbitrary chat-completions API does not implement the jobs contract. A real provider bridge and shared worktree filesystem were not supplied. |
| Connected editors/apps | Authenticated HTTP and native MCP transport, scoped announcement, all 23 MCP tools | Startup, model selection and shutdown remain in the external client. Native MCP attachment alone does not create an unattended work loop. |
| Complete history | Retention and filtered cursor endpoints; browser recovery and normal initial terminal pagination | Terminal multi-page refresh gaps remain, AV-21. |
| First-class terminal interface | Broad normal workflows and repaired memory draft preservation | Error recovery is incomplete for successful creations and rejected invitations, AV-26/27. Some web features still lack terminal parity. |
| Windows recipes | PowerShell source and escaping reviewed | PowerShell executable was unavailable. Actual Windows execution was not tested; managed supervisors are documented for Linux/macOS. |
| Production deployment | Local compiled frontend/persistence checks and exact-commit Docker CI | Live VPS networking, DNS, Caddy certificates, public HTTPS, firewall rules, systemd service lifecycle, and production backup/restore were not exercised. |
| Accessibility and browsers | Chromium, several narrow/mobile/tablet/desktop layouts, focus handling, reduced motion and blocked storage | Firefox/Safari, physical mobile devices, screen readers, full contrast/zoom audit and performance under real production load remain unverified. |

## Improvements after testing

1. Fix the terminal refresh gap and save-result handling, and add regressions for rejected invitations. Include post-success refresh failure separately from POST/network failure.
2. Add an SDK installation step directly beside **Copy Python setup**. Offer a bounded connection check that distinguishes transport presence from native agent readiness.
3. Publish a vendor/version acceptance matrix covering native authentication, MCP attachment, advertised models/settings, planning, committed implementation, independent review and confirmed stop. Mark unverified combinations visibly.
4. Add compare/reapply controls for memory/profile conflicts. Keep the server's version protection; provide a deliberate resolution path instead of asking users to manually copy and reopen drafts.
5. Add ordinary dashboard task editing and clearer node/token replacement and recovery controls. These are user-flow improvements, not new failures of the underlying task-edit API.
6. Improve failed-logout feedback and retry server-side revocation. Normal logout passes; the source's failed-request branch clears local state without establishing successful revocation.
7. Represent required boolean settings with no default as explicitly unset/true/false. Keep uncertain runtime recovery visible, including last contact, frozen execution contract, journal availability and cancellation evidence.
8. Make viewport checks wait for completed resize/layout. Record layout width and offending elements on failure. A screenshot or immediate synchronous width read taken during resize can produce ambiguous results.

## Reproduction and evidence appendix

The backend expansion retests the earlier runtime, credential, authorization, MCP and worker findings. Historical `test_retest_*` names may describe the former defect; their assertions now check corrected behavior. The round-five gap/creation/invitation probes assert desired behavior and therefore fail when the documented problem is reproduced.

Backend verification commands:

```bash
uv sync --frozen --extra dev
uv run ruff check src tests
uv run pytest -q
uv run pytest -q tests/test_collaboration.py tests/test_remote_control.py tests/test_team_and_adapters.py tests/test_worker_and_tui.py tests/test_audit_regressions.py tests/test_full_audit.py tests/test_round4_extensions.py
uv run pytest -q -s tests/test_round5_probes.py
npm ci --prefix web
npm run build --prefix web
uv build
```

For local HTTP execution, external proxy variables were unset. Playwright used a locally installed Chromium executable; the normal configured download was not reused as a test installation. The two audit configurations below specify new database paths and the compiled frontend check.

### Shipped backend output

```text
.......................................................                  [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /workspace/scratch/ecae45260a2e/agentverse-audit5-latest/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
55 passed, 1 warning in 48.47s

```

### Expanded backend output

```text
........................................................................ [ 90%]
........                                                                 [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /workspace/scratch/ecae45260a2e/agentverse-audit5-latest/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
80 passed, 1 warning in 84.78s (0:01:24)

```

### New terminal observations and failures

```text
{'target': 'general', 'server_count': 210, 'loaded_count': 105, 'gap_0_loaded': False, 'gap_104_loaded': False, 'older_disabled': True}
F{'target': 'engineering', 'server_count': 210, 'loaded_count': 105, 'gap_0_loaded': False, 'gap_104_loaded': False, 'older_disabled': True}
F{'target': 'private', 'server_count': 210, 'loaded_count': 105, 'gap_0_loaded': False, 'gap_104_loaded': False, 'older_disabled': True}
F{'server_count': 210, 'loaded_count': 105, 'gap_help_5_loaded': False, 'older_disabled': True}
F{'form_still_open': True, 'saved_content': 'Concurrent version two', 'saved_version': 2}
.{'invitation_kind': 'agent', 'form_remains_open': False, 'created_count': 0}
F{'invitation_kind': 'node', 'form_remains_open': False, 'created_count': 0}
F{'reopened_after_successful_post': True, 'project_count_after_retry': 2}
.{'terminal_size': (130, 45), 'history_buttons_work': True}
FAILED tests/test_round5_probes.py::test_terminal_refresh_bridges_a_multi_page_gap[general]
FAILED tests/test_round5_probes.py::test_terminal_refresh_bridges_a_multi_page_gap[engineering]
FAILED tests/test_round5_probes.py::test_terminal_refresh_bridges_a_multi_page_gap[private]
FAILED tests/test_round5_probes.py::test_terminal_help_refresh_retains_access_to_requests_inside_gap
FAILED tests/test_round5_probes.py::test_terminal_invitation_keeps_draft_on_validation_error[agent]
FAILED tests/test_round5_probes.py::test_terminal_invitation_keeps_draft_on_validation_error[node]
FAILED tests/test_round5_probes.py::test_terminal_creation_is_not_resubmitted_after_successful_post_and_failed_refresh
7 failed, 4 passed, 1 warning in 42.89s
```

The full failed desired-behavior assertions are reproducible from the independent terminal probe below. The second Save in the conflict check is expected to preserve the draft and reject the stale version; a deliberately reviewed reapplication subsequently saves version 3. Click-based pagination checks passed at both tested terminal sizes.

### Completed development-browser output

```text
[WebServer] INFO:     Started server process [21]
[WebServer] INFO:     Waiting for application startup.

[WebServer] [10/10/26 07:52:45] INFO     StreamableHTTP       streamable_http_manager.py:164
[WebServer]                              session manager                                    
[WebServer]                              started                                            
[WebServer] INFO:     Application startup complete.

[WebServer] INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)

[WebServer] npm warn Unknown env config "http-proxy". This will stop working in the next major version of npm.

[WebServer] (node:40) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
[WebServer] (Use `node --trace-warnings ...` to show where the warning was created)


Running 27 tests using 1 worker

(node:59) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)


[1/27] tests/agentverse.spec.ts:7:1 › seven themes persist, motion respects accessibility, and dialogs keep keyboard focus
[2/27] tests/agentverse.spec.ts:39:1 › one-time teammate token survives a failed post-save refresh
[WebServer] INFO:     127.0.0.1:57970 - "WebSocket /api/live?ticket=dgOyxK8BoxdvFw0geyJQtnAiaKLUizgFACozri2FoMg&after=1" [accepted]

[WebServer] INFO:     connection open

[3/27] tests/agentverse.spec.ts:54:1 › blocked browser storage does not break login or themes
[WebServer] INFO:     127.0.0.1:60964 - "WebSocket /api/live?ticket=hUTuePudC8nhAx0Wh0BD32iWESgmpRQW7IKCKjj31_k&after=2" [accepted]
[WebServer] INFO:     connection open

[4/27] tests/agentverse.spec.ts:66:1 › future tools, typed settings, external modes, profiles, issues, and capability help
[WebServer] INFO:     127.0.0.1:32826 - "WebSocket /api/live?ticket=Jqh5T7Rwet7U8Gg-ZUn1U7zC59bvOjqEwjVLCu7HW-Q&after=6" [accepted]
[WebServer] INFO:     connection open

  1) tests/agentverse.spec.ts:66:1 › future tools, typed settings, external modes, profiles, issues, and capability help 

    Error: expect(received).toBe(expected) // Object.is equality

    Expected: true
    Received: false

      127 |   if (process.env.UPDATE_SCREENSHOTS) await page.screenshot({ path: '../docs/assets/daylight.png', fullPage: true })
      128 |   await page.setViewportSize({ width: 390, height: 844 })
    > 129 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      |                                                                                         ^
      130 | })
      131 |
      at /workspace/scratch/ecae45260a2e/agentverse-audit5-latest/web/tests/agentverse.spec.ts:129:89

    Error Context: test-results/agentverse-future-tools-ty-bf921--issues-and-capability-help/error-context.md

    attachment #2: trace (application/zip) ─────────────────────────────────────────────────────────
    test-results/agentverse-future-tools-ty-bf921--issues-and-capability-help/trace.zip
    Usage:

        npx playwright show-trace test-results/agentverse-future-tools-ty-bf921--issues-and-capability-help/trace.zip

    ────────────────────────────────────────────────────────────────


(node:195) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)


[5/27] tests/full-audit.spec.ts:24:1 › scoped token login preserves identity, restricts controls and visits every section
[WebServer] INFO:     127.0.0.1:51262 - "WebSocket /api/live?ticket=IzC6ZI_8D3xS9IoIITXgcVZbAWKWWZCOpS9TsL-_rMY&after=17" [accepted]
[WebServer] INFO:     connection open

  2) tests/full-audit.spec.ts:24:1 › scoped token login preserves identity, restricts controls and visits every section 

    Error: expect(received).toBe(expected) // Object.is equality

    Expected: true
    Received: false

      44 |   for(const size of [{width:320,height:740},{width:768,height:1024}]) {
      45 |     await page.setViewportSize(size)
    > 46 |     expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
      |                                                                                       ^
      47 |   }
      48 |   expect(errors).toEqual([])
      49 | })
      at /workspace/scratch/ecae45260a2e/agentverse-audit5-latest/web/tests/full-audit.spec.ts:46:87

    Error Context: test-results/full-audit-scoped-token-lo-f86b2-ls-and-visits-every-section/error-context.md

    attachment #2: trace (application/zip) ─────────────────────────────────────────────────────────
    test-results/full-audit-scoped-token-lo-f86b2-ls-and-visits-every-section/trace.zip
    Usage:

        npx playwright show-trace test-results/full-audit-scoped-token-lo-f86b2-ls-and-visits-every-section/trace.zip

    ────────────────────────────────────────────────────────────────


(node:277) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)


[6/27] tests/full-audit.spec.ts:51:1 › password form reports invalid credentials and logout revokes captured session
[WebServer] INFO:     127.0.0.1:58694 - "WebSocket /api/live?ticket=T0rhCdVUy4T5gwkBS96kq1TV3M7mdkNhCZ9apeazGFc&after=16" [accepted]
[WebServer] INFO:     connection open

[7/27] tests/full-audit.spec.ts:69:1 › copied HTTP Python setup works for all eight advertised tool identities
[WebServer] INFO:     127.0.0.1:54100 - "WebSocket /api/live?ticket=TE2E7f9rtwbGzGZCKO877la_bhJbFbq1LNazCYOsnp8&after=18" [accepted]
[WebServer] INFO:     connection open

[8/27] tests/full-audit.spec.ts:96:1 › retest ordinary double quote in agent name breaks copied Python recipe
[WebServer] INFO:     127.0.0.1:53580 - "WebSocket /api/live?ticket=PNxgDWBrV2o3FqsgApzwEG1zIF73-0CQiuUNkDhi6Lk&after=43" [accepted]

[WebServer] INFO:     connection open

[9/27] tests/full-audit.spec.ts:109:1 › memory and profile conflicts preserve edits and show controlled errors
[WebServer] INFO:     127.0.0.1:60964 - "WebSocket /api/live?ticket=tHyXfa4iXbtsPvFIfJ3goF2rks9kUG4Dge0-1YhjKN4&after=47" [accepted]

[WebServer] INFO:     connection open

[10/27] tests/full-audit.spec.ts:131:1 › failed save and failed chat preserve user input and permit retry
[WebServer] INFO:     127.0.0.1:46886 - "WebSocket /api/live?ticket=o_vVWaHQW0gluKI0onWuwL7xzyiPGbTfxbVpWhL8ugk&after=50" [accepted]
[WebServer] INFO:     connection open

[11/27] tests/full-audit.spec.ts:171:1 › retest switching projects retains an invalid DM recipient
[WebServer] INFO:     127.0.0.1:60172 - "WebSocket /api/live?ticket=hwT15fkbn_FXQXx1aMcR8XJ5Mx5NTKABARx43EfLaCY&after=56" [accepted]
[WebServer] INFO:     connection open

[WebServer] INFO:     127.0.0.1:60240 - "WebSocket /api/live?ticket=OooX1qPWUsgeZ6G6MHjUEZmVrX1xQctkVJzVh7Yi7xI&after=55" [accepted]
[WebServer] INFO:     connection open

[WebServer] INFO:     127.0.0.1:60310 - "WebSocket /api/live?ticket=cGv9Jf3y-VkB6xP3ropLI26RzXbDQouhxCdliTudUvE&after=56" [accepted]

[WebServer] INFO:     connection open

[12/27] tests/full-audit.spec.ts:171:1 › review page, task release, revoke confirmation, keyboard shortcut and all mobile sections
[WebServer] INFO:     127.0.0.1:60446 - "WebSocket /api/live?ticket=cHeJAi_zFa3A5iNnqPH2w9oiV66Ow7g4clt7GhKPYkc&after=62" [accepted]
[WebServer] INFO:     connection open

[13/27] tests/full-audit.spec.ts:211:1 › retest saved project remains in dialog and retry duplicates it after list refresh fails
[WebServer] INFO:     127.0.0.1:51720 - "WebSocket /api/live?ticket=n1-7gjsefjk1xEPrVU2iuwfGVK7XPHRfaOmUUJDUo3s&after=71" [accepted]
[WebServer] INFO:     connection open

[14/27] tests/full-audit.spec.ts:231:1 › retest older open help and older channel messages disappear without pagination
[WebServer] INFO:     127.0.0.1:53420 - "WebSocket /api/live?ticket=e5IEe6BVu35iJglEPi-ULX--CEOjUPTDNq-2RaJW0eA&after=193" [accepted]
[WebServer] INFO:     connection open

[15/27] tests/full-audit.spec.ts:250:1 › task dependency/capability fields, search, clipboard failure and live fallback
[WebServer] INFO:     127.0.0.1:39966 - "WebSocket /api/live?ticket=bAdjK2s4uxn-8-oIf9iNEXd08qbqAcWchj3wjgBQ-7o&after=195" [accepted]
[WebServer] INFO:     connection open

[16/27] tests/history-recovery.spec.ts:8:3 › conversation recovers a multi-page reconnect burst after 0 messages
[17/27] tests/history-recovery.spec.ts:8:3 › conversation recovers a multi-page reconnect burst after 5 messages
[18/27] tests/history-recovery.spec.ts:8:3 › conversation recovers a multi-page reconnect burst after 105 messages
[19/27] tests/remote-control.spec.ts:7:1 › dashboard registers a node, selects a model, launches, stops, and reconfigures a teammate
[WebServer] INFO:     127.0.0.1:60820 - "WebSocket /api/live?ticket=1g9SHmvZ0je23Tl8C69ispJpQ6e_yVZDtO2uFv-vbVg&after=927" [accepted]

[WebServer] INFO:     connection open

[20/27] tests/round4-extensions.spec.ts:15:1 › history controls load all help, resolved problems, channel pages and private pages
[WebServer] INFO:     127.0.0.1:38034 - "WebSocket /api/live?ticket=iPmqoDeBgi8PKd0wP9Y0WRh_7pr_1Brt9GaDlH7u1-M&after=1360" [accepted]

[WebServer] INFO:     connection open

[21/27] tests/round4-extensions.spec.ts:52:1 › live refresh retains access to older messages when conversation crosses 100 messages
[22/27] tests/round4-extensions.spec.ts:77:1 › required runtime settings without defaults can be saved and launched through the form
[WebServer] INFO:     127.0.0.1:58268 - "WebSocket /api/live?ticket=wU_yUAnE-Bsrf3z_12MWoyynipjvqGrDFhcelmGA1CM&after=1470" [accepted]
[WebServer] INFO:     connection open

[23/27] tests/round5-recovery.spec.ts:8:3 › independent gap recovery: engineering
[24/27] tests/round5-recovery.spec.ts:8:3 › independent gap recovery: private
[25/27] tests/round5-recovery.spec.ts:8:3 › independent gap recovery: send-during-gap
[26/27] tests/workspace.spec.ts:6:1 › owner creates a project, connects a teammate, chats, manages tasks and memory
[WebServer] INFO:     127.0.0.1:39258 - "WebSocket /api/live?ticket=CUvsxXyCTI7KcBb_vf0io77vCUzB551O2BekhkRhkMI&after=2109" [accepted]
[WebServer] INFO:     connection open

[WebServer] INFO:     127.0.0.1:39342 - "WebSocket /api/live?ticket=b2zJdu-MMYcDPwme5IE1WgLQBu0HJ5y-mavl4eeWjz4&after=2111" [accepted]

[WebServer] INFO:     connection open

[27/27] tests/workspace.spec.ts:58:1 › dashboard live updates, task details, DMs, and mobile navigation
[WebServer] INFO:     127.0.0.1:42412 - "WebSocket /api/live?ticket=ZESGY4-TcpyfufqL-diq_N6maOz0T-I4UIxt9FSxPPA&after=2140" [accepted]

[WebServer] INFO:     connection open

  2 failed
    tests/agentverse.spec.ts:66:1 › future tools, typed settings, external modes, profiles, issues, and capability help 
    tests/full-audit.spec.ts:24:1 › scoped token login preserves identity, restricts controls and visits every section 
  25 passed (4.9m)

```

### Compiled production-browser output

```text
[WebServer] INFO:     Started server process [21]
[WebServer] INFO:     Waiting for application startup.

[WebServer] [10/10/26 07:57:51] INFO     StreamableHTTP       streamable_http_manager.py:164
[WebServer]                              session manager                                    
[WebServer]                              started                                            

[WebServer] INFO:     Application startup complete.

[WebServer] INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)


Running 10 tests using 1 worker

(node:27) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)


[1/10] tests/full-audit.spec.ts:24:1 › scoped token login preserves identity, restricts controls and visits every section
[WebServer] INFO:     127.0.0.1:43888 - "WebSocket /api/live?ticket=0tlh7XVLKueGGZrZUs45m2yYmKNS7cYlQc8wViEiS2U&after=3" [accepted]
[WebServer] INFO:     connection open

[2/10] tests/history-recovery.spec.ts:8:3 › conversation recovers a multi-page reconnect burst after 0 messages
[3/10] tests/history-recovery.spec.ts:8:3 › conversation recovers a multi-page reconnect burst after 5 messages
[4/10] tests/history-recovery.spec.ts:8:3 › conversation recovers a multi-page reconnect burst after 105 messages
[5/10] tests/remote-control.spec.ts:7:1 › dashboard registers a node, selects a model, launches, stops, and reconfigures a teammate
[WebServer] INFO:     127.0.0.1:54404 - "WebSocket /api/live?ticket=uvqVe0gI5idAgAc6WkokbxB-BXRejPga6lS8o7An_eQ&after=733" [accepted]

[WebServer] INFO:     connection open

[6/10] tests/round5-recovery.spec.ts:8:3 › independent gap recovery: engineering
[7/10] tests/round5-recovery.spec.ts:8:3 › independent gap recovery: private
[8/10] tests/round5-recovery.spec.ts:8:3 › independent gap recovery: send-during-gap
[9/10] tests/round5-responsive.spec.ts:66:1 › settled layout: future tools, typed settings, external modes, profiles, issues, and capability help
[WebServer] INFO:     127.0.0.1:48166 - "WebSocket /api/live?ticket=aDy6gdP9fh7xqm_jPxdWirdpDNH5v_u1JpZc3qYUbQI&after=1383" [accepted]
[WebServer] INFO:     connection open

tests/round5-responsive.spec.ts:66:1 › settled layout: future tools, typed settings, external modes, profiles, issues, and capability help
resize immediate { width: 390, scroll: 390 }

resize settled { width: 390, scroll: 390 }

[10/10] tests/workspace.spec.ts:6:1 › owner creates a project, connects a teammate, chats, manages tasks and memory
[WebServer] INFO:     127.0.0.1:33664 - "WebSocket /api/live?ticket=mkbWTMmW2yUrJdyPXiXZY_x9zjybDwpsZowdtgXSgMs&after=1391" [accepted]

[WebServer] INFO:     connection open

[WebServer] INFO:     127.0.0.1:33668 - "WebSocket /api/live?ticket=MPLTHRnXdIRd3QTkeGPFLSvVrl2M3Pu0RpFgHBNMnws&after=1393" [accepted]

[WebServer] INFO:     connection open

  10 passed (1.4m)

```

### Build outputs

```text
npm warn Unknown env config "http-proxy". This will stop working in the next major version of npm.

> agentverse-web@0.2.0 build
> tsc -b && vite build

vite v6.4.4 building for production...
transforming...
✓ 1589 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.65 kB │ gzip: 0.40 kB
dist/assets/index-DeZPspfV.css   56.45 kB │ gzip: 12.36 kB
dist/assets/index-CvhtxW63.js   318.59 kB │ gzip: 95.09 kB
✓ built in 4.72s
Building source distribution...
Building wheel from source distribution...
Successfully built dist/agentverse_workspace-0.2.0.tar.gz
Successfully built dist/agentverse_workspace-0.2.0-py3-none-any.whl

```

### Independent reproduction scripts

These are audit additions, not committed project changes. The responsive copy reproduces the shipped future-tool workflow and replaces its final immediate width assertion with a settled-layout check and width logging. Its other shipped scenarios were not selected in the production follow-up. The shipped source file itself remained unchanged.

### tests/test_previous_observations.py

```python
SESSION = 'e' * 32

def runtime(client, p, a, mode='managed_api'):
    n = client.post(f'/api/projects/{p}/nodes', json={'name': 'Audit node'}).json()
    nh = {'Authorization': f"Bearer {n['token']}"}
    profile = {'id': 'runtime', 'name': 'Runtime', 'kind': 'custom', 'mode': mode}
    assert client.post('/api/nodes/me/register', headers=nh, json={'session_id': SESSION, 'profiles': [profile]}).status_code == 200
    base = f'/api/projects/{p}/agents/{a}'
    assert client.put(base + '/runtime', json={'node_id': n['node']['id'], 'profile_id': 'runtime'}).status_code == 200
    return n, nh, profile, base


```

### tests/test_full_audit.py

```python
"""Independent audit: positive regression checks and explicitly named observations."""
import asyncio
import json
import os
import shlex
import signal
import threading
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from agentcommons.server import create_app
from agentcommons.node import NodeConfig, NodeService, Child, LocalProfile
from agentcommons.drivers import CLIDriver
from agentcommons.worker import execute_agent
from conftest import TOKEN, agent, project
from test_previous_observations import runtime, SESSION


def running(c, p, a, mode='managed_api'):
    n, nh, profile, base = runtime(c, p, a, mode)
    assert c.post(base+'/launch').status_code == 200
    row = c.post('/api/nodes/me/poll', headers=nh, json={'session_id': SESSION}).json()['runtimes'][0]
    mh = {'Authorization': f"Bearer {row['token']}"}
    assert c.post('/api/nodes/me/report', headers=nh, json={'session_id': SESSION, 'agent_id': a, 'run_id': row['run_id'], 'state': 'running'}).status_code == 200
    return n, nh, profile, base, row, mh


def test_fixed_admin_release_task_and_help_wait_for_terminal_report(api):
    c, _ = api
    p = project(c)
    a, _, _ = agent(c, p, 'Managed')
    _, nh, _, _, row, mh = running(c, p, a)
    task = c.post(f'/api/projects/{p}/tasks', json={'title': 'Safe task'}).json()
    path = f"/api/projects/{p}/tasks/{task['id']}"
    assert c.post(path+'/claim', headers=mh).status_code == 200
    assert c.post(path+'/release', json={'reason': 'Manual release'}).status_code == 409
    help_request = c.post(f'/api/projects/{p}/help', json={'question': 'Safe help'}).json()
    hp = f"/api/projects/{p}/help/{help_request['id']}"
    assert c.post(hp+'/claim', headers=mh).status_code == 200
    assert c.post(hp+'/release').status_code == 409
    assert c.post('/api/nodes/me/report', headers=nh, json={'session_id': SESSION, 'agent_id': a, 'run_id': row['run_id'], 'state': 'stopped'}).status_code == 200
    assert c.get(f'/api/projects/{p}/tasks').json()[0]['status'] == 'backlog'
    assert c.get(f'/api/projects/{p}/snapshot').json()['help_requests'][0]['state'] == 'open'


def test_retest_admin_can_release_running_managed_review(api):
    c, _ = api
    p = project(c)
    a, _, _ = agent(c, p, 'Running reviewer')
    _, ah, _ = agent(c, p, 'Author')
    b, bh, _ = agent(c, p, 'Replacement reviewer')
    _, _, _, base, _, mh = running(c, p, a)
    task = c.post(f'/api/projects/{p}/tasks', json={'title': 'Review race'}).json()
    path = f"/api/projects/{p}/tasks/{task['id']}"
    assert c.post(path+'/claim', headers=ah).status_code == 200
    assert c.post(path+'/submit', headers=ah, json={'summary':'Code', 'branch':'feature', 'commit_sha':'a'*40}).status_code == 200
    assert c.post(path+'/review-claim', headers=mh).status_code == 200
    assert c.post(path+'/review-release').status_code == 409
    assert c.post(path+'/review-claim', headers=bh).status_code == 409
    assert c.get(f'/api/projects/{p}/snapshot').json()['agents'][0]['runtime']['state'] == 'running'
    assert c.post(base+'/stop').status_code == 200


def test_retest_inventory_mode_drift_releases_api_claim_on_takeover(api):
    c, store = api
    p = project(c)
    a, _, _ = agent(c, p, 'Drifting runtime')
    n, nh, profile, base = runtime(c, p, a, 'managed_cli')
    profile.update(mode='managed_api', driver='http')
    assert c.post('/api/nodes/me/inventory', headers=nh, json={'session_id':SESSION, 'profiles':[profile]}).status_code == 200
    assert c.post(base+'/launch').json()['mode'] == 'managed_api'
    row = c.post('/api/nodes/me/poll', headers=nh, json={'session_id':SESSION}).json()['runtimes'][0]
    mh = {'Authorization': f"Bearer {row['token']}"}
    task = c.post(f'/api/projects/{p}/tasks', json={'title':'Potential remote job'}).json()
    assert c.post(f"/api/projects/{p}/tasks/{task['id']}/claim", headers=mh).status_code == 200
    store.db.execute('UPDATE nodes SET last_seen=? WHERE id=?', (time.time()-91, n['node']['id']))
    assert c.post('/api/nodes/me/register', headers=nh, json={'session_id':'f'*32, 'profiles':[profile]}).status_code == 200
    snap = c.get(f'/api/projects/{p}/snapshot').json()
    assert snap['agents'][0]['runtime']['state'] == 'unconfirmed'
    assert snap['tasks'][0]['status'] == 'in_progress'


def test_fixed_unconfirmed_report_is_accepted_after_inventory_drift(api):
    c, _ = api
    p = project(c)
    a, _, _ = agent(c, p, 'Reported drift')
    _, nh, _, _, row, _ = running(c, p, a, 'managed_cli')
    assert c.post('/api/nodes/me/report', headers=nh, json={'session_id':SESSION, 'agent_id':a, 'run_id':row['run_id'], 'state':'unconfirmed'}).json()['state'] == 'unconfirmed'


def alive(pid):
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False


def wrapper(tmp_path, slow):
    pid_file = tmp_path/'descendant.pid'
    code = 'import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN)\nwhile True:\n pathlib.Path('+repr(str(tmp_path/'child-heartbeat'))+') .write_text(str(time.time()))\n time.sleep(.03)'
    script = tmp_path/'wrapper.py'
    script.write_text('import subprocess,sys,pathlib,time\n'+f'p=subprocess.Popen([sys.executable,"-c",{code!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n'+f'pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n'+'time.sleep(.2)\n'+('time.sleep(60)\n' if slow else 'print(\'```agentverse\\n{"summary":"done"}\\n```\')\n'))
    return pid_file, script


def test_fixed_completed_command_reaps_descendants(tmp_path):
    file, script = wrapper(tmp_path, False)
    assert execute_agent(shlex.join([sys.executable,str(script)]), 'audit',tmp_path,5)['summary'] == 'done'
    heartbeat=tmp_path/'child-heartbeat'
    before=heartbeat.read_text();time.sleep(.2)
    assert heartbeat.read_text()==before


def test_retest_timed_out_command_leaves_ignoring_descendant(tmp_path):
    file, script = wrapper(tmp_path, True)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            execute_agent(shlex.join([sys.executable,str(script)]),'audit',tmp_path,1)
        before=(tmp_path/'child-heartbeat').read_text();time.sleep(.2)
        assert (tmp_path/'child-heartbeat').read_text()==before
    finally:
        if file.exists() and alive(int(file.read_text())):
            os.kill(int(file.read_text()),signal.SIGKILL)


def test_retest_node_terminate_leaves_ignoring_descendant(tmp_path):
    file, script = wrapper(tmp_path, True)
    log = (tmp_path/'worker.log').open('w')
    p = subprocess.Popen([sys.executable,str(script)],start_new_session=True,stdout=log)
    try:
        deadline = time.monotonic()+5
        while not file.exists() and time.monotonic()<deadline:
            time.sleep(.01)
        time.sleep(.3)
        NodeService.terminate(Child('audit',p,log,None))
        assert p.poll() is not None
        before=(tmp_path/'child-heartbeat').read_text();time.sleep(.2)
        assert (tmp_path/'child-heartbeat').read_text()==before
    finally:
        if file.exists() and alive(int(file.read_text())):
            os.kill(int(file.read_text()),signal.SIGKILL)
        if p.poll() is None:
            p.kill(); p.wait()
        log.close()


def test_retest_explicit_required_setting_still_marks_profile_unlaunchable():
    profile = LocalProfile(id='required',name='Required',kind='custom',argv=[sys.executable,'{setting:effort}'],settings_schema=[{'key':'effort','label':'Effort','type':'choice','options':['low','high']}])
    assert CLIDriver().command(profile,'',{'effort':'high'}) == [sys.executable,'high']
    assert CLIDriver().check(profile)[0] == 'available'


@pytest.mark.parametrize('base', ['main','master'])
def test_retest_git_setup_warning_does_not_disable_availability(tmp_path,base):
    repo=tmp_path/'repo';repo.mkdir()
    for args in [['init','-b','master'],['-c','user.name=Audit','-c','user.email=audit@example.test','commit','--allow-empty','-m','Initial']]:
        subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True)
    service=NodeService('http://127.0.0.1:1','audit',NodeConfig(repo=str(repo),profiles=[{'id':'tool','name':'Tool','kind':'custom','argv':[sys.executable,'{prompt}'],'base':base,'push':True}]))
    try:
        report=service.inspect()['profiles'][0]
        assert report['availability']=='needs_setup'
        assert 'missing' in report['diagnostic'] or 'no origin' in report['diagnostic']
    finally:
        service.http.close()


def test_password_changes_expiry_restart_and_prefix_compatibility(api,monkeypatch,tmp_path):
    c,store=api
    monkeypatch.setenv('AGENTVERSE_ADMIN_USERNAME','audit')
    monkeypatch.setenv('AGENTVERSE_ADMIN_PASSWORD','pässword')
    assert c.post('/api/login',json={'username':'audit','password':'wrong'}).status_code==401
    token=c.post('/api/login',json={'username':'audit','password':'pässword'}).json()['token']
    h={'Authorization':f'Bearer {token}'}
    assert c.get('/api/me',headers=h).status_code==200
    monkeypatch.setenv('AGENTVERSE_ADMIN_PASSWORD','changed')
    assert c.get('/api/me',headers=h).status_code==401
    token=c.post('/api/login',json={'username':'audit','password':'changed'}).json()['token']
    store.admin_sessions[token]=(1,store.admin_credential_fingerprint())
    assert c.get('/api/me',headers={'Authorization':f'Bearer {token}'}).status_code==401
    monkeypatch.delenv('AGENTVERSE_ADMIN_USERNAME');monkeypatch.delenv('AGENTVERSE_ADMIN_PASSWORD')
    monkeypatch.setenv('AGENTCOMMONS_ADMIN_USERNAME','legacy')
    monkeypatch.setenv('AGENTCOMMONS_ADMIN_PASSWORD','legacy-pass')
    assert c.post('/api/login',json={'username':'legacy','password':'legacy-pass'}).status_code==200


def test_all_23_mcp_tools_over_http(api):
    c,_=api
    p=project(c,auto_plan=True)
    a,ah,_=agent(c,p,'MCP author')
    _,bh,_=agent(c,p,'MCP reviewer')
    used=set()
    def call(name,arguments=None,headers=ah):
        h={**headers,'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-06-18'}
        payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments or {}}}
        response=c.post('/mcp/',headers=h,json=payload)
        assert response.status_code==200,response.text
        result=response.json()['result'];assert not result.get('isError'),result
        used.add(name)
        return result.get('structuredContent',{}).get('result',result.get('structuredContent')) or json.loads(result['content'][0]['text'])
    call('announce_peer',{'capabilities':['python'],'limitations':['No browser'],'tool_version':'audit'})
    call('announce_peer',{'capabilities':['python']},bh)
    assert call('list_projects')[0]['id']==p
    call('list_teammates',{'project_id':p,'capability':'python'})
    call('heartbeat',{'status':'idle'})
    snap=call('project_context',{'project_id':p})
    planning=snap['tasks'][0]['id']
    call('claim_task',{'project_id':p,'task_id':planning})
    call('finish_plan',{'project_id':p,'task_id':planning,'summary':'Plan','tasks':[{'title':'Implement','required_capabilities':['python']}]})
    t=call('create_task',{'project_id':p,'title':'MCP capability task','required_capabilities':['python']})
    assert t['required_capabilities']==['python']
    args={'project_id':p,'task_id':t['id']}
    call('claim_task',args);call('release_task',{**args,'reason':'Retry'});call('claim_task',args)
    call('submit_work',{**args,'summary':'Work','branch':'feature','commit_sha':'a'*40,'diff':'+test'})
    call('claim_review',args,bh);call('release_review',args,bh);call('claim_review',args,bh)
    call('review_work',{**args,'decision':'approve','comment':'Inspected'},bh)
    mem=call('write_memory',{'project_id':p,'title':'Decision','content':'Shared context','tags':['audit']})
    call('write_memory',{'project_id':p,'title':'Decision2','content':'Updated','memory_id':mem['id'],'expected_version':1})
    call('read_memory',{'project_id':p})
    call('send_message',{'project_id':p,'content':'Private handoff','recipient_id':a},bh)
    call('team_inbox',{'project_id':p})
    issue=call('report_problem',{'project_id':p,'title':'Resolved fixture'})
    call('resolve_problem',{'project_id':p,'issue_id':issue['id']})
    help_row=call('request_help',{'project_id':p,'question':'Help','capability':'python'})
    hp={'project_id':p,'help_id':help_row['id']}
    call('claim_help',hp,bh);call('release_help',hp,bh);call('claim_help',hp,bh);call('answer_help',{**hp,'answer':'Helpful'},bh)
    listing=c.post('/mcp/',headers={**ah,'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}).json()['result']['tools']
    assert used=={t['name'] for t in listing}


def test_production_assets_spa_unknown_api_and_persistence(tmp_path):
    dist=Path(__file__).parents[1]/'web/dist'
    path=str(tmp_path/'persistent.db')
    app=create_app(path,TOKEN,str(dist))
    with TestClient(app,base_url='http://127.0.0.1',headers={'Authorization':f'Bearer {TOKEN}'}) as c:
        p=project(c)
        _,h,token=agent(c,p,'Persistent')
        task=c.post(f'/api/projects/{p}/tasks',json={'title':'Persisted'}).json()
        c.post(f"/api/projects/{p}/tasks/{task['id']}/claim",headers=h)
        c.post(f'/api/projects/{p}/memories',json={'title':'Stored','content':'Survives restart'})
        assert 'AgentVerse' in c.get('/').text
        assert c.get('/arbitrary/client/path').status_code==200
        for missing in ['/api/no-such-route','/assets/missing.js','/mcp/missing']:
            assert c.get(missing).status_code==404
        for file in (dist/'assets').iterdir():
            r=c.get('/assets/'+file.name);assert r.status_code==200
            assert r.headers['x-content-type-options']=='nosniff'
    app=create_app(path,TOKEN,str(dist))
    with TestClient(app,headers={'Authorization':f'Bearer {token}'}) as c:
        snap=c.get(f'/api/projects/{p}/snapshot').json()
        assert snap['tasks'][0]['status']=='in_progress'
        assert snap['memories'][0]['content']=='Survives restart'


def test_request_validation_edits_and_cycle_rejection(api):
    c,_=api
    p=project(c)
    a=c.post(f'/api/projects/{p}/tasks',json={'title':'First'}).json()
    b=c.post(f'/api/projects/{p}/tasks',json={'title':'Second','dependencies':[a['id']]}).json()
    assert c.patch(f"/api/projects/{p}/tasks/{a['id']}",json={'dependencies':[b['id']]}).status_code==422
    assert c.patch(f"/api/projects/{p}/tasks/{a['id']}",json={'title':'Edited','priority':'high','required_capabilities':['python']}).status_code==200
    for route,data in [(f'/api/projects/{p}/tasks',{'title':''}),(f'/api/projects/{p}/agents',{'name':''}),(f'/api/projects/{p}/memories',{'title':'Blank','content':''}),(f'/api/projects/{p}/messages',{'content':'a','channel':'Invalid'})]:
        assert c.post(route,json=data).status_code==422
    assert c.get(f'/api/projects/{p}/events?limit=501').status_code==422


def test_tui_remaining_creation_memory_health_pause_and_agent_permissions(live_server):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Input,TextArea,DataTable,TabbedContent
    url,c=live_server
    async def audit():
        app=CommonsTUI(url,TOKEN)
        async with app.run_test(size=(140,50)) as pilot:
            await pilot.pause(.3)
            app.action_new_project();await pilot.pause(.1)
            app.screen.query_one('#field-name',Input).value='TUI fresh project'
            app.screen.query_one('#field-goal',TextArea).text='Complete every terminal path'
            await pilot.click('#save');await pilot.pause(.5)
            app.action_new_task();await pilot.pause(.1)
            app.screen.query_one('#field-title',Input).value='TUI created task'
            await pilot.click('#save');await pilot.pause(.3)
            app.action_new_memory();await pilot.pause(.1)
            app.screen.query_one('#field-title',Input).value='TUI memory'
            app.screen.query_one('#field-content',TextArea).text='Terminal shared knowledge'
            await pilot.click('#save');await pilot.pause(.3)
            await app.action_toggle_pause();await pilot.pause(.2)
            assert c.get('/api/projects').json()[0]['status']=='paused'
            await app.action_toggle_pause();await pilot.pause(.2)
            assert c.get('/api/projects').json()[0]['status']=='active'
            app.query_one(TabbedContent).active='memory-tab'
            app.query_one('#memories',DataTable).focus()
            await pilot.press('enter');await pilot.pause(.2)
            app.screen.query_one('#field-content',TextArea).text='Updated terminal memory'
            await pilot.click('#save');await pilot.pause(.3)
            snap=c.get(f'/api/projects/{app.project_id}/snapshot').json()
            assert snap['memories'][0]['version']==2
            assert any(t['title']=='TUI created task' for t in snap['tasks'])
            app.action_add_agent();await pilot.pause(.1)
            app.screen.query_one('#field-name',Input).value='TUI invited peer'
            await pilot.click('#save');await pilot.pause(.2)
            assert 'CONNECTION TOKEN' in app.screen.text
            await pilot.press('escape');await pilot.pause(.3)
            app.action_add_node();await pilot.pause(.1)
            app.screen.query_one('#field-name',Input).value='TUI invited node'
            await pilot.click('#save');await pilot.pause(.2)
            assert 'CONNECTION TOKEN' in app.screen.text
            await pilot.press('escape');await pilot.pause(.3)
            app.refresh_remote();await pilot.pause(.3)
            app.query_one(TabbedContent).active='agents-tab'
            app.query_one('#agents',DataTable).focus()
            app.action_report_problem();await pilot.pause(.1)
            app.screen.query_one('#field-title',Input).value='TUI reported problem'
            await pilot.click('#save');await pilot.pause(.3)
            app.action_resolve_problem();await pilot.pause(.1)
            await pilot.click('#save');await pilot.pause(.3)
            snapshot=c.get(f'/api/projects/{app.project_id}/snapshot').json()
            assert snapshot['issues'][0]['resolved']==1
            assert snapshot['nodes'][0]['name']=='TUI invited node'
        await app.http.aclose()
    asyncio.run(audit())


def test_adapter_entry_point_accepts_healthy_plugin_and_ignores_broken_or_wrong_version(monkeypatch):
    from agentcommons.drivers import drivers
    class Adapter:
        protocol_version=1
        mode='managed_cli'
        def check(self,profile): return 'available','Audit plugin'
        def command(self,profile,model,settings): return [sys.executable,'{prompt_file}']
    class Entry:
        def __init__(self,name,broken=False,version=1): self.name,self.broken,self.version=name,broken,version
        def load(self):
            if self.broken: raise ImportError('Missing dependency')
            def instantiate():
                adapter=Adapter();adapter.protocol_version=self.version;return adapter
            return instantiate
    monkeypatch.setattr('agentcommons.drivers.importlib.metadata.entry_points',lambda **kw:[Entry('audit-plugin'),Entry('broken',True),Entry('future-version',version=2),Entry('cli',True)])
    available=drivers()
    assert set(available)=={'cli','http','connected','audit-plugin'}
    profile=LocalProfile(id='plugin',name='Plugin',kind='custom',driver='audit-plugin')
    assert available['audit-plugin'].check(profile)[0]=='available'
    assert available['audit-plugin'].command(profile,'',{})==[sys.executable,'{prompt_file}']


def test_retest_dashboard_password_is_inherited_by_agent_command(tmp_path,monkeypatch):
    for prefix in ('AGENTVERSE','AGENTCOMMONS'):
        monkeypatch.setenv(f'{prefix}_ADMIN_USERNAME','audit-only-admin')
        monkeypatch.setenv(f'{prefix}_ADMIN_PASSWORD','audit-only-password')
        monkeypatch.setenv(f'{prefix}_ADMIN_TOKEN','audit-admin-token')
        monkeypatch.setenv(f'{prefix}_NODE_TOKEN','audit-node-token')
    script=tmp_path/'read-env.py'
    script.write_text('import os,json\nprint(json.dumps({k:os.getenv(k) for p in ["AGENTVERSE","AGENTCOMMONS"] for k in [p+"_ADMIN_PASSWORD",p+"_ADMIN_USERNAME",p+"_ADMIN_TOKEN",p+"_NODE_TOKEN"]}))\n')
    result=execute_agent(shlex.join([sys.executable,str(script)]),'audit',tmp_path,5)
    for prefix in ('AGENTVERSE','AGENTCOMMONS'):
        assert result[f'{prefix}_ADMIN_TOKEN'] is None
        assert result[f'{prefix}_NODE_TOKEN'] is None
        assert result[f'{prefix}_ADMIN_PASSWORD'] is None
        assert result[f'{prefix}_ADMIN_USERNAME'] is None


def test_retest_revoked_disconnected_websocket_close_raises(api):
    from starlette.websockets import WebSocketDisconnect
    c,store=api
    p=project(c)
    a,h,_=agent(c,p,'Revoked live peer')
    ticket=c.post(f'/api/realtime-ticket?project_id={p}',headers=h).json()['ticket']
    assert c.delete(f'/api/projects/{p}/agents/{a}').status_code==200
    endpoint=next(route.endpoint for route in c.app.routes if getattr(route,'path',None)=='/api/live')
    class AlreadyDisconnected:
        async def accept(self): pass
        async def close(self,code): raise WebSocketDisconnect(1006)
    asyncio.run(endpoint(AlreadyDisconnected(),ticket))


def test_fixed_pause_allows_real_worker_owned_plan_to_finish(live_server, tmp_path):
    from agentcommons.worker import Worker
    url, c = live_server
    p = project(c)
    _, _, token = agent(c, p, 'Paused worker')
    t = c.post(f'/api/projects/{p}/tasks', json={'title': 'Plan before pause', 'kind': 'planning'}).json()
    repo = tmp_path / 'repo'
    repo.mkdir()
    for argv in [['init', '-b', 'main'], ['config', 'user.email', 'audit@example.invalid'], ['config', 'user.name', 'Audit'], ['commit', '--allow-empty', '-m', 'initial']]:
        subprocess.run(['git', *argv], cwd=repo, check=True, capture_output=True)
    ready, proceed = tmp_path / 'ready', tmp_path / 'proceed'
    wrapper = tmp_path / 'planner.py'
    wrapper.write_text('import pathlib,time\n' + f'pathlib.Path({str(ready)!r}).touch()\n' +
        f'while not pathlib.Path({str(proceed)!r}).exists(): time.sleep(0.01)\n' +
        'print(\'```agentverse\\n{"summary":"Valid plan", "tasks":[{"title":"Implement"}]}\\n```\')\n')
    errors = []
    worker = Worker(url, token, repo, shlex.join([sys.executable, str(wrapper)]), push=False)
    def run():
        try:
            worker.run(once=True)
        except BaseException as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        assert c.patch(f'/api/projects/{p}', json={'status': 'paused'}).status_code == 200
        proceed.touch()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert errors == []
        tasks = c.get(f'/api/projects/{p}/tasks').json()
        assert len(tasks) == 2 and tasks[0]['id'] == t['id'] and tasks[0]['status'] == 'done'
    finally:
        proceed.touch()
        thread.join(timeout=10)


```

### tests/test_round4_extensions.py

```python
"""Independent fresh audit: pagination, inventory and terminal boundaries."""
import asyncio
import json
import subprocess
import sys

from conftest import TOKEN, agent, project
from agentcommons.node import NodeConfig, NodeService
from test_full_audit import running


def test_history_pages_filters_and_privacy(api):
    c, _ = api
    p = project(c)
    a, ah, _ = agent(c, p, 'A')
    b, bh, _ = agent(c, p, 'B')
    _, outsider, _ = agent(c, project(c, name='Outside'), 'Outside')
    message_ids = []
    for i in range(105):
        r = c.post(f'/api/projects/{p}/messages', headers=ah, json={'content': f'Private {i}', 'recipient_id': b})
        assert r.status_code == 201
        message_ids.append(r.json()['id'])
    route = f'/api/projects/{p}/messages?recipient_id={b}&limit=100'
    newest = c.get(route, headers=ah).json()
    assert len(newest) == 100
    oldest = c.get(route + '&before=' + newest[0]['id'], headers=ah).json()
    assert [r['id'] for r in oldest + newest] == message_ids
    assert c.get(f'/api/projects/{p}/messages?recipient_id={a}', headers=bh).json()
    assert c.get(f'/api/projects/{p}/messages?before={message_ids[0]}').status_code == 404
    assert c.get(f'/api/projects/{p}/messages', headers=outsider).status_code == 403
    assert c.get(f'/api/projects/{p}/messages?recipient_id={a}&channel=general', headers=bh).status_code == 422
    rows = []
    for i in range(105):
        rows.append(c.post(f'/api/projects/{p}/help', json={'question': f'Help {i}'}).json())
    first = c.get(f'/api/projects/{p}/help?state=active&limit=100').json()
    second = c.get(f'/api/projects/{p}/help?state=active&limit=100&before={first[-1]["id"]}').json()
    assert len(first) == 100 and len(second) == 5
    assert len({r['id'] for r in first + second}) == 105
    h = rows[-1]['id']
    assert c.post(f'/api/projects/{p}/help/{h}/claim', headers=bh).status_code == 200
    assert c.post(f'/api/projects/{p}/help/{h}/answer', headers=bh, json={'answer': 'Answered'}).status_code == 200
    assert len(c.get(f'/api/projects/{p}/help?state=history').json()) == 1
    assert c.get(f'/api/projects/{p}/help?before=no-such-id').status_code == 404


def test_native_mcp_sdk_initializes_remote_transport_and_announces_scoped_peer(live_server):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    url, c = live_server
    p = project(c)
    a, ah, _ = agent(c, p, 'Native MCP SDK')
    async def audit():
        async with httpx.AsyncClient(headers=ah) as http:
            async with streamable_http_client(url + '/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name
                    listing = await session.list_tools()
                    assert len(listing.tools) == 23
                    result = await session.call_tool('announce_peer', {'capabilities': ['python'], 'tool_version': 'native-sdk-audit'})
                    assert not result.isError
                    result = await session.call_tool('send_message', {'project_id': p, 'content': 'Native MCP handoff'})
                    assert not result.isError
    asyncio.run(audit())
    snapshot = c.get(f'/api/projects/{p}/snapshot').json()
    peer = next(peer for peer in snapshot['agents'] if peer['id'] == a)
    assert peer['session_info']['connection'] == 'mcp'
    assert peer['session_info']['tool_version'] == 'native-sdk-audit'
    assert snapshot['messages'][0]['sender_id'] == a


def test_active_execution_contract_rejects_changes_but_allows_health_refresh(api):
    c, _ = api
    p = project(c)
    a, _, _ = agent(c, p, 'Contract')
    _, nh, profile, _, row, _ = running(c, p, a)
    from test_previous_observations import SESSION
    assert row['run_contract']['mode'] == 'managed_api'
    for change in [{'mode': 'managed_cli'}, {'driver': 'replacement'}, {'execution_revision': 'changed'}, {'models': [{'id': 'new', 'name': 'New'}]}]:
        r = c.post('/api/nodes/me/inventory', headers=nh, json={'session_id': SESSION, 'profiles': [{**profile, **change}]})
        assert r.status_code == 409, r.text
    assert c.post('/api/nodes/me/inventory', headers=nh, json={'session_id': SESSION, 'profiles': [{**profile, 'availability': 'needs_setup', 'diagnostic': 'Temporary health problem'}]}).status_code == 200


def test_node_refuses_mismatched_run_contract_before_spawning(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    for argv in [['init', '-b', 'main'], ['-c', 'user.name=Audit', '-c', 'user.email=audit@example.test', 'commit', '--allow-empty', '-m', 'Initial']]:
        subprocess.run(['git', *argv], cwd=repo, capture_output=True, check=True)
    service = NodeService('http://127.0.0.1:1', 'fixture', NodeConfig(repo=str(repo), log_dir=str(tmp_path / 'logs'), profiles=[{'id': 'cli', 'name': 'CLI', 'kind': 'custom', 'argv': [sys.executable], 'push': False}]))
    try:
        service.inspect()
        row = {'agent_id': 'a', 'run_id': 'run_a', 'profile_id': 'cli', 'model': '', 'mode': 'managed_cli', 'run_contract': {}}
        service.launch(row)
        assert service.children == {}
        assert service.pending_reports['a']['state'] == 'failed'
        assert 'changed after launch' in service.pending_reports['a']['error']
    finally:
        service.http.close()


def test_fixed_tui_displays_help_and_private_history_under_channel_flood(live_server):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Select, RichLog, TabbedContent
    url, c = live_server
    p = project(c)
    a, ah, _ = agent(c, p, 'Terminal peer')
    for i in range(21):
        assert c.post(f'/api/projects/{p}/help', json={'question': f'Terminal help {i:02}'}).status_code == 200
    assert c.post(f'/api/projects/{p}/messages', headers=ah, json={'content': 'Terminal private decision', 'recipient_id': 'human'}).status_code == 201
    for i in range(100):
        c.post(f'/api/projects/{p}/messages', json={'content': f'General flood {i}'})
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(.5)
            app.query_one('#chat-target', Select).value = a
            await pilot.pause(.3)
            assert len(app.snapshot['help_requests']) == 21
            app.query_one(TabbedContent).active = 'health-tab'
            await pilot.pause(.2)
            health = '\n'.join(line.text for line in app.query_one('#health', RichLog).lines)
            app.query_one(TabbedContent).active = 'chat-tab'
            await pilot.pause(.2)
            chat = '\n'.join(line.text for line in app.query_one('#chat', RichLog).lines)
            assert 'Terminal help 20' in health
            assert 'Terminal help 00' in health
            assert 'Terminal private decision' in chat
        await app.http.aclose()
    asyncio.run(audit())
    assert c.get(f'/api/projects/{p}/messages?recipient_id={a}').json()[0]['content'] == 'Terminal private decision'


def test_fixed_tui_conflict_restores_unsaved_memory(live_server):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import TabbedContent, DataTable, Input, TextArea
    url, c = live_server
    p = project(c)
    note = c.post(f'/api/projects/{p}/memories', json={'title': 'Conflict note', 'content': 'Initial'}).json()
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(.5)
            app.query_one(TabbedContent).active = 'memory-tab'
            app.query_one('#memories', DataTable).focus()
            await pilot.press('enter'); await pilot.pause(.2)
            assert isinstance(app.screen, FormScreen)
            app.screen.query_one('#field-content', TextArea).text = 'Unsaved terminal analysis that should survive'
            assert c.put(f'/api/projects/{p}/memories/{note["id"]}', json={'title': 'Conflict note', 'content': 'Concurrent saved change', 'expected_version': 1}).status_code == 200
            await pilot.click('#save'); await pilot.pause(.3)
            assert isinstance(app.screen, FormScreen)
            assert c.get(f'/api/projects/{p}/snapshot').json()['memories'][0]['content'] == 'Concurrent saved change'
            assert 'Unsaved terminal analysis' in app.screen.query_one('#field-content', TextArea).text
            await pilot.press('escape')
        await app.http.aclose()
    asyncio.run(audit())

```

### tests/test_round5_probes.py

```python
"""Independent round-five checks of newly changed terminal workflows."""
import asyncio

import pytest
from conftest import TOKEN, agent, project


@pytest.mark.parametrize('target', ['general', 'engineering', 'private'])
def test_terminal_refresh_bridges_a_multi_page_gap(live_server, target):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Button, Select
    url, c = live_server
    p = project(c)
    a, ah, _ = agent(c, p, 'Gap peer')
    def post(content):
        body = {'content': content, 'channel': target if target != 'private' else 'general'}
        if target == 'private':
            body['recipient_id'] = 'human'
        assert c.post(f'/api/projects/{p}/messages', headers=ah, json=body).status_code == 201
    for i in range(5):
        post(f'Before gap {i}')
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one('#chat-target', Select).value = a if target == 'private' else '#' + target
            await pilot.pause(.5)
            assert len(app.chat_messages) == 5
            for i in range(205):
                post(f'Inside gap {i}')
            app.refresh_remote()
            await app.workers.wait_for_complete()
            await pilot.pause(.2)
            contents = [r['content'] for r in app.chat_messages]
            print({'target': target, 'server_count': len(c.get(f'/api/projects/{p}/messages?limit=500' + (f'&recipient_id={a}' if target == 'private' else '&channel=' + target)).json()), 'loaded_count': len(contents), 'gap_0_loaded': 'Inside gap 0' in contents, 'gap_104_loaded': 'Inside gap 104' in contents, 'older_disabled': app.query_one('#older-chat', Button).disabled})
            assert 'Inside gap 0' in contents or not app.query_one('#older-chat', Button).disabled, 'Middle history must remain reachable through the UI'
        await app.http.aclose()
    asyncio.run(audit())


def test_terminal_help_refresh_retains_access_to_requests_inside_gap(live_server):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Button
    url, c = live_server
    p = project(c)
    def post(i):
        assert c.post(f'/api/projects/{p}/help', json={'question': f'Gap help {i}'}).status_code == 200
    for i in range(5):
        post(i)
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            assert len(app.help_requests) == 5
            for i in range(5, 210):
                post(i)
            app.refresh_remote()
            await app.workers.wait_for_complete()
            await pilot.pause(.2)
            questions = [r['question'] for r in app.help_requests]
            print({'server_count': len(c.get(f'/api/projects/{p}/help?state=all&limit=500').json()), 'loaded_count': len(questions), 'gap_help_5_loaded': 'Gap help 5' in questions, 'older_disabled': app.query_one('#older-help', Button).disabled})
            assert 'Gap help 5' in questions or not app.query_one('#older-help', Button).disabled, 'Missing requests must remain reachable'
        await app.http.aclose()
    asyncio.run(audit())


def test_terminal_conflict_preserves_draft_and_protects_concurrent_version(live_server):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import DataTable, TabbedContent, TextArea
    url, c = live_server
    p = project(c)
    note = c.post(f'/api/projects/{p}/memories', json={'title': 'Retry conflict', 'content': 'Original'}).json()
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = 'memory-tab'
            app.query_one('#memories', DataTable).focus()
            await pilot.press('enter'); await pilot.pause(.2)
            app.screen.query_one('#field-content', TextArea).text = 'Preserved draft'
            assert c.put(f'/api/projects/{p}/memories/{note["id"]}', json={'title': 'Retry conflict', 'content': 'Concurrent version two', 'expected_version': 1}).status_code == 200
            await pilot.click('#save'); await pilot.pause(.4)
            assert isinstance(app.screen, FormScreen)
            assert app.screen.query_one('#field-content', TextArea).text == 'Preserved draft'
            await pilot.click('#save'); await pilot.pause(.4)
            saved = c.get(f'/api/projects/{p}/snapshot').json()['memories'][0]
            print({'form_still_open': isinstance(app.screen, FormScreen), 'saved_content': saved['content'], 'saved_version': saved['version']})
            assert isinstance(app.screen, FormScreen)
            assert app.screen.query_one('#field-content', TextArea).text == 'Preserved draft'
            assert saved['content'] == 'Concurrent version two' and saved['version'] == 2
            # A plain retry must never overwrite the concurrent edit. A user
            # can cancel, load the latest version, then deliberately reapply.
            await pilot.press('escape')
            app.refresh_remote(); await pilot.pause(.4)
            app.query_one('#memories', DataTable).focus()
            await pilot.press('enter'); await pilot.pause(.2)
            assert app.screen.query_one('#field-content', TextArea).text == 'Concurrent version two'
            app.screen.query_one('#field-content', TextArea).text = 'Reviewed and reapplied preserved draft'
            await pilot.click('#save'); await pilot.pause(.4)
            assert not isinstance(app.screen, FormScreen)
            saved = c.get(f'/api/projects/{p}/snapshot').json()['memories'][0]
            assert saved['version'] == 3
            assert saved['content'] == 'Reviewed and reapplied preserved draft'
        await app.http.aclose()
    asyncio.run(audit())


@pytest.mark.parametrize('kind', ['agent', 'node'])
def test_terminal_invitation_keeps_draft_on_validation_error(live_server, kind):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import Input, TextArea
    url, c = live_server
    p = project(c)
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            if kind == 'agent':
                app.action_add_agent()
            else:
                app.action_add_node()
            await pilot.pause(.2)
            app.screen.query_one('#field-name', Input).value = 'N' * (81 if kind == 'agent' else 101)
            if kind == 'agent':
                app.screen.query_one('#field-capabilities', Input).value = 'python, review, architecture'
                app.screen.query_one('#field-limitations', TextArea).text = 'Carefully entered onboarding limitations'
            await pilot.click('#save'); await pilot.pause(.4)
            rows = c.get(f'/api/projects/{p}/snapshot').json()['agents' if kind == 'agent' else 'nodes']
            print({'invitation_kind': kind, 'form_remains_open': isinstance(app.screen, FormScreen), 'created_count': len(rows)})
            assert len(rows) == 0
            assert isinstance(app.screen, FormScreen), 'A rejected invitation must preserve fields for correction'
            if kind == 'agent':
                assert app.screen.query_one('#field-limitations', TextArea).text == 'Carefully entered onboarding limitations'
        await app.http.aclose()
    asyncio.run(audit())


def test_terminal_creation_is_not_resubmitted_after_successful_post_and_failed_refresh(live_server):
    from agentcommons.tui import CommonsTUI, FormScreen
    from textual.widgets import Input, TextArea
    url, c = live_server
    project(c)
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.action_new_project(); await pilot.pause(.2)
            app.screen.query_one('#field-name', Input).value = 'Creation retry duplicate'
            app.screen.query_one('#field-goal', TextArea).text = 'Saved successfully before refresh failure'
            original = app.call
            failed = False
            async def call(method, path, data=None):
                nonlocal failed
                if method == 'GET' and path == '/api/projects' and not failed:
                    failed = True
                    raise RuntimeError('Simulated projects list refresh 503')
                return await original(method, path, data)
            app.call = call
            await pilot.click('#save'); await pilot.pause(.4)
            reopened = isinstance(app.screen, FormScreen)
            assert len([r for r in c.get('/api/projects').json() if r['name'] == 'Creation retry duplicate']) == 1
            if reopened:
                await pilot.click('#save'); await pilot.pause(.5)
            count = len([r for r in c.get('/api/projects').json() if r['name'] == 'Creation retry duplicate'])
            print({'reopened_after_successful_post': reopened, 'project_count_after_retry': count})
            assert count == 1, 'A refresh failure must not invite replaying a successful creation'
        await app.http.aclose()
    asyncio.run(audit())


def test_terminal_can_send_to_all_named_channels(live_server):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Input, Select, TabbedContent
    url, c = live_server
    p = project(c)
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = 'chat-tab'
            for channel in ['general', 'engineering', 'reviews']:
                app.query_one('#chat-target', Select).value = '#' + channel
                await pilot.pause(.2)
                app.query_one('#chat-input', Input).value = 'Channel test ' + channel
                await app.send(); await pilot.pause(.2)
                row = c.get(f'/api/projects/{p}/messages?channel={channel}').json()
                assert row[-1]['content'] == 'Channel test ' + channel
                assert row[-1]['recipient_id'] is None
        await app.http.aclose()
    asyncio.run(audit())


@pytest.mark.parametrize('size', [(80, 24), (130, 45)])
def test_terminal_history_buttons_work_at_actual_terminal_sizes(live_server, size):
    from agentcommons.tui import CommonsTUI
    from textual.widgets import Button, TabbedContent
    url, c = live_server
    p = project(c)
    for i in range(105):
        assert c.post(f'/api/projects/{p}/help', json={'question': f'Clickable help {i}'}).status_code == 200
    async def audit():
        app = CommonsTUI(url, TOKEN)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(1)
            app.query_one(TabbedContent).active = 'health-tab'
            await pilot.pause(.2)
            assert len(app.help_requests) == 100
            assert not app.query_one('#older-help', Button).disabled
            assert await pilot.click('#older-help')
            await app.workers.wait_for_complete(); await pilot.pause(.3)
            assert len(app.help_requests) == 105
            assert app.query_one('#older-help', Button).disabled
            app.query_one(TabbedContent).active = 'chat-tab'
            await pilot.pause(.2)
            assert len(app.chat_messages) == 100
            assert await pilot.click('#older-chat')
            await app.workers.wait_for_complete(); await pilot.pause(.3)
            assert len(app.chat_messages) == 105
            assert app.query_one('#older-chat', Button).disabled
            print({'terminal_size': size, 'history_buttons_work': True})
        await app.http.aclose()
    asyncio.run(audit())

```

### web/tests/full-audit.spec.ts

```typescript
import { expect, test } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import path from 'node:path'

const root='http://127.0.0.1:8000/api'
const token='browser-test-only-token-not-a-secret'
const headers={Authorization:`Bearer ${token}`}
const python=path.resolve('../.venv/bin/python')
async function login(page:any,value=token) {
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(value)
  await page.getByRole('button',{name:'Enter your workspace'}).click()
  await expect(page.locator('.profile-button')).toBeVisible()
}
async function project(request:any,name:string) {
  const r=await request.post(`${root}/projects`,{headers,data:{name,goal:'Full independent user audit',auto_plan:false}})
  expect(r.status()).toBe(201);return r.json()
}
async function peer(request:any,p:any,name:string,kind='custom') {
  const r=await request.post(`${root}/projects/${p.id}/agents`,{headers,data:{name,kind,capabilities:['python','review'],limitations:['No browser']}})
  expect(r.status()).toBe(201);return r.json()
}

test('scoped token login preserves identity, restricts controls and visits every section',async({page,request})=>{
  const p=await project(request,'Scoped browser audit')
  await project(request,'Other hidden project')
  const a=await peer(request,p,'Scoped UI peer')
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await login(page,a.token)
  expect(await page.evaluate(()=>sessionStorage.getItem('agentverse-token'))).toBe(a.token)
  await expect(page.locator('.profile-button')).toContainText('Agent session')
  await expect(page.getByRole('button',{name:'Other hidden project',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Create project',exact:true})).toHaveCount(0)
  for(const section of ['Task board','Team conversations','Shared memory','Code reviews','Agents & connections','Overview']) {
    await page.getByRole('button',{name:section,exact:true}).click()
    await expect(page.getByRole('heading',{name:section==='Overview'?'Your team, in sync.':section,exact:true})).toBeVisible()
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  }
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  await page.getByRole('button',{name:'Profile Scoped UI peer',exact:true}).click()
  await expect(page.getByLabel('Teammate name')).toHaveAttribute('readonly','')
  await expect(page.getByRole('button',{name:'Save profile'})).toHaveCount(0)
  await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click()
  for(const size of [{width:320,height:740},{width:768,height:1024}]) {
    await page.setViewportSize(size)
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  }
  expect(errors).toEqual([])
})

test('password form reports invalid credentials and logout revokes captured session',async({page})=>{
  await page.goto('/')
  await page.getByLabel('Login method').selectOption('password')
  await page.getByLabel('User ID', {exact:true}).fill('audit-ui-admin')
  await page.getByLabel('Password',{exact:true}).fill('incorrect')
  await page.getByRole('button',{name:'Enter your workspace'}).click()
  await expect(page.getByRole('alert')).toContainText('Invalid')
  await page.getByLabel('Password',{exact:true}).fill('audit-ui-password')
  await page.getByRole('button',{name:'Enter your workspace'}).click()
  await expect(page.locator('.profile-button')).toContainText('Workspace owner')
  const saved=await page.evaluate(()=>sessionStorage.getItem('agentverse-token'))
  expect(saved).toMatch(/^web_/)
  await page.locator('.profile-button').click()
  await expect(page.getByLabel('Workspace access token')).toBeVisible()
  const response=await page.request.get(`${root}/me`,{headers:{Authorization:`Bearer ${saved}`}})
  expect(response.status()).toBe(401)
})

test('copied HTTP Python setup works for all eight advertised tool identities',async({page,request})=>{
  const p=await project(request,'Eight tool recipe audit')
  await login(page)
  await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  for(const kind of ['opencode','cline','omnirush','agentzero','claude','codex','kiro','antigravity']) {
    await page.getByRole('button',{name:'Connect agent',exact:true}).click()
    await page.getByLabel('Teammate name').fill(`Recipe ${kind}`)
    await page.getByLabel('Agent tool').selectOption(kind)
    await page.getByLabel('Strengths').fill('python, review')
    await page.getByLabel('Limitations').fill('No browser')
    await page.getByRole('button',{name:'Create connection'}).click()
    const code=await page.getByRole('dialog').locator('pre').nth(0).innerText()
    const env={...process.env};delete env.AGENTVERSE_AGENT_TOKEN;delete env.AGENTCOMMONS_AGENT_TOKEN
    const run=spawnSync(python,['-u','-c',code],{env,encoding:'utf8',timeout:1500})
    expect(run.error?.message).toContain('ETIMEDOUT')
    expect(run.stderr).not.toContain('Traceback')
    const ps=await page.getByRole('dialog').locator('pre').nth(1).innerText()
    expect(ps).toContain('while ($true)');expect(ps).toContain('/api/agents/heartbeat')
    await page.getByRole('button',{name:'I saved the token'}).click()
  }
  const snap=await request.get(`${root}/projects/${p.id}/snapshot`,{headers}).then(r=>r.json())
  expect(snap.agents).toHaveLength(8)
  for(const agent of snap.agents){expect(agent.online).toBe(true);expect(agent.session_info.capabilities).toEqual(['python','review']);expect(agent.session_info.tool_version).toBe('')}
  expect(snap.messages.filter((m:any)=>m.content.endsWith('is connected over HTTP.'))).toHaveLength(8)
})

test('retest ordinary double quote in agent name breaks copied Python recipe',async({page,request})=>{
  const p=await project(request,'Quoted name audit')
  await login(page)
  await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:'Connect agent',exact:true}).click()
  await page.getByLabel('Teammate name').fill('Atlas "Reviewer"')
  await page.getByLabel('Agent tool').selectOption('codex')
  await page.getByRole('button',{name:'Create connection'}).click()
  const code=await page.getByRole('dialog').locator('pre').nth(0).innerText()
  const run=spawnSync(python,['-c','import ast,sys; ast.parse(sys.stdin.read())'],{input:code,encoding:'utf8'})
  expect(run.status).toBe(0);expect(run.stderr).toBe('')
})

test('memory and profile conflicts preserve edits and show controlled errors',async({page,request})=>{
  const p=await project(request,'Concurrent edits UI')
  const a=await peer(request,p,'Concurrent peer')
  const m=await request.post(`${root}/projects/${p.id}/memories`,{headers,data:{title:'Concurrent note',content:'Original'}}).then(r=>r.json())
  await login(page);await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:'Shared memory',exact:true}).click()
  await page.getByRole('button',{name:'Concurrent note'}).click()
  await page.getByLabel('Shared knowledge').fill('Unsaved local edit')
  expect((await request.put(`${root}/projects/${p.id}/memories/${m.id}`,{headers,data:{title:'Concurrent note',content:'Other session',expected_version:1}})).status()).toBe(200)
  await page.getByRole('button',{name:'Save memory'}).click()
  await expect(page.getByRole('alert')).toContainText(/changed|version|conflict/i)
  await expect(page.getByLabel('Shared knowledge')).toHaveValue('Unsaved local edit')
  await page.getByRole('button',{name:'Cancel',exact:true}).click()
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  await page.getByRole('button',{name:'Profile Concurrent peer',exact:true}).click()
  await page.getByLabel('Role & context').fill('Local role edit')
  expect((await request.patch(`${root}/projects/${p.id}/agents/${a.agent.id}`,{headers,data:{name:'Concurrent peer',description:'Other role',expected_version:1}})).status()).toBe(200)
  await page.getByRole('button',{name:'Save profile'}).click()
  await expect(page.getByRole('alert')).toContainText(/changed|version|conflict/i)
  await expect(page.getByLabel('Role & context')).toHaveValue('Local role edit')
})

test('failed save and failed chat preserve user input and permit retry',async({page,request})=>{
  const p=await project(request,'Transient failure UI')
  await login(page);await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:'New task',exact:true}).click()
  await page.getByLabel('Task title').fill('Retry this task')
  await page.route(`**/api/projects/${p.id}/tasks`,r=>r.fulfill({status:503,contentType:'application/json',body:'{"detail":"Temporarily unavailable"}'}))
  await page.getByRole('button',{name:'Add task',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('Temporarily unavailable')
  await expect(page.getByLabel('Task title')).toHaveValue('Retry this task')
  await page.unroute(`**/api/projects/${p.id}/tasks`)
  await page.getByRole('button',{name:'Add task',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button',{name:'Team conversations',exact:true}).click()
  await page.getByLabel('Message',{exact:true}).fill('Retry chat')
  await page.route(`**/api/projects/${p.id}/messages`,r=>r.fulfill({status:503,contentType:'application/json',body:'{"detail":"Chat unavailable"}'}))
  await page.getByRole('button',{name:'Send message'}).click()
  await expect(page.getByRole('alert')).toContainText('Chat unavailable')
  await expect(page.getByLabel('Message',{exact:true})).toHaveValue('Retry chat')
  await page.unroute(`**/api/projects/${p.id}/messages`)
  await page.getByRole('button',{name:'Send message'}).click()
  await expect(page.locator('.message-body')).toContainText('Retry chat')
})

test('retest switching projects retains an invalid DM recipient',async({page,request})=>{
  const a=await project(request,'DM project A'),b=await project(request,'DM project B')
  const ap=await peer(request,a,'Only A peer');await peer(request,b,'Only B peer')
  await login(page);await page.getByRole('button',{name:a.name,exact:true}).click()
  await page.locator('.team-member').filter({hasText:'Only A peer'}).click()
  await expect(page.getByLabel('Conversation')).toHaveValue(ap.agent.id)
  await page.getByRole('button',{name:b.name,exact:true}).click()
  await expect(page.getByRole('heading',{name:'Team conversations',exact:true})).toBeVisible()
  await page.getByLabel('Message',{exact:true}).fill('Message after project switch')
  await page.getByRole('button',{name:'Send message'}).click()
  await expect(page.getByLabel('Conversation')).toHaveValue('#general')
  await expect(page.locator('.message-body')).toContainText('Message after project switch')
  const snap=await request.get(`${root}/projects/${b.id}/snapshot`,{headers}).then(r=>r.json())
  expect(snap.messages.filter((m:any)=>m.content==='Message after project switch')).toHaveLength(1)
  expect(snap.messages.find((m:any)=>m.content==='Message after project switch').recipient_id).toBeNull()
})

test('review page, task release, revoke confirmation, keyboard shortcut and all mobile sections',async({page,request})=>{
  const p=await project(request,'Remaining actions audit')
  const a=await peer(request,p,'Author UI'),b=await peer(request,p,'Reviewer UI')
  const ah={Authorization:`Bearer ${a.token}`},bh={Authorization:`Bearer ${b.token}`}
  const t=await request.post(`${root}/projects/${p.id}/tasks`,{headers,data:{title:'UI review details'}}).then(r=>r.json())
  const tp=`${root}/projects/${p.id}/tasks/${t.id}`
  expect((await request.post(tp+'/claim',{headers:ah})).status()).toBe(200)
  await login(page);await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:/UI review details/}).click()
  await page.getByRole('button',{name:'Release task',exact:true}).click()
  expect((await request.post(tp+'/claim',{headers:ah})).status()).toBe(200)
  expect((await request.post(tp+'/submit',{headers:ah,data:{summary:'Review summary',branch:'feature',commit_sha:'a'.repeat(40),diff:'+ UI review fixture'}})).status()).toBe(200)
  expect((await request.post(tp+'/review-claim',{headers:bh})).status()).toBe(200)
  await page.getByRole('button',{name:'Code reviews',exact:true}).click()
  await page.getByRole('button',{name:/UI review details/}).click()
  await page.getByRole('button',{name:'Release review',exact:true}).click()
  expect((await request.post(tp+'/review-claim',{headers:bh})).status()).toBe(200)
  expect((await request.post(tp+'/review',{headers:bh,data:{decision:'approve',comment:'UI history evidence'}})).status()).toBe(200)
  await expect(page.locator('.review-history')).toContainText('UI history evidence')
  await page.keyboard.press('Control+k');await expect(page.getByRole('dialog')).toBeVisible();await page.keyboard.press('Escape')
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  page.once('dialog',d=>d.dismiss())
  await page.getByRole('region',{name:'Author UI agent'}).getByRole('button',{name:'Revoke access'}).click()
  expect((await request.get(root+'/me',{headers:ah})).status()).toBe(200)
  page.once('dialog',d=>d.accept())
  await page.getByRole('region',{name:'Author UI agent'}).getByRole('button',{name:'Revoke access'}).click()
  await expect(page.getByRole('region',{name:'Author UI agent'})).toContainText('Access revoked')
  expect((await request.get(root+'/me',{headers:ah})).status()).toBe(401)
  await page.screenshot({path:'../../audit5-agents-desktop.png',fullPage:true})
  await page.setViewportSize({width:390,height:844})
  for(const section of ['Overview','Task board','Team conversations','Shared memory','Code reviews','Agents & connections']) {
    await page.getByRole('button',{name:'Open navigation'}).click()
    await page.getByRole('button',{name:section,exact:true}).click()
    await expect(page.getByRole('heading',{name:section==='Overview'?'Your team, in sync.':section,exact:true})).toBeVisible()
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  }
  await expect.poll(()=>page.locator('.sidebar').evaluate(el=>el.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await page.screenshot({path:'../../audit5-agents-mobile.png',fullPage:true,animations:'disabled'})
})

test('retest saved project remains in dialog and retry duplicates it after list refresh fails',async({page,request})=>{
  await project(request,'Existing project for failure')
  await login(page)
  await page.getByRole('button',{name:'Create project',exact:true}).click()
  await page.getByLabel('Project name',{exact:true}).fill('Duplicate-on-refresh audit')
  await page.getByLabel('The goal',{exact:true}).fill('Preserve successful project creation')
  await page.route('**/api/projects',route=>route.request().method()==='GET'?route.fulfill({status:503,contentType:'application/json',body:'{"detail":"List refresh failed"}'}):route.continue())
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('button',{name:'Create project',exact:true}).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.error-banner[role="status"]')).toContainText('Project saved')
  const first=await request.get(`${root}/projects`,{headers}).then(r=>r.json())
  expect(first.filter((p:any)=>p.name==='Duplicate-on-refresh audit')).toHaveLength(1)
  await page.unroute('**/api/projects')
  await page.getByRole('button',{name:'Retry refresh',exact:true}).click()
  await expect(page.locator('.error-banner[role="status"]')).toHaveCount(0)
  const second=await request.get(`${root}/projects`,{headers}).then(r=>r.json())
  expect(second.filter((p:any)=>p.name==='Duplicate-on-refresh audit')).toHaveLength(1)
})

test('retest older open help and older channel messages disappear without pagination',async({page,request})=>{
  const p=await project(request,'History pagination audit')
  for(let i=0;i<9;i++)expect((await request.post(`${root}/projects/${p.id}/help`,{headers,data:{question:`Historical help ${i}`}})).status()).toBe(200)
  expect((await request.post(`${root}/projects/${p.id}/messages`,{headers,data:{content:'Earlier engineering decision',channel:'engineering'}})).status()).toBe(201)
  for(let i=0;i<100;i++)await request.post(`${root}/projects/${p.id}/messages`,{headers,data:{content:`General flood ${i}`}})
  await login(page);await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  await expect(page.locator('.coordination-item').getByText('Historical help 8',{exact:true})).toBeVisible()
  await expect(page.locator('.coordination-item').getByText('Historical help 0',{exact:true})).toBeVisible()
  const snap=await request.get(`${root}/projects/${p.id}/snapshot`,{headers}).then(r=>r.json())
  expect(snap.help_requests).toHaveLength(9)
  expect(snap.help_requests.find((h:any)=>h.question==='Historical help 0').state).toBe('open')
  await page.getByRole('button',{name:'Team conversations',exact:true}).click()
  await page.getByLabel('Conversation').selectOption('#engineering')
  await expect(page.locator('.message-body')).toContainText('Earlier engineering decision')
  const history=await request.get(`${root}/projects/${p.id}/messages?limit=500`,{headers}).then(r=>r.json())
  expect(history.some((m:any)=>m.content==='Earlier engineering decision')).toBe(true)
})

test('task dependency/capability fields, search, clipboard failure and live fallback',async({page,request})=>{
  const p=await project(request,'Last UI coverage')
  const dep=await request.post(`${root}/projects/${p.id}/tasks`,{headers,data:{title:'Prerequisite UI task'}}).then(r=>r.json())
  await login(page);await page.getByRole('button',{name:p.name,exact:true}).click()
  await page.getByRole('button',{name:'New task',exact:true}).click()
  await page.getByLabel('Task title').fill('Dependent UI task')
  await page.getByLabel('Required capabilities').fill('python, testing')
  await page.locator('select[name=priority]').selectOption('high')
  await page.getByLabel('Prerequisite UI task',{exact:true}).check()
  await page.getByRole('button',{name:'Add task',exact:true}).click()
  await page.getByRole('button',{name:'Task board',exact:true}).click()
  await page.getByLabel('Search tasks').fill('Dependent')
  await expect(page.locator('.task-card')).toHaveCount(1)
  await expect(page.locator('.task-card')).toContainText('waiting on dependencies')
  const snap=await request.get(`${root}/projects/${p.id}/snapshot`,{headers}).then(r=>r.json())
  const task=snap.tasks.find((t:any)=>t.title==='Dependent UI task')
  expect(task.dependencies).toEqual([dep.id]);expect(task.required_capabilities).toEqual(['python','testing']);expect(task.priority).toBe('high')
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('Denied')}}}))
  await page.getByRole('button',{name:'Copy HTTP API endpoint'}).click()
  await expect(page.getByRole('alert')).toContainText('clipboard access is unavailable')
  await page.routeWebSocket('**/api/live?*',ws=>ws.close())
  await page.reload();await page.getByRole('button',{name:'Team conversations',exact:true}).click()
  await request.post(`${root}/projects/${p.id}/messages`,{headers,data:{content:'Message while websocket unavailable'}})
  await expect(page.locator('.message-body')).toContainText('Message while websocket unavailable',{timeout:20000})
})

```

### web/tests/round4-extensions.spec.ts

```typescript
import { test, expect } from '@playwright/test'

const root = 'http://127.0.0.1:8000/api'
const headers = { Authorization: 'Bearer browser-test-only-token-not-a-secret' }
async function project(request:any, name:string) {
  const response = await request.post(`${root}/projects`, { headers, data: {name, goal:'Fresh round five audit', auto_plan:false} })
  expect(response.status()).toBe(201); return response.json()
}
async function login(page:any, name:string) {
  await page.goto('/'); await page.getByLabel('Workspace access token').fill('browser-test-only-token-not-a-secret')
  await page.getByRole('button',{name:'Enter your workspace'}).click()
  await page.getByRole('button',{name,exact:true}).click()
}

test('history controls load all help, resolved problems, channel pages and private pages',async({page,request})=>{
  test.setTimeout(60000)
  const p=await project(request,'Round five paginated history')
  const a=await request.post(`${root}/projects/${p.id}/agents`,{headers,data:{name:'History peer',kind:'custom'}}).then(r=>r.json())
  for(let i=0;i<105;i++) {
    expect((await request.post(`${root}/projects/${p.id}/help`,{headers,data:{question:`Paged help ${i}`}})).status()).toBe(200)
    expect((await request.post(`${root}/projects/${p.id}/messages`,{headers,data:{content:`Paged channel ${i}`}})).status()).toBe(201)
    expect((await request.post(`${root}/projects/${p.id}/messages`,{headers,data:{content:`Paged private ${i}`,recipient_id:a.agent.id}})).status()).toBe(201)
  }
  const issue=await request.post(`${root}/projects/${p.id}/agents/${a.agent.id}/issues`,{headers,data:{title:'Resolved history evidence'}}).then(r=>r.json())
  expect((await request.post(`${root}/projects/${p.id}/issues/${issue.id}/resolve`,{headers})).status()).toBe(200)
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await login(page,p.name)
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  await expect(page.locator('.coordination-item').getByText('Paged help 104',{exact:true})).toBeVisible()
  await expect(page.locator('.coordination-item').getByText('Paged help 0',{exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Load more help requests',exact:true}).click()
  await expect(page.locator('.coordination-item').getByText('Paged help 0',{exact:true})).toBeVisible()
  await page.getByLabel('Problem history').selectOption('history')
  await expect(page.locator('.coordination-item').getByText('Resolved history evidence',{exact:true})).toBeVisible()
  await page.getByLabel('Problem history').selectOption('active')
  await expect(page.locator('.coordination-item').getByText('Resolved history evidence',{exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Team conversations',exact:true}).click()
  await expect(page.locator('.message-body').getByText('Paged channel 104',{exact:true})).toBeVisible()
  await expect(page.locator('.message-body').getByText('Paged private 104',{exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Load older messages',exact:true}).click()
  await expect(page.locator('.message-body').getByText('Paged channel 5',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Load older messages',exact:true}).click()
  await expect(page.locator('.message-body').getByText('Paged channel 0',{exact:true})).toBeVisible()
  await page.getByLabel('Conversation').selectOption(a.agent.id)
  await expect(page.locator('.message-body').getByText('Paged private 104',{exact:true})).toBeVisible()
  await expect(page.locator('.message-body').getByText('Paged channel 104',{exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Load older messages',exact:true}).click()
  await expect(page.locator('.message-body').getByText('Paged private 0',{exact:true})).toBeVisible()
  expect(errors).toEqual([])
})

test('live refresh retains access to older messages when conversation crosses 100 messages',async({page,request})=>{
  const p=await project(request,'Round five live history overflow')
  await page.routeWebSocket('**/api/live*',ws=>ws.close())
  await login(page,p.name)
  await page.getByRole('button',{name:'Team conversations',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Start the conversation',exact:true})).toBeVisible()
  await page.route(`**/api/projects/${p.id}/messages?*`,async route=>{
    const url=new URL(route.request().url())
    if(!url.searchParams.has('before') && route.request().method()==='GET') {
      const result=await request.get(route.request().url(),{headers})
      await route.fulfill({response:result});return
    }
    await route.continue()
  })
  for(let i=0;i<105;i++)await request.post(`${root}/projects/${p.id}/messages`,{headers,data:{content:`Live overflow ${i}`}})
  await expect(page.locator('.message-body').getByText('Live overflow 104',{exact:true})).toBeVisible({timeout:20000})
  await expect(page.locator('.message-body').getByText('Live overflow 0',{exact:true})).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Load older messages',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Load older messages',exact:true}).click()
  await expect(page.locator('.message-body').getByText('Live overflow 0',{exact:true})).toBeVisible()
  const all=await request.get(`${root}/projects/${p.id}/messages?channel=general&limit=500`,{headers}).then(r=>r.json())
  expect(all).toHaveLength(105)
  await page.screenshot({path:'/workspace/scratch/ecae45260a2e/audit5-live-history-overflow.png',fullPage:true})
})

test('required runtime settings without defaults can be saved and launched through the form',async({page,request})=>{
  const p=await project(request,'Round five required settings')
  const a=await request.post(`${root}/projects/${p.id}/agents`,{headers,data:{name:'Explicit runtime',kind:'custom'}}).then(r=>r.json())
  const n=await request.post(`${root}/projects/${p.id}/nodes`,{headers,data:{name:'Explicit node'}}).then(r=>r.json())
  const nodeHeaders={Authorization:`Bearer ${n.token}`}
  expect((await request.post(`${root}/nodes/me/register`,{headers:nodeHeaders,data:{session_id:'e'.repeat(32),profiles:[{id:'explicit',name:'Explicit CLI',kind:'custom',required_settings:['effort'],settings_schema:[{key:'effort',label:'Required effort',type:'choice',options:['low','high']}]}]}})).status()).toBe(200)
  await login(page,p.name)
  await page.getByRole('button',{name:'Agents & connections',exact:true}).click()
  await page.getByRole('button',{name:'Configure Explicit runtime',exact:true}).click()
  await page.getByRole('button',{name:'Save runtime',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('Required effort')
  await page.getByLabel('Required effort').selectOption('high')
  await page.getByRole('button',{name:'Save runtime',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button',{name:'Launch Explicit runtime',exact:true}).click()
  await expect(page.locator('.agent-card').filter({hasText:'Explicit runtime'})).toContainText('queued')
  const row=await request.get(`${root}/projects/${p.id}/snapshot`,{headers}).then(r=>r.json())
  expect(row.agents.find((peer:any)=>peer.id===a.agent.id).runtime.settings.effort).toBe('high')
})

```

### web/tests/round5-recovery.spec.ts

```typescript
import { expect, test } from '@playwright/test'

const root = 'http://127.0.0.1:8000/api'
const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }

for (const target of ['engineering', 'private', 'send-during-gap']) {
  test(`independent gap recovery: ${target}`, async ({ page, request }) => {
    test.setTimeout(90000)
    const p = await request.post(`${root}/projects`, { headers, data: { name: `Independent recovery ${target}`, goal: 'No lost coordination messages', auto_plan: false } }).then(r => r.json())
    const a = await request.post(`${root}/projects/${p.id}/agents`, { headers, data: { name: 'Recovery peer', kind: 'custom' } }).then(r => r.json())
    const body = (content: string) => ({ content, channel: target === 'engineering' ? 'engineering' : 'general', recipient_id: target === 'private' ? a.agent.id : null })
    for (let i = 0; i < 5; i++) expect((await request.post(`${root}/projects/${p.id}/messages`, { headers, data: body(`Seed ${i}`) })).status()).toBe(201)
    await page.routeWebSocket('**/api/live*', ws => ws.close())
    await page.goto('/')
    await page.getByLabel('Workspace access token').fill(token)
    await page.getByRole('button', { name: 'Enter your workspace' }).click()
    await page.getByRole('button', { name: p.name, exact: true }).click()
    await page.getByRole('button', { name: 'Team conversations', exact: true }).click()
    await page.getByLabel('Conversation').selectOption(target === 'private' ? a.agent.id : target === 'engineering' ? '#engineering' : '#general')
    await expect(page.locator('.message-body').getByText('Seed 0', { exact: true })).toBeVisible()
    let blocked = true
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    await page.route(`**/api/projects/${p.id}/messages?*`, async route => { if (blocked) await gate; await route.continue() })
    try {
      for (let i = 0; i < 205; i++) expect((await request.post(`${root}/projects/${p.id}/messages`, { headers, data: body(`Gap ${i}`) })).status()).toBe(201)
      if (target === 'send-during-gap') {
        await page.getByLabel('Message', { exact: true }).fill('My message after the gap')
        await page.getByRole('button', { name: 'Send message', exact: true }).click()
        await expect(page.getByLabel('Message', { exact: true })).toHaveValue('')
      }
    } finally { blocked = false; release() }
    await expect(page.locator('.message')).toHaveCount(target === 'send-during-gap' ? 211 : 210, { timeout: 30000 })
    for (const i of [0, 4, 104, 105, 204]) await expect(page.locator('.message-body').getByText(`Gap ${i}`, { exact: true })).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Load older messages', exact: true })).toHaveCount(0)
    if (target === 'private') {
      await page.getByLabel('Conversation').selectOption('#general')
      await expect(page.locator('.message-body').getByText('Gap 204', { exact: true })).toHaveCount(0)
    }
  })
}

```

### web/tests/round5-responsive.spec.ts

```typescript
import { expect, test } from '@playwright/test'

const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }
const root = 'http://127.0.0.1:8000/api'

test('seven themes persist, motion respects accessibility, and dialogs keep keyboard focus', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('.brand')).toHaveText('AgentVerse')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'off')
  await page.getByRole('button', { name: 'Appearance', exact: true }).click()
  const dialog = page.getByRole('dialog')
  for (const [name, id] of [['Aurora', 'aurora'], ['Cosmic', 'cosmic'], ['Ember', 'ember'], ['Daylight', 'daylight'], ['Atoms', 'atoms'], ['Deep Sea', 'deep-sea'], ['Deep Galaxy', 'deep-galaxy']]) {
    const button = dialog.getByRole('button', { name: new RegExp(`^${name}`) })
    await button.click()
    await expect(button).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('html')).toHaveAttribute('data-theme', id)
    expect(await page.locator('.ambient-glow').first().evaluate(el => getComputedStyle(el).animationName)).toBe('none')
  }
  await dialog.getByRole('button', { name: 'Off', exact: true }).click()
  await dialog.getByRole('button', { name: 'Done', exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close dialog' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Appearance', exact: true })).toBeFocused()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'deep-galaxy')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'off')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Appearance', exact: true }).click()
  await expect(dialog.getByRole('button', { name: /^Daylight/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

test('one-time teammate token survives a failed post-save refresh', async ({ page, request }) => {
  await request.post(`${root}/projects`, { headers, data: { name: 'Refresh failure lab', goal: 'Keep invitation tokens visible.', auto_plan: false } })
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: 'Connect agent', exact: true }).click()
  await page.getByLabel('Teammate name').fill('Refresh-proof peer')
  await page.getByLabel('Agent tool').selectOption('custom')
  await page.getByLabel('Custom tool ID').fill('future-wrapper')
  await page.route('**/api/projects/*/snapshot', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Fixture refresh failure"}' }))
  await page.getByRole('button', { name: 'Create connection' }).click()
  await expect(page.getByRole('heading', { name: 'Refresh-proof peer is ready to connect.' })).toBeVisible()
  await expect(page.locator('.copy-box code')).toContainText('ac_')
})

test('blocked browser storage does not break login or themes', async ({ page }) => {
  await page.addInitScript(() => { Storage.prototype.setItem = () => { throw new Error('Storage disabled') }; Storage.prototype.getItem = () => { throw new Error('Storage disabled') } })
  await page.goto('/')
  await page.getByRole('button', { name: 'Appearance', exact: true }).click()
  await page.getByRole('button', { name: /^Daylight/ }).click()
  await page.getByRole('button', { name: 'Done', exact: true }).click()
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await expect(page.getByRole('button', { name: 'Agents & connections', exact: true })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'daylight')
})

test('settled layout: future tools, typed settings, external modes, profiles, issues, and capability help', async ({ page, request }) => {
  const p = await request.post(`${root}/projects`, { headers, data: { name: 'Future tools lab', goal: 'Coordinate arbitrary tools.', auto_plan: false } }).then(r => r.json())
  const peer = await request.post(`${root}/projects/${p.id}/agents`, { headers, data: { name: 'Future peer', kind: 'future-tool' } }).then(r => r.json())
  const node = await request.post(`${root}/projects/${p.id}/nodes`, { headers, data: { name: 'Mixed tools VPS' } }).then(r => r.json())
  const nh = { Authorization: `Bearer ${node.token}` }
  await request.post(`${root}/nodes/me/register`, { headers: nh, data: { session_id: 'd'.repeat(32), profiles: [
    { id: 'future-cli', name: 'Future tool CLI', kind: 'future-tool', settings_schema: [
      { key: 'effort', label: 'Reasoning effort', type: 'choice', default: 'low', options: ['low', 'high'] },
      { key: 'budget', label: 'Iteration budget', type: 'number', default: 3, minimum: 1, maximum: 5 },
      { key: 'respond_to_help', label: 'Respond to teammates', type: 'boolean', default: true },
    ] },
    { id: 'future-editor', name: 'Future editor', kind: 'future-tool', mode: 'connected' },
    { id: 'missing', name: 'Missing optional tool', kind: 'other', availability: 'unavailable', diagnostic: 'Executable not installed; other profiles remain available.' },
  ] } })
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: 'Agents & connections', exact: true }).click()
  await page.getByText('Tool health & connection modes', { exact: true }).click()
  await expect(page.getByText('Executable not installed; other profiles remain available.')).toBeVisible()
  await page.getByRole('button', { name: 'Configure Future peer', exact: true }).click()
  await page.getByLabel('Reasoning effort').selectOption('high')
  await page.getByLabel('Iteration budget').fill('5')
  await page.getByLabel('Respond to teammates').uncheck()
  await page.getByRole('button', { name: 'Save runtime' }).click()
  let snap = await request.get(`${root}/projects/${p.id}/snapshot`, { headers }).then(r => r.json())
  expect(snap.agents[0].runtime.settings).toEqual({ effort: 'high', budget: 5, respond_to_help: false })
  await page.getByRole('button', { name: 'Profile Future peer', exact: true }).click()
  await page.getByLabel('Strengths').fill('frontend, review')
  await page.getByLabel('Limitations').fill('No shell in editor mode')
  await page.getByRole('button', { name: 'Save profile' }).click()
  const card = page.getByRole('region', { name: 'Future peer agent' })
  await expect(card).toContainText('No shell in editor mode')
  await page.getByRole('button', { name: 'Report problem for Future peer' }).click()
  await page.getByLabel('Problem', { exact: true }).fill('Reauthentication needed')
  await page.getByLabel('Details', { exact: true }).fill('Update login on the remote machine.')
  await page.getByRole('dialog').getByRole('button', { name: 'Report problem', exact: true }).click()
  await expect(page.locator('.coordination-item').getByText('Reauthentication needed')).toBeVisible()
  await page.getByRole('button', { name: 'Mark resolved' }).click()
  await expect(page.getByText('Reauthentication needed', { exact: true })).not.toBeVisible()
  await page.getByRole('button', { name: 'Ask for help' }).click()
  await page.getByLabel('Capability needed').fill('review')
  await page.getByLabel('Question', { exact: true }).fill('Please review the interface contract.')
  await page.getByRole('button', { name: 'Send help request' }).click()
  await expect(page.getByText('Please review the interface contract.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Configure Future peer', exact: true }).click()
  await page.getByLabel('Agent runtime', { exact: true }).selectOption('future-editor')
  await expect(page.getByText('Start this tool in its own client and connect through the AgentVerse HTTP API.', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Save runtime' }).click()
  await expect(card.getByRole('button', { name: 'Launch Future peer' })).toHaveCount(0)
  await card.getByRole('button', { name: 'Connect', exact: true }).click()
  await page.getByRole('button', { name: 'Generate replacement token' }).click()
  await expect(page.locator('.copy-box code')).toContainText('ac_')
  await expect(page.getByText('Introduce the session to its teammates')).toBeVisible()
  await page.getByRole('button', { name: 'I saved the token' }).click()
  snap = await request.get(`${root}/projects/${p.id}/snapshot`, { headers }).then(r => r.json())
  expect(snap.help_requests[0].recipient_id).toBe(peer.agent.id)
  await page.getByRole('button', { name: 'Appearance', exact: true }).click()
  await page.getByRole('button', { name: /^Daylight/ }).click()
  await page.getByRole('button', { name: 'Off', exact: true }).click()
  await page.getByRole('button', { name: 'Done', exact: true }).click()
  if (process.env.UPDATE_SCREENSHOTS) await page.screenshot({ path: '../docs/assets/daylight.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  console.log('resize immediate', await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth})))
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  console.log('resize settled', await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth})))
})

```

### web/playwright.audit.config.ts

```typescript
import original from './playwright.config'

export default {
  ...original, timeout: 45000,
  use: { ...original.use, reducedMotion: "reduce", launchOptions: { executablePath: '/tmp/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } },
  webServer: [
    { ...original.webServer![0], env: { ...original.webServer![0].env, AGENTVERSE_DB: `/tmp/agentverse-fresh-audit-${Date.now()}-${Math.random().toString(36).slice(2)}.db`, AGENTVERSE_ADMIN_USERNAME: 'audit-ui-admin', AGENTVERSE_ADMIN_PASSWORD: 'audit-ui-password' } },
    { ...original.webServer![1], command: 'npm run dev -- --host 127.0.0.1 --port 5173' },
  ],
}

```

### web/playwright.production-audit.config.ts

```typescript
import audit from './playwright.audit.config'

export default {
  ...audit,
  use: { ...audit.use, baseURL: 'http://127.0.0.1:8000' },
  webServer: [{
    ...audit.webServer[0],
    env: { ...audit.webServer[0].env, AGENTVERSE_WEB_DIR: '/workspace/scratch/ecae45260a2e/agentverse-audit5-latest/web/dist' },
  }],
}

```
