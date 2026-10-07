import { useCallback, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Check, ChevronRight, Copy, Cpu, Globe, LoaderCircle, MessageSquare, Play, Plus, Server, Settings2, Square, Terminal } from 'lucide-react'
import { api } from './api'
import Modal from './Dialog'
import type { Agent, RemoteNode, Snapshot } from './types'

const activeStates = ['queued', 'starting', 'running', 'stopping']

function RuntimeForm({ agent, nodes, busy, error, submit, close }: {
  agent: Agent; nodes: RemoteNode[]; busy: boolean; error: string;
  submit: (config: { node_id: string; profile_id: string; model: string }) => Promise<void>;
  close: () => void;
}) {
  const compatible = nodes.filter(node => node.profiles.some(profile => agent.kind === 'custom' || profile.kind === agent.kind))
  const [nodeId, setNodeId] = useState(agent.runtime?.node_id || compatible[0]?.id || '')
  const profiles = nodes.find(node => node.id === nodeId)?.profiles.filter(profile => agent.kind === 'custom' || profile.kind === agent.kind) || []
  const [profileId, setProfileId] = useState(agent.runtime?.profile_id || profiles[0]?.id || '')
  const models = profiles.find(profile => profile.id === profileId)?.models || []
  const [model, setModel] = useState(agent.runtime?.model ?? models[0]?.id ?? '')
  async function save(event: FormEvent) {
    event.preventDefault()
    await submit({ node_id: nodeId, profile_id: profileId, model })
  }
  return <form className="dialog-form" onSubmit={e => void save(e)}>
    <label>Remote node<select aria-label="Remote node" value={nodeId} onChange={e => {
      const node = nodes.find(n => n.id === e.target.value)
      const profile = node?.profiles.find(p => agent.kind === 'custom' || p.kind === agent.kind)
      setNodeId(e.target.value); setProfileId(profile?.id || ''); setModel(profile?.models[0]?.id || '')
    }} required><option value="" disabled>Select a connected node</option>{compatible.map(node => <option key={node.id} value={node.id}>{node.name} · {node.online ? 'online' : 'offline'}</option>)}</select></label>
    <label>Agent runtime<select aria-label="Agent runtime" value={profileId} onChange={e => { setProfileId(e.target.value); setModel(profiles.find(p => p.id === e.target.value)?.models[0]?.id || '') }} required>
      <option value="" disabled>Select an installed tool</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
    </select></label>
    <label>Model<select aria-label="Model" value={model} onChange={e => setModel(e.target.value)} disabled={!models.length}>
      {models.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
    </select></label>
    <div className="runtime-help"><Cpu size={17} /><p>Models come from this node’s tool configuration. The selected model is passed to the worker, command, and task context when you launch.</p></div>
    {!compatible.length && <p className="form-error">No node advertises a {agent.kind} runtime yet. Register a remote node and start its node service.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="dialog-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary" disabled={busy || !profileId || !models.length}>{busy ? <LoaderCircle size={15} className="spin" /> : <><Check size={15} />Save runtime</>}</button></div>
  </form>
}

export default function RemoteAgents({ snapshot, token, reload, avatar, invite, message }: {
  snapshot: Snapshot; token: string; reload: () => Promise<void>;
  avatar: (agent: Agent) => ReactNode; invite: () => void; message: (agent: Agent) => void;
}) {
  const [dialog, setDialog] = useState<'node' | 'invitation' | 'runtime' | null>(null)
  const [selected, setSelected] = useState<Agent | null>(null)
  const [invitation, setInvitation] = useState<{ node: RemoteNode; token: string } | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [cardError, setCardError] = useState<{ id: string; text: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const close = useCallback(() => { setDialog(null); setInvitation(null); setError(''); setCopied(false) }, [])
  const admin = snapshot.identity.admin, nodes = snapshot.nodes
  const base = `/projects/${snapshot.project.id}`
  async function createNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    const data = new FormData(event.currentTarget)
    try {
      const result = await api<{ node: RemoteNode; token: string }>(token, `${base}/nodes`, 'POST', { name: String(data.get('name')).trim() })
      setInvitation(result); setDialog('invitation'); await reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function configure(config: { node_id: string; profile_id: string; model: string }) {
    setBusy(true); setError('')
    try { await api(token, `${base}/agents/${selected!.id}/runtime`, 'PUT', config); await reload(); close() }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function action(agent: Agent, operation: 'launch' | 'stop' | 'revoke') {
    setBusy(true); setCardError(null)
    try {
      await api(token, `${base}/agents/${agent.id}${operation === 'revoke' ? '' : `/${operation}`}`, operation === 'revoke' ? 'DELETE' : 'POST')
      await reload()
    } catch (e) { setCardError({ id: agent.id, text: (e as Error).message }) } finally { setBusy(false) }
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(true) } catch { setError('Select and copy the token below; clipboard access is unavailable.') }
  }

  return <>
    <div className="integration-banner"><div className="integration-symbol"><Globe size={25} /></div><div><h2>Your team, ready on command.</h2><p>Choose where each agent runs and which model it uses. Remote node services keep you connected, from launch through the last review.</p></div><span className="badge purple">Remote control</span></div>
    <div className="section-heading remote-heading"><div><h2>Remote nodes</h2><span>The machines that bring your agents to life</span></div>{admin && <button className="button secondary" onClick={() => { setError(''); setDialog('node') }}><Plus size={14} />Add remote node</button>}</div>
    {nodes.length ? <div className="nodes-grid">{nodes.map(node => <section className="panel node-card" key={node.id}><div className="node-icon"><Server size={20} /></div><div><h3>{node.name}</h3><p>{node.profiles.length ? node.profiles.map(profile => profile.name).join(' · ') : 'Start the node service to advertise tools and models'}</p><span>{node.profiles.reduce((count, profile) => count + profile.models.length, 0)} model options</span></div><span className={`badge ${node.online ? 'green' : 'muted'}`}><span className={`status-dot ${node.online ? 'green' : 'muted'}`} />{node.online ? 'Online' : 'Offline'}</span></section>)}</div> : <section className="panel node-empty"><Server size={24} /><div><h3>Connect a machine. Control the whole team.</h3><p>Run one node service on your remote machine, then launch agents from here.</p></div>{admin && <button className="text-button" onClick={() => { setError(''); setDialog('node') }}>Set up a node <ChevronRight size={15} /></button>}</section>}
    <div className="section-heading remote-heading"><div><h2>Your teammates</h2><span>Independent tools, a model for each role, one shared goal</span></div><span className="subtle">{snapshot.agents.length} connected identities</span></div>
    <div className="agents-grid">{snapshot.agents.map(agent => {
      const runtime = agent.runtime
      const node = nodes.find(n => n.id === runtime?.node_id)
      const active = !!runtime && activeStates.includes(runtime.state)
      const state = agent.revoked ? 'Access revoked' : runtime ? !node?.online && active ? 'Connection lost' : runtime.state : agent.online ? agent.status : 'Offline'
      const color = state === 'running' || !runtime && agent.online ? 'green' : state === 'failed' ? 'danger' : active ? 'amber' : 'muted'
      const modelName = node?.profiles.find(p => p.id === runtime?.profile_id)?.models.find(m => m.id === runtime?.model)?.name
      return <section className="panel agent-card managed-agent" key={agent.id} aria-label={`${agent.name} agent`}>
        <div className="agent-card-top">{avatar(agent)}<span className={`badge ${color}`}><span className={`status-dot ${color === 'green' ? 'green' : color === 'amber' ? 'amber' : 'muted'}`} />{state}</span></div>
        <h2>{agent.name}</h2><p>{agent.kind} · Remote teammate</p>
        <div className="memory-tags">{agent.capabilities.map(cap => <span key={cap}>{cap}</span>)}</div>
        <div className="runtime-summary">{runtime ? <><span><Server size={13} />{node?.name || 'Remote node'}</span><span title={runtime.model}><Cpu size={13} />{modelName || runtime.model || 'Tool default model'}</span>{runtime.pid && active && <span><Terminal size={13} />Worker PID {runtime.pid}</span>}</> : <span><Settings2 size={14} />Set a node, tool, and model to enable launch controls.</span>}</div>
        {runtime?.error && <p className="runtime-error" role="status">{runtime.error}</p>}
        {cardError?.id === agent.id && <p className="form-error" role="alert">{cardError.text}</p>}
        {admin && !agent.revoked && <div className="runtime-actions"><button className="button secondary" disabled={busy || active} aria-label={`Configure ${agent.name}`} onClick={() => { setSelected(agent); setError(''); setDialog('runtime') }}><Settings2 size={14} />Configure</button>{active ? <button className="button secondary stop-agent" aria-label={`Stop ${agent.name}`} disabled={busy || runtime?.state === 'stopping'} onClick={() => void action(agent, 'stop')}>{runtime?.state === 'stopping' ? <LoaderCircle size={14} className="spin" /> : <Square size={13} />}{runtime?.state === 'stopping' ? 'Stopping…' : 'Stop'}</button> : <button className="button primary" aria-label={`Launch ${agent.name}`} disabled={busy || !runtime || !node?.online || snapshot.project.status === 'paused'} onClick={() => void action(agent, 'launch')}><Play size={14} />Launch</button>}</div>}
        <div className="agent-card-bottom"><button className="text-button" onClick={() => message(agent)}><MessageSquare size={14} />Message</button>{admin && !agent.revoked && <button className="text-button danger" onClick={() => { if (confirm(`Revoke ${agent.name}'s access and stop its managed worker?`)) void action(agent, 'revoke') }}>Revoke access</button>}</div>
      </section>
    })}{admin && <button className="agent-add-card" onClick={invite}><span><Plus size={25} /></span><h3>Add a teammate</h3><p>OpenCode, Cline, Omnirush,<br />Agent Zero, or your own agent.</p></button>}</div>
    <section className="panel endpoint-panel"><div><Terminal size={19} /><h2>Remote MCP endpoint</h2></div><code>{location.origin}/mcp/</code><button className="icon-button" aria-label="Copy MCP endpoint" onClick={() => void copy(`${location.origin}/mcp/`)}><Copy size={16} /></button></section>
    {dialog && <Modal title={dialog === 'node' ? 'Connect a remote machine.' : dialog === 'invitation' ? `${invitation?.node.name} is ready to connect.` : `Configure ${selected?.name}`} description={dialog === 'node' ? 'One service on your machine, launch controls for every teammate.' : dialog === 'invitation' ? 'Save this one-time node token. The service uses it to receive launch and stop requests.' : 'Choose an installed runtime and the model for this teammate.'} close={close}>
      {dialog === 'node' && <form className="dialog-form" onSubmit={e => void createNode(e)}><label>Node name<input name="name" required maxLength={100} placeholder="e.g. My development VPS" /></label><p className="form-hint">This node belongs to {snapshot.project.name}. Its repository path and executable commands are configured on the remote machine.</p>{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <><Plus size={15} />Register node</>}</button></div></form>}
      {dialog === 'runtime' && selected && <RuntimeForm key={selected.id} agent={selected} nodes={nodes} busy={busy} error={error} submit={configure} close={close} />}
      {dialog === 'invitation' && invitation && <div className="connection-dialog"><label>Node token<div className="copy-box"><code>{invitation.token}</code><button className="icon-button" aria-label="Copy node token" onClick={() => void copy(invitation.token)}><Copy size={16} /></button></div></label><h3>Start the service on this remote machine</h3><pre>{`export AGENTCOMMONS_NODE_TOKEN='${invitation.token}'\nuv run agentcommons node --server ${location.origin} \\\n  --config /path/to/node.json`}</pre><p>Copy examples/node.example.json from the repository, set the project clone path, and list the installed commands and models. Then run this service once; the dashboard handles individual agent launches.</p><a className="text-button node-docs" href="https://github.com/modhack2003/agentcommons/blob/main/docs/remote-control.md" target="_blank" rel="noreferrer">Remote node setup guide <ChevronRight size={14} /></a>{copied && <p className="form-hint">Copied to clipboard.</p>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><button className="button primary" onClick={close}><Check size={15} />I saved the node token</button></div></div>}
    </Modal>}
  </>
}
