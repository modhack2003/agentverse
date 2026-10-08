import { Copy, ChevronRight } from 'lucide-react'
import type { Agent } from './types'

export default function ConnectionDetails({ agent, token, copy }: { agent: Agent; token: string; copy: (text: string) => void }) {
  const server = location.origin
  const pythonString = (value: string) => JSON.stringify(value)
  const powerShellString = (value: string) => `"${value.replace(/[`"$]/g, character => `\`${character}`)}"`
  const capabilities = JSON.stringify(agent.configured_capabilities)
  const limitations = JSON.stringify(agent.configured_limitations)
  const toolVersion = agent.session_info.tool_version || ''
  const powerShellCapabilities = agent.configured_capabilities.map(powerShellString).join(', ')
  const powerShellLimitations = agent.configured_limitations.map(powerShellString).join(', ')
  const python = `import time
from agentverse import Client

SERVER = ${pythonString(server)}
TOKEN = ${pythonString(token)}

with Client(SERVER, TOKEN) as peer:
    connected = peer.connect(
        capabilities=${capabilities},
        limitations=${limitations},
        tool_version=${pythonString(toolVersion)}
    )
    project_id = connected["agent"]["project_id"]
    peer.say(project_id, ${pythonString(`${agent.name} is connected over HTTP.`)})
    while True:
        peer.post("/api/agents/heartbeat", {"status": "idle"})
        time.sleep(25)`
  const powershell = `$env:AGENTVERSE_SERVER = ${powerShellString(server)}
$env:AGENTVERSE_AGENT_TOKEN = ${powerShellString(token)}

$headers = @{ Authorization = "Bearer $env:AGENTVERSE_AGENT_TOKEN" }
$body = @{
  connection = "http"
  protocol_version = 1
  tool_version = ${powerShellString(toolVersion)}
  capabilities = @(${powerShellCapabilities})
  limitations = @(${powerShellLimitations})
} | ConvertTo-Json

Invoke-RestMethod "$env:AGENTVERSE_SERVER/api/agents/announce" -Method Post -Headers $headers -ContentType "application/json" -Body $body

while ($true) {
  Invoke-RestMethod "$env:AGENTVERSE_SERVER/api/agents/heartbeat" -Method Post -Headers $headers -ContentType "application/json" -Body '{"status":"idle"}'
  Start-Sleep -Seconds 25
}`
  return <div className="connection-dialog">
    <label>Agent token<div className="copy-box"><code>{token}</code><button className="icon-button" aria-label="Copy agent token" onClick={() => copy(token)}><Copy size={16} /></button></div></label>
    <div className="connection-step"><span>1</span><div><h3>Connect {agent.name} over HTTP</h3><p>HTTP is the simplest agent connection. The client uses the AgentVerse SDK or REST API to announce itself, read context, send messages, request help, and maintain a heartbeat.</p></div></div>
    <h3>Python HTTP SDK</h3><pre>{python}</pre><button className="button secondary" onClick={() => copy(python)}><Copy size={15} />Copy Python setup</button>
    <h3>Windows PowerShell / REST</h3><pre>{powershell}</pre><button className="button secondary" onClick={() => copy(powershell)}><Copy size={15} />Copy PowerShell setup</button>
    <div className="connection-step"><span>2</span><div><h3>Introduce the session to its teammates</h3><p>These examples announce the selected agent’s actual capabilities and limitations, then keep its presence alive with a heartbeat every 25 seconds.</p></div></div>
    <div className="connection-step"><span>3</span><div><h3>For Launch and Stop from the web UI</h3><p>HTTP connected sessions are manageable for collaboration, but they do not let the dashboard start or stop the agent. Add a remote node with a verified managed CLI or jobs-protocol API adapter, then choose Configure → runtime → model/settings → Launch.</p></div></div>
    <h3>Standalone worker option</h3><pre>{`export AGENTVERSE_AGENT_TOKEN='${token}'
uv run agentverse worker --server ${server} \
  --repo /path/to/project \
  --command 'your-verified-headless-command {prompt}'`}</pre>
    <p>Use a different token for every active session. Provider credentials and executable commands stay on the agent machine.</p>
    <a className="text-button node-docs" href="https://github.com/modhack2003/agentverse/blob/main/docs/agents.md" target="_blank" rel="noreferrer">HTTP agent recipes and managed runtime guide <ChevronRight size={14} /></a>
  </div>
}
