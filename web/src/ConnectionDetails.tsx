import { Copy, ChevronRight } from 'lucide-react'
import type { Agent } from './types'

export default function ConnectionDetails({ agent, token, copy }: { agent: Agent; token: string; copy: (text: string) => void }) {
  const config = JSON.stringify({ mcpServers: { agentverse: { url: `${location.origin}/mcp/`, headers: { Authorization: `Bearer ${token}` } } } }, null, 2)
  return <div className="connection-dialog">
    <label>Agent token<div className="copy-box"><code>{token}</code><button className="icon-button" aria-label="Copy agent token" onClick={() => copy(token)}><Copy size={16} /></button></div></label>
    <div className="connection-step"><span>1</span><div><h3>Choose how {agent.name} joins</h3><p>Managed CLI: a headless command on a node. Managed API: a jobs-protocol adapter on a node. Connected session: your editor or app stays in control and talks to this workspace.</p></div></div>
    <div className="connection-step"><span>2</span><div><h3>For an editor or application: attach MCP</h3><p>In the client’s remote HTTP MCP settings, add this endpoint and bearer header. Each client may use a different configuration format.</p></div></div>
    <pre>{config}</pre><button className="button secondary" onClick={() => copy(config)}><Copy size={15} />Copy connection config</button>
    <div className="connection-step"><span>3</span><div><h3>Introduce the session to its teammates</h3><p>Ask the agent to call <code>announce_peer</code> with its capabilities and limitations, then <code>list_teammates</code>. Keep it active and send a heartbeat every 25 seconds. An MCP connection alone does not start an unattended loop.</p></div></div>
    <h3>For dashboard-managed work</h3><p>Add a remote node, prepare its project clone and tool authentication, then choose Configure → runtime → model/settings → Launch. The node supplies a run-scoped identity automatically.</p>
    <h3>Or run a standalone worker</h3><pre>{`export AGENTVERSE_AGENT_TOKEN='${token}'\nuv run agentverse worker --server ${location.origin} \\\n  --repo /path/to/project \\\n  --command 'your-verified-headless-command {prompt}'`}</pre>
    <p>Use a different teammate identity for each active session. Provider credentials and executable commands are configured on the remote machine.</p>
    <a className="text-button node-docs" href="https://github.com/modhack2003/agentverse/blob/main/docs/agents.md" target="_blank" rel="noreferrer">Tool-specific connection recipes <ChevronRight size={14} /></a>
  </div>
}
