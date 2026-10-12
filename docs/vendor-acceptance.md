# Vendor and version acceptance

Last reviewed: 2026-10-11. AgentVerse workspace: 0.2.0, protocol 1.

**No live native vendor/version combination has full acceptance in this test environment.** A successful HTTP announcement, green presence badge, detected executable, or advertised model does not establish native authentication, MCP attachment, or completed work. The dashboard links this matrix beside connection setup.

U = unverified with a real native client/account. V = verified with the indicated local test fixture. A cell must remain U until its evidence is recorded for the exact version, operating system, connection mode and model.

| Native tool | Version accepted in this round | Native auth | Native MCP attachment | Native models/settings | Planning | Committed implementation | Independent review | Confirmed stop |
|---|---|---|---|---|---|---|---|---|
| OpenCode | None | U | U | U | U | U | U | U |
| Omnirush | None | U | U | U | U | U | U | U |
| Cline | None | U | U | U | U | U | U | U |
| Claude | None | U | U | U | U | U | U | U |
| Codex | None | U | U | U | U | U | U | U |
| Kiro | None | U | U | U | U | U | U | U |
| Antigravity | None | U | U | U | U | U | U | U |
| Agent Zero | None | U | U | U | U | U | U | U |
| Custom tool / plugin | None | U | U | U | U | U | U | U |

The Omnirush 2.2.1 interface example in [agents.md](agents.md) describes earlier interface inspection; it is not a live native acceptance result.

| Local integration fixture | Authentication/attachment | Models/settings | Planning | Commit | Independent review | Stop |
|---|---|---|---|---|---|---|
| Python HTTP SDK, eight tool identities | V: AgentVerse bearer authentication and announcement; native auth/MCP U | Client configured; native U | Native U | Native U | Native U | Presence only; native U |
| Official Python MCP client | V: authenticated HTTP transport, initialize, tool discovery and announce; native client U | Protocol metadata V; native U | Native U | Native U | Native U | Native U |
| Deterministic managed CLI, temporary Git repositories | V: runtime bearer identity | V: advertised validation and invocation | V | V | V: second identity | V: process tree termination |
| Local jobs-protocol API bridge | V: bridge protocol fixture | V: validated advertised settings | Native U | Native U | Native U | V: acknowledgement, lost response, retry, uncertainty retained |

These fixture results validate AgentVerse behavior and are not substitutes for vendor acceptance. See [the testing report](testing-optional-fixes.md) for this round's commands and counts.

## Accepting an exact native combination

Create a separate evidence record with tool/version, OS, client edition, connection mode, model ID, adapter revision, date and AgentVerse commit. Never store credentials in the record.

1. Authenticate in the native tool and make a real model request. Save sanitized output.
2. Attach `/mcp/` with a unique agent identity. Confirm tool discovery and `announce_peer` from inside the native session; HTTP SDK presence alone is insufficient.
3. Check every advertised model and setting against the installed tool. Confirm values reach the invocation, including explicit false and omitted defaults.
4. Complete a planning task that creates dependent implementation work.
5. Complete implementation in a temporary Git clone; record its branch and commit and successful push.
6. Have a different agent identity review that exact commit. Verify approval/changes requested and integration behavior.
7. Stop during active work. Confirm the native process tree or remote API job has ended before claims are released. Simulate a lost cancellation response and node restart with the same journal.

For a connected client, mark dashboard Launch/Stop as not applicable and record the client's own confirmed stop. Publish evidence per version; failures and unverified cells must remain visible.

Conversation workflow acceptance in 0.4.1 covers continuous SDK callbacks, MCP turn ownership, configured CLI invocation, jobs-protocol API replies, frozen node/worker chat, and browser chat → planning → code → independent review. Deterministic adapters exercise the complete application boundaries; these tests do not establish live vendor/provider authentication or unattended support for a particular editor version.
