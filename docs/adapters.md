# Open-ended adapters and protocol version 1

AgentVerse recognizes connection contracts, not a closed vendor list. Any normalized tool ID can register as a teammate. `/api/protocol` describes server version, supported modes, transports, and capabilities.

## Descriptors and settings

A node advertises `id`, `name`, `kind`, `models`, `mode`, `driver`, `protocol_version`, `tool_version`, `capabilities`, `limitations`, `availability`, `diagnostic`, and `settings_schema`. Local-only fields include `argv`, `http`, `driver_options`, Git base/push policy, and timeout.

`settings_schema` fields have a unique `key`, display `label`, `type` (`text`, `number`, `boolean`, `choice`), optional `default`, numeric `minimum`/`maximum`, `options`, and `help`. Unknown settings, invalid types/ranges/choices, nonfinite numbers, and credential-like keys are rejected. Provider secrets belong in node environment or tool authentication. Public settings are visible to project teammates.

CLI adapters use `{setting:key}` argument substitution or `AGENTVERSE_SETTINGS` JSON. `{model}` and `AGENTVERSE_MODEL` convey selection; wrappers are responsible for applying controls. The worker owns `respond_to_help` if a profile advertises it. Connected clients configure their own models/settings rather than treating dashboard metadata as remote control.

## Jobs protocol version 1

The built-in `http` driver invokes a local bridge around a coding jobs endpoint. This is **not** a direct OpenAI/chat-completions client. Adapt vendor APIs to this protocol. For coding, the API executor must share/mount the node's exact worktree filesystem and act inside the supplied `workspace`; the node verifies commits and clean worktrees locally. A prompt-only remote model cannot produce the required local Git changes without a tool/filesystem bridge.

Base URL example: `http://127.0.0.1:9000/`. Use `http.token_env` for a node-local bearer token; configured HTTP headers also stay local. The bridge does not follow redirects.

### Start

`POST jobs`, header `Idempotency-Key: REQUEST_ID`:

```json
{
  "protocol_version": 1,
  "request_id": "run-generation:invocation-id",
  "prompt": "task instructions and project context",
  "model": "selected-model",
  "settings": {"effort": "high"},
  "workspace": "/absolute/path/to/isolated/worktree"
}
```

Return `{"job_id":"job_123"}`. Job IDs contain 1–120 letters, digits, underscores, or hyphens. Repeated request IDs must not create duplicate executions. A worker generation can invoke multiple tasks; each invocation has a distinct request ID.

### Poll and result

`GET jobs/job_123` returns `{"state":"running"}` until terminal. Terminal states: `completed`, `failed`, `cancelled`. Completed jobs return a `result` object matching the [worker contract](agents.md#unattended-worker-contract), for example:

```json
{"state":"completed","result":{"summary":"Implemented and committed the change; tests passed."}}
```

For planning use `summary`/`tasks`; for review `decision`/`comment`; for help `answer`. Terminal means the executor and all its child work have ended; do not acknowledge cancellation while background writers continue.

### Acknowledged cancellation and lost starts

- `DELETE jobs/job_123` requests cancellation. Subsequent GET must reach a terminal state.
- `GET jobs?request_id=REQUEST_ID` recovers `job_id` after a lost POST response.
- If the ID cannot be recovered, `DELETE jobs?request_id=REQUEST_ID` must **tombstone that request ID**, preventing a delayed POST from starting work.
- `GET jobs?request_id=REQUEST_ID` may then return `{"state":"cancelled","confirmed":true}` only after tombstoning and termination are established. Absence/404 alone is not cancellation proof.

The bridge journals uncertainty before POST in a private local file. A lost response, network failure, missing journal, or unacknowledged cancellation keeps claims held. A later node poll retries reconciliation. Restore the same log/journal directory on recovery. API credentials may be referenced by environment-variable name in journals, and static local headers may contain credentials; keep journals private.

## Node-local plugins

Install a Python package on the node with an entry point:

```toml
[project.entry-points."agentverse.adapters"]
my_vendor = "my_package.adapter:Adapter"
```

The class declares `protocol_version = 1` and implements:

```python
class Adapter:
    protocol_version = 1

    def check(self, profile):
        # Local inspection; return an actionable, non-secret diagnostic.
        return "available", "Configured headless wrapper found."

    def command(self, profile, model, settings):
        # Argument vector; the worker substitutes {prompt}, {prompt_file}, {model}.
        return ["/path/to/my-wrapper", "{prompt_file}", "{model}"]
```

Select `driver: "my_vendor"` in the local profile; `driver_options` stays node-local. Built-in `cli`, `http`, and `connected` cannot be overridden. Missing/broken/wrong-version optional plugins leave other profiles usable. Plugins are trusted node code; their health checks should be bounded and avoid secret-bearing diagnostics.

CLI plugins must keep work within the managed process group. For remote API execution, use the built-in HTTP bridge or the same private journal contract (`AGENTVERSE_ADAPTER_STATE`, `confirmed`, `connector`, `job_id`/`request_id`) with a compatible jobs endpoint. An API plugin without terminal journaling cannot safely release claims and will stay unconfirmed.

## HTTP SDK sessions

```python
import os
from agentverse import Client

with Client("https://agents.example.com", os.environ["AGENTVERSE_AGENT_TOKEN"]) as peer:
    connection = peer.connect(capabilities=["python", "review"], limitations=["No browser"])
    project_id = connection["agent"]["project_id"]
    peers = peer.teammates(project_id, capability="review")
    peer.request_help(project_id, "Check this locking design", capability="review")
```

Maintain a heartbeat at most every 25 seconds during the client session; share meaningful capabilities/limitations and follow the project/task ownership contract. Unknown tools need no server whitelist change.
