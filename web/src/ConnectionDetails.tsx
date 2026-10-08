import { Copy, ChevronRight } from 'lucide-react'
import type { Agent } from './types'

export default function ConnectionDetails({ agent, token, copy }: { agent: Agent; token: string; copy: (text: string) => void }) {
  const server = location.origin
  const python = `import os\nimport time\nfrom agentverse import Client\n\nwith Client("${server}", os.environ["AGENTVERSE_AGENT_TOKEN"]) as peer:\n    connected = peer.connect(\n        capabilities=["planning", "implementation", "review", "testing"],\n        tool_version="2.2.1"\n    )\n    project_id = connected["agent"]["project_id"]\n    peer.say(project_id, "Omnirush is connected over HTTP.")\n    while True:\n        peer.post("/api/agents/heartbeat", {"status": "idle"})\n        time.sleep(25)`
  const powershell = `$env:AGENTVERSE_SERVER = "${server}"\n$env:AGENTVERSE_AGENT_TOKEN = "${token}"\n\n$headers = @{ Authorization = "Bearer $env:AGENTVERSE_AGENT_TOKEN" }\n$body = @{\n  connection = "http"\n  protocol_version = 1\n  tool_version = "2.2.1"\n  capabilities = @("planning", "implementation", "review", "testing")\n  limitations = @()\n} | ConvertTo-Json\n\nInvoke-RestMethod "$env:AGENTVERSE_SERVER/api/agents/announce" -Method Post -Headers $headers -ContentType "application/json" -Body $body`
  return <div className="connection-dialog">
    <label>Agent token<div className="copy-box"><code>{token}</code><button className="icon-button" aria-label="Copy agent token" onClick={() => copy(token)}><Copy size={16} /></button></div></label>
    <div className="connection-step"><span>1</span><div><h3>Connect {agent.name} over HTTP</h3><p>HTTP is the simplest agent connection. The client uses the AgentVerse SDK or REST API to announce itself, read context, send messages, request help, and maintain a heartbeat.</p></div></div>
    <h3>Python HTTP SDK</h3><pre>{python}</pre><button className="button secondary" onClick={() => copy(python)}><Copy size={15} />Copy Python setup</button>
    <h3>Windows PowerShell / REST</h3><pre>{powershell}</pre><button className="button secondary" onClick={() => copy(powershell)}><Copy size={15} />Copy PowerShell setup</button>
    <div className="connection-step"><span>2</span><div><h3>Introduce the session to its teammates</h3><p>Call <code>announce_peer</code> through HTTP, then use <code>list_teammates</code>, <code>project_context</code>, and <code>team_inbox</code>. Keep the process active and send a heartbeat every 25 seconds.</p></div></div>
    <div className="connection-step"><span>3</span><div><h3>For Launch and Stop from the web UI</h3><p>HTTP connected sessions are manageable for collaboration, but they do not let the dashboard start or stop the agent. Add a remote node with a verified managed CLI or jobs-protocol API adapter, then choose Configure → runtime → model/settings → Launch.</p></div></div>
    <h3>Standalone worker option</h3><pre>{`export AGENTVERSE_AGENT_TOKEN='${token}'\nuv run agentverse worker --server ${server} \\\n  --repo /path/to/project \\\n  --command 'your-verified-headless-command {prompt}'`}</pre>
    <p>Use a different token for every active session. Provider credentials and executable commands stay on the agent machine.</p>
    <a className="text-button node-docs" href="https://github.com/modhack2003/agentverse/blob/main/docs/agents.md" target="_blank" rel="noreferrer">HTTP agent recipes and managed runtime guide <ChevronRight size={14} /></a>
  </div>
}
