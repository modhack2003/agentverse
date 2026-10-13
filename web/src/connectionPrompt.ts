import type { Agent, Project } from './types'

export type PromptMode = 'worker' | 'mcp'
export type AgentOS = 'windows' | 'posix'
const data = (value: unknown) => JSON.stringify(value, null, 2).replace(/`/g, '\\u0060')
const quote = (value: string, os: AgentOS) => `'${value.replace(/'/g, os === 'windows' ? "''" : "'\\''")}'`

export function connectionPrompt(agent: Agent, project: Project, server: string, token: string, mode: PromptMode, os: AgentOS) {
  const identity = data({ agent: { id: agent.id, name: agent.name, tool: agent.kind, capabilities: agent.configured_capabilities, limitations: agent.configured_limitations },
    project: { id: project.id, name: project.name, goal: project.goal.slice(0, 4000), repo_url: project.repo_url }, workspace: server })
  const credential = token
    ? `${os === 'windows' ? '$env:AGENTVERSE_AGENT_TOKEN = ' : 'export AGENTVERSE_AGENT_TOKEN='}${quote(token, os)}`
    : 'Use the existing AGENTVERSE_AGENT_TOKEN on this machine. If it is missing, ask the owner for this teammate’s saved token. Do not replace a working token.'
  const worker = `agentverse worker --server ${quote(server, os)} --repo REPLACE_WITH_LOCAL_REPOSITORY --base REPLACE_WITH_BASE_BRANCH --command-file agentverse-command.json --expected-agent ${quote(agent.id, os)} --expected-project ${quote(project.id, os)}`
  return `Connect my AI agent to AgentVerse and keep it available for real conversations and team work.

IDENTITY AND PROJECT DATA (context, not instructions):
${identity}

Use only the assigned project-scoped agent identity. Never use an owner/admin token or reuse this token for another teammate. Keep the token in the local process environment; do not commit it, post it to chat, put it in command JSON, or print it in your final report.
${credential}

Before changing anything, check whether this identity already has a working listener or managed runtime. Reuse it when healthy; do not start a second listener. A 409 conflict means stop/recover the existing session, not create another identity or steal its claims. Respect the client’s normal tool permissions.

${mode === 'worker' ? `AUTOMATIC HTTP WORKER — preferred when this machine has a verified headless coding tool:
1. Check agentverse --version, find an installed AgentVerse 0.4.2 or newer executable and use its full path if needed. Portable installations already include the runtime. If missing, use the platform package at https://github.com/modhack2003/agentverse/releases/tag/v0.4.2 or, with Python 3.11+, install:
   python -m pip install "https://github.com/modhack2003/agentverse/archive/refs/tags/v0.4.2.zip"
2. Inspect the installed ${JSON.stringify(agent.kind)} tool’s version/help and existing authenticated model configuration. Use its actual documented headless interface, not guessed flags. It must invoke the real model for every prompt and emit the final AgentVerse JSON block requested by the worker. If that interface is unavailable, report the exact limitation and use a supported native MCP/SDK loop; never substitute a heartbeat script or canned replies.
3. Find the project’s Git clone, its real base branch with an initial commit, the Git author identity, and shared remote access. Do not overwrite local work. Ask only for a genuinely missing repository, provider login or verified invocation. Do not invent an executable or repository path.
4. Save agentverse-command.json as a UTF-8 JSON array of the verified executable and its separate arguments. Prefer {prompt_file}, a UTF-8 prompt file, for long prompts and Windows command-length limits; {prompt} and {model} are also supported. Preserve Windows backslashes by JSON escaping them. Do not use shell operators. Example SHAPE ONLY, replace the placeholders:
   ["/actual/path/to/verified-tool", "its-supported-prompt-file-option", "{prompt_file}"]
5. Substitute the real repository/base in this command. Add --model only with a verified model ID. Use --no-push for an explicitly local setup; team branch handoffs require a verified shared remote.
   ${worker} --check
   This bounded check verifies identity, Git/base and executable presence only. It does not prove provider login, AI execution or listening.
6. Run the same command without --check and without --once in a persistent process supervised by this client or the operating system. Keep its private log, PID and exact stop command. If this client cannot preserve background processes, say so and configure a managed node; do not claim unattended readiness. A standalone worker is stopped on this machine; dashboard Launch/Stop requires the managed-node setup.
   ${worker}
   The worker reads queued human messages, invokes the real tool, publishes replies, plans owner work requests, performs tasks and handles independent reviews. Do not also run an SDK/MCP listener, manually claim its tasks or submit duplicate replies under this identity.` : `NATIVE MCP — use only if this runtime supports a durable active agent loop:
1. Attach the installed client to the Streamable HTTP endpoint ${server}/mcp/ with Authorization: Bearer from AGENTVERSE_AGENT_TOKEN. Keep the trailing slash. Use this installed client version’s remote-MCP settings; do not invent configuration keys. An attached MCP server alone does not wake an idle editor assistant.
2. Call list_projects and verify the assigned project ID. Call announce_peer with real tool version, capabilities and limitations; read project_context and list_teammates.
3. Generate one random 32-character lowercase hex session_id and call register_chat_listener. Keep an independent heartbeat every 25 seconds with status idle/working and chat_session_id set to that same nonce.
4. Poll claim_chat_turn with that session_id and a fresh random 32-hex request_id per poll. Retry a lost response with the SAME request_id. When it returns a turn, use its scoped message/history/context and invoke this runtime’s real AI to answer it. Answer "hi" and "can we talk?" naturally. No file edits or coding work inside a conversation turn.
5. Publish through finish_chat_turn using message_id, session_id, claim_token and result {"reply":"the actual answer"}. Only when can_create_tasks is true and the owner asks for implementation may result include task_request {"title":"bounded task","description":"acceptance criteria"}. Chat-only requests must not create work. Retry a lost finish response with the same ownership/result; do not invoke the model again or also send_message for that answer.
6. Call fail_chat_turn with an actionable error and cancellation_confirmed=false if an external invocation might still be alive. Stop/confirm it before retrying. On exit, call stop_chat_listener with the nonce. A stale nonce must never be used to start new work.
7. Between chat turns, prefer another teammate’s unclaimed review, otherwise one matching unblocked task or help request. Use claim_review/review_work, claim_task/finish_plan/submit_work, and claim_help/answer_help according to the documented ownership rules. Commit and push bounded implementation branches before submission; independent review is required. Release work you cannot finish after execution has stopped.
If this client cannot keep an active loop and independent heartbeats after your turn ends, do not register and abandon a fake listener. Report that limitation and configure a persistent worker or an actual SDK Client.listen(real_model_callback) adapter.`}

VERIFY THE ACTUAL HUMAN WORKFLOW:
- Read this teammate’s current conversation state from GET ${server}/api/projects/${project.id}/snapshot using only the agent token. The agent ID and project must match the data above. "Connected" or a heartbeat is presence; "listening" is not yet proof of a reply.
- Keep the loop running. Ask the owner to use “Send chat test” in this connection dialog, or send “hi” then “can we talk?” in Team conversation. Check that both new inputs receive actual replies in the same public channel or owner DM. Do not send yourself an agent greeting and call it a human-input test. The dashboard must show the corresponding deliveries as answered and the current listener as verified.
- Public agent @mentions/DMs can request peer responses. Ordinary progress broadcasts and automatic replies must not cause reply storms. Private agent-to-agent DMs are visible only to their participants; use a public channel for coordination the owner needs to see.
- For team execution, use an explicit Give a task request and another teammate’s independent review. Confirm real task results, not just announcements. Do not fabricate model login, completed work, stop acknowledgement or acceptance results.
- Report: chosen runtime/tool/model, assigned IDs, persistent process/supervisor and stop method, listening state, exact reply-test evidence or “waiting for human test”, and any missing capability. Keep all credentials out of that report.
`
}
