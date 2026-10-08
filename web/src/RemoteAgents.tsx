import { useCallback, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Check, ChevronRight, Copy, Cpu, Globe, LoaderCircle, MessageSquare, Play, Plus, Server, Settings2, Square, Terminal, TriangleAlert } from 'lucide-react'
import { api } from './api'
import Modal from './Dialog'
import ConnectionDetails from './ConnectionDetails'
import CoordinationHistory from './CoordinationHistory'
import type { Agent, ConnectionMode, RemoteNode, RuntimeConfig, SettingValue, Snapshot } from './types'

const activeStates = ['queued', 'starting', 'running', 'stopping', 'unconfirmed']
const modeName: Record<ConnectionMode, string> = { managed_cli: 'Managed CLI', managed_api: 'Managed API', connected: 'Connected session' }
const split = (value: string) => value.split(',').map(v => v.trim()).filter(Boolean)

function RuntimeForm({ agent, nodes, busy, error, submit, close }: {
  agent: Agent; nodes: RemoteNode[]; busy: boolean; error: string; submit: (config: RuntimeConfig) => Promise<void>; close: () => void;
}) {
  const compatible = nodes.filter(n => n.profiles.some(p => agent.kind === 'custom' || p.kind === agent.kind))
  const [nodeId, setNodeId] = useState(agent.runtime?.node_id || compatible[0]?.id || '')
  const profiles = nodes.find(n => n.id === nodeId)?.profiles.filter(p => agent.kind === 'custom' || p.kind === agent.kind) || []
  const [profileId, setProfileId] = useState(agent.runtime?.profile_id || profiles[0]?.id || '')
  const profile = profiles.find(p => p.id === profileId), models = profile?.models || []
  const [model, setModel] = useState(agent.runtime?.model ?? models[0]?.id ?? '')
  const [settings, setSettings] = useState<Record<string, SettingValue>>(agent.runtime?.settings || {})
  const value = (key: string, fallback: SettingValue) => Object.hasOwn(settings, key) ? settings[key] : fallback
  const change = (key: string, next: SettingValue) => setSettings(current => ({ ...current, [key]: next }))
  return <form className="dialog-form" onSubmit={e => { e.preventDefault(); void submit({ node_id: nodeId, profile_id: profileId, model, settings }) }}>
    <label>Remote node<select aria-label="Remote node" value={nodeId} onChange={e => {
      const first = nodes.find(n => n.id === e.target.value)?.profiles.find(p => agent.kind === 'custom' || p.kind === agent.kind)
      setNodeId(e.target.value); setProfileId(first?.id || ''); setModel(first?.models[0]?.id || ''); setSettings({})
    }} required><option value="" disabled>Select a connected node</option>{compatible.map(n => <option key={n.id} value={n.id}>{n.name} · {n.online ? 'online' : 'offline'}</option>)}</select></label>
    <label>Agent runtime<select aria-label="Agent runtime" value={profileId} onChange={e => { setProfileId(e.target.value); setModel(profiles.find(p => p.id === e.target.value)?.models[0]?.id || ''); setSettings({}) }} required>
      <option value="" disabled>Select a configured tool</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name} · {modeName[p.mode] || 'Managed CLI'}{p.availability !== 'available' ? ' · needs attention' : ''}</option>)}
    </select></label>
    <label>Model<select aria-label="Model" value={model} onChange={e => setModel(e.target.value)} disabled={!models.length || profile?.mode === 'connected'}>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
    {profile && <div className="profile-contract"><strong>{modeName[profile.mode]} · protocol {profile.protocol_version}{profile.tool_version ? ` · ${profile.tool_version}` : ''}</strong><p>{profile.mode === 'connected' ? 'Start this tool in its own client and connect through the AgentVerse HTTP API. Launch and stop are controlled there; model/settings are configured in that client.' : 'This node runs the adapter. Model and settings below are passed to each task invocation.'}</p><p>{profile.diagnostic}</p>{profile.capabilities.length > 0 && <p>Capabilities: {profile.capabilities.join(', ')}</p>}{profile.limitations.length > 0 && <p>Limitations: {profile.limitations.join(' · ')}</p>}</div>}
    {profile?.mode !== 'connected' && profile?.settings_schema.map(field => {
      const current = value(field.key, field.default)
      const required = profile.required_settings?.includes(field.key)
      return <label key={field.key} className={field.type === 'boolean' ? 'checkbox-label' : ''}>
        {field.type === 'boolean' ? <><input type="checkbox" checked={current === true} onChange={e => change(field.key, e.target.checked)} /><span>{field.label}</span></> : <>{field.label}{field.type === 'choice' ? <select value={String(current ?? '')} onChange={e => change(field.key, e.target.value || null)}><option value="">Tool default</option>{field.options.map(option => <option key={option}>{option}</option>)}</select> : <input type={field.type === 'number' ? 'number' : 'text'} min={field.minimum ?? undefined} max={field.maximum ?? undefined} step="any" value={String(current ?? '')} maxLength={5000} onChange={e => change(field.key, e.target.value === '' ? null : field.type === 'number' ? Number(e.target.value) : e.target.value)} />}</>}
        {required && <small className="form-hint">Required by this command. Choose an explicit value if no default is provided.</small>}{field.help && <small className="form-hint">{field.help}</small>}
      </label>
    })}
    <div className="runtime-help"><Cpu size={17} /><p>Only controls advertised by this adapter appear here. Tool authentication stays on the node. Save a configuration even while a tool needs setup; Launch becomes available after it is healthy.</p></div>
     {!compatible.length && <p className="form-error">No node advertises a {agent.kind} profile yet. Add it to your node configuration, or connect the tool directly through the AgentVerse HTTP API.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="dialog-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary" disabled={busy || !profileId || !models.some(m => m.id === model)}>{busy ? <LoaderCircle size={15} className="spin" /> : <><Check size={15} />Save runtime</>}</button></div>
  </form>
}

export default function RemoteAgents({ snapshot, token, reload, avatar, invite, message }: {
  snapshot: Snapshot; token: string; reload: () => Promise<void>; avatar: (agent: Agent) => ReactNode; invite: () => void; message: (agent: Agent) => void;
}) {
  const [dialog, setDialog] = useState<'node' | 'invitation' | 'runtime' | 'profile' | 'issue' | 'help' | 'connection' | null>(null)
  const [selected, setSelected] = useState<Agent | null>(null)
  const [invitation, setInvitation] = useState<{ node: RemoteNode; token: string } | null>(null)
  const [agentToken, setAgentToken] = useState('')
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [cardError, setCardError] = useState<{ id: string; text: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const close = useCallback(() => { setDialog(null); setInvitation(null); setAgentToken(''); setError(''); setCopied(false) }, [])
  const admin = snapshot.identity.admin, nodes = snapshot.nodes, base = `/projects/${snapshot.project.id}`
  const select = (agent: Agent, mode: typeof dialog) => { setSelected(agent); setError(''); setAgentToken(''); setDialog(mode) }
  async function save(path: string, method: string, data?: unknown) {
    setBusy(true); setError('')
    try { const result = await api(token, path, method, data); await reload().catch(() => setError('Saved successfully; workspace refresh failed. Live updates will retry.')); return result }
    catch (e) { setError((e as Error).message); throw e } finally { setBusy(false) }
  }
  async function createNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try { const result = await save(`${base}/nodes`, 'POST', { name: String(new FormData(event.currentTarget).get('name')).trim() }) as { node: RemoteNode; token: string }; setInvitation(result); setDialog('invitation') } catch { /* Form shows error. */ }
  }
  async function configure(config: RuntimeConfig) { try { await save(`${base}/agents/${selected!.id}/runtime`, 'PUT', config); close() } catch { /* Form shows error. */ } }
  async function action(agent: Agent, operation: 'launch' | 'stop' | 'revoke') {
    setBusy(true); setCardError(null)
    try { await api(token, `${base}/agents/${agent.id}${operation === 'revoke' ? '' : `/${operation}`}`, operation === 'revoke' ? 'DELETE' : 'POST'); await reload() }
    catch (e) { setCardError({ id: agent.id, text: (e as Error).message }) } finally { setBusy(false) }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget), field = (key: string) => String(data.get(key) || '').trim()
    try {
      if (dialog === 'profile') await save(`${base}/agents/${selected!.id}`, 'PATCH', { name: field('name'), description: field('description'), capabilities: split(field('capabilities')), limitations: field('limitations').split('\n').map(v => v.trim()).filter(Boolean), expected_version: selected!.profile_version })
      if (dialog === 'issue') await save(`${base}/agents/${selected!.id}/issues`, 'POST', { title: field('title'), detail: field('detail'), severity: field('severity') })
      if (dialog === 'help') await save(`${base}/help`, 'POST', { question: field('question'), capability: field('capability') })
      close()
    } catch { /* Form shows error. */ }
  }
  async function rotate() { try { const result = await save(`${base}/agents/${selected!.id}/token`, 'POST') as { token: string }; setAgentToken(result.token) } catch { /* Dialog shows error. */ } }
  async function resolve(id: string) { try { await save(`${base}/issues/${id}/resolve`, 'POST') } catch { /* Error shown below. */ } }
  async function copy(text: string) { try { await navigator.clipboard.writeText(text); setCopied(true) } catch { setError('Select and copy the text; clipboard access is unavailable.') } }

  return <>
    <div className="integration-banner"><div className="integration-symbol"><Globe size={25} /></div><div><h2>Your team, ready on command.</h2><p>Every tool brings its own strengths. Connect a CLI, API adapter, editor, or app; let teammates discover and help each other.</p></div><span className="badge purple">Agent-neutral</span></div>
     <div className="connection-modes">{Object.entries(modeName).map(([mode, name]) => <div key={mode}><strong>{name}</strong><p>{mode === 'managed_cli' ? 'Node runs a verified headless command. Launch, stop, and model selection here.' : mode === 'managed_api' ? 'Node talks to a jobs-protocol API. Cancellation stays held until acknowledged.' : 'Agent connects through the HTTP API. Start it and choose its model in its own client; web Launch/Stop requires a managed node.'}</p></div>)}</div>
    <div className="section-heading remote-heading"><div><h2>Remote nodes</h2><span>Independent inventories for every machine</span></div>{admin && <button className="button secondary" onClick={() => { setError(''); setDialog('node') }}><Plus size={14} />Add remote node</button>}</div>
    {nodes.length ? <div className="nodes-grid">{nodes.map(node => <section className="panel node-card" key={node.id}><div className="node-icon"><Server size={20} /></div><div className="node-details"><h3>{node.name}</h3><p>{node.profiles.length ? node.profiles.map(p => p.name).join(' · ') : 'Start the node service to advertise tools and models'}</p><span>{node.profiles.reduce((c, p) => c + p.models.length, 0)} model options · capacity {node.capacity} · protocol {node.protocol_version}</span>{node.profiles.length > 0 && <details className="node-inventory"><summary>Tool health & connection modes</summary>{node.profiles.map(p => <div key={p.id}><strong>{p.name} · {modeName[p.mode]}</strong><p className={p.availability !== 'available' ? 'diagnostic-warning' : ''}>{p.diagnostic || p.availability.replace('_', ' ')}</p>{p.tool_version && <small>Version {p.tool_version}</small>}</div>)}{node.diagnostics.filter(d => !d.profile_id).map((d, i) => <p className="diagnostic-warning" key={i}>{d.message}</p>)}</details>}</div><span className={`badge ${node.online ? 'green' : 'muted'}`}><span className={`status-dot ${node.online ? 'green' : 'muted'}`} />{node.online ? 'Online' : 'Offline'}</span></section>)}</div> : <section className="panel node-empty"><Server size={24} /><div><h3>Connect a machine. Control the whole team.</h3><p>Run one node service per remote machine for managed work. Connected sessions can join directly.</p></div>{admin && <button className="text-button" onClick={() => { setError(''); setDialog('node') }}>Set up a node <ChevronRight size={15} /></button>}</section>}
    <div className="section-heading remote-heading"><div><h2>Your teammates</h2><span>Discover capabilities, share limitations, route help</span></div><span className="subtle">{snapshot.agents.length} identities</span></div>
    <div className="agents-grid">{snapshot.agents.map(agent => {
      const runtime = agent.runtime, node = nodes.find(n => n.id === runtime?.node_id), profile = node?.profiles.find(p => p.id === runtime?.profile_id)
      const connected = !runtime || runtime.mode === 'connected', active = !!runtime && activeStates.includes(runtime.state)
      const state = agent.revoked ? 'Access revoked' : connected ? agent.online ? agent.status : 'Offline' : !node?.online && active ? 'Connection lost' : runtime!.state
      const color = state === 'running' || connected && agent.online ? 'green' : state === 'failed' || state === 'unconfirmed' ? 'danger' : active ? 'amber' : 'muted'
      const modelName = profile?.models.find(m => m.id === runtime?.model)?.name
      const own = admin || agent.id === snapshot.identity.actor_id
      return <section className="panel agent-card managed-agent" key={agent.id} aria-label={`${agent.name} agent`}>
        <div className="agent-card-top">{avatar(agent)}<span className={`badge ${color}`}><span className={`status-dot ${color === 'green' ? 'green' : color === 'amber' ? 'amber' : 'muted'}`} />{state}</span></div>
        <h2>{agent.name}</h2><p>{agent.kind} · {connected ? 'Connected session' : modeName[runtime!.mode]}</p>{agent.description && <p className="agent-description">{agent.description}</p>}
        <div className="memory-tags">{agent.capabilities.map(cap => <span key={cap}>{cap}</span>)}</div>
        {agent.limitations.length > 0 && <p className="agent-limitations"><TriangleAlert size={12} />{agent.limitations.join(' · ')}</p>}
         <div className="runtime-summary">{runtime ? <><span><Server size={13} />{node?.name || 'Remote node'}</span><span title={runtime.model}><Cpu size={13} />{modelName || runtime.model || 'Tool default model'}</span>{runtime.pid && active && <span><Terminal size={13} />Worker PID {runtime.pid}</span>}</> : <span><Globe size={14} />Connect through HTTP, or configure a managed node runtime.</span>}{agent.session_info.tool_version && <span>Session version {agent.session_info.tool_version}</span>}</div>
        {profile?.availability !== 'available' && profile && <p className="runtime-error">{profile.diagnostic}</p>}{runtime?.error && <p className="runtime-error" role="status">{runtime.error}</p>}
        {runtime?.state === 'unconfirmed' && <p className="runtime-error">Previous API work may still be running. The node retries cancellation; claims remain held until the endpoint acknowledges it.</p>}
        {cardError?.id === agent.id && <p className="form-error" role="alert">{cardError.text}</p>}
        {admin && !agent.revoked && <div className="runtime-actions"><button className="button secondary" disabled={busy || active} aria-label={`Configure ${agent.name}`} onClick={() => select(agent, 'runtime')}><Settings2 size={14} />Configure</button>{active && runtime?.state !== 'unconfirmed' ? <button className="button secondary stop-agent" aria-label={`Stop ${agent.name}`} disabled={busy || runtime?.state === 'stopping'} onClick={() => void action(agent, 'stop')}>{runtime?.state === 'stopping' ? <LoaderCircle size={14} className="spin" /> : <Square size={13} />}{runtime?.state === 'stopping' ? 'Stopping…' : 'Stop'}</button> : connected ? <button className="button secondary" onClick={() => select(agent, 'connection')}><Globe size={14} />Connect</button> : <button className="button primary" aria-label={`Launch ${agent.name}`} title={profile?.diagnostic} disabled={busy || active || !runtime || !node?.online || profile?.availability !== 'available' || snapshot.project.status === 'paused'} onClick={() => void action(agent, 'launch')}><Play size={14} />Launch</button>}</div>}
        <div className="peer-actions"><button className="text-button" aria-label={`Profile ${agent.name}`} onClick={() => select(agent, 'profile')}>{admin ? 'Edit profile' : 'View profile'}</button>{own && !agent.revoked && <button className="text-button" aria-label={`Report problem for ${agent.name}`} onClick={() => select(agent, 'issue')}>Report problem</button>}</div>
        <div className="agent-card-bottom"><button className="text-button" onClick={() => message(agent)}><MessageSquare size={14} />Message</button>{admin && !agent.revoked && <button className="text-button danger" onClick={() => { if (confirm(`Revoke ${agent.name}'s access and stop its managed worker?`)) void action(agent, 'revoke') }}>Revoke access</button>}</div>
      </section>
    })}{admin && <button className="agent-add-card" onClick={invite}><span><Plus size={25} /></span><h3>Add a teammate</h3><p>Any tool. Its own capabilities.<br />One equal place on the team.</p></button>}</div>
    <CoordinationHistory snapshot={snapshot} token={token} busy={busy} resolve={resolve} ask={() => { setError(''); setDialog('help') }} />
    {!dialog && error && <p className="form-error" role="alert">{error}</p>}{!dialog && copied && <p className="form-hint" role="status">Copied to clipboard.</p>}
     <section className="panel endpoint-panel"><div><Terminal size={19} /><h2>Remote HTTP API</h2></div><code>{location.origin}/api/</code><button className="icon-button" aria-label="Copy HTTP API endpoint" onClick={() => void copy(`${location.origin}/api/`)}><Copy size={16} /></button></section>
    {dialog && <Modal title={dialog === 'node' ? 'Connect a remote machine.' : dialog === 'invitation' ? `${invitation?.node.name} is ready to connect.` : dialog === 'runtime' ? `Configure ${selected?.name}` : dialog === 'profile' ? `${selected?.name}’s profile` : dialog === 'issue' ? `Report a problem for ${selected?.name}` : dialog === 'help' ? 'Ask an equal teammate for help.' : `Connect ${selected?.name}`} description={dialog === 'runtime' ? 'This node advertises the tool’s supported mode, models, settings, and limitations.' : dialog === 'profile' ? 'Capabilities and limitations are shared with teammates. Edits detect concurrent changes.' : undefined} close={close}>
      {dialog === 'node' && <form className="dialog-form" onSubmit={e => void createNode(e)}><label>Node name<input name="name" required maxLength={100} placeholder="e.g. My development VPS" /></label><p className="form-hint">This node belongs to {snapshot.project.name}. Its commands, project clone, and provider credentials stay on that machine.</p>{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <><Plus size={15} />Register node</>}</button></div></form>}
      {dialog === 'runtime' && selected && <RuntimeForm key={selected.id} agent={selected} nodes={nodes} busy={busy} error={error} submit={configure} close={close} />}
      {dialog === 'invitation' && invitation && <div className="connection-dialog"><label>Node token<div className="copy-box"><code>{invitation.token}</code><button className="icon-button" aria-label="Copy node token" onClick={() => void copy(invitation.token)}><Copy size={16} /></button></div></label><h3>Prepare and inspect this remote machine</h3><pre>{`uv sync --frozen\nuv run agentverse doctor\nuv run agentverse doctor --config /path/to/node.json`}</pre><p>Start from examples/node.example.json. Choose a mode for each tool, prepare a project Git clone for managed coding, and configure authentication in the tool’s own client. A missing tool does not disable other profiles.</p><h3>Start the node service</h3><pre>{`export AGENTVERSE_NODE_TOKEN='${invitation.token}'\nuv run agentverse node --server ${location.origin} \\\n  --config /path/to/node.json`}</pre><p>Configure and launch teammates here after the node is online. The service refreshes its inventory and reloads valid configuration edits automatically.</p><a className="text-button node-docs" href="https://github.com/modhack2003/agentverse/blob/main/docs/remote-control.md" target="_blank" rel="noreferrer">Remote node setup guide <ChevronRight size={14} /></a>{copied && <p className="form-hint">Copied to clipboard.</p>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><button className="button primary" onClick={close}><Check size={15} />I saved the node token</button></div></div>}
      {(dialog === 'profile' || dialog === 'issue' || dialog === 'help') && <form className="dialog-form" onSubmit={e => void submit(e)}>
        {dialog === 'profile' && selected && <><label>Teammate name<input name="name" defaultValue={selected.name} required maxLength={80} readOnly={!admin} /></label><label>Role & context<textarea name="description" defaultValue={selected.description} maxLength={5000} rows={3} readOnly={!admin} /></label><label>Strengths <span className="optional">comma-separated</span><input name="capabilities" defaultValue={selected.configured_capabilities.join(', ')} readOnly={!admin} /></label><label>Limitations <span className="optional">one per line</span><textarea name="limitations" defaultValue={selected.configured_limitations.join('\n')} rows={3} readOnly={!admin} /></label>{selected.session_info.capabilities?.length ? <p className="form-hint">Session also advertises: {selected.session_info.capabilities.join(', ')}</p> : null}<p className="form-hint">Tool: {selected.kind} · profile version {selected.profile_version}</p></>}
        {dialog === 'issue' && <><label>Problem<input name="title" required maxLength={200} placeholder="e.g. Tool needs reauthentication" /></label><label>Details<textarea name="detail" rows={4} maxLength={5000} placeholder="What happened? What would help?" /></label><label>Severity<select name="severity" defaultValue="warning"><option value="info">Information</option><option value="warning">Needs attention</option><option value="error">Blocking error</option></select></label></>}
        {dialog === 'help' && <><label>Capability needed<input name="capability" maxLength={100} list="peer-capabilities" placeholder="e.g. frontend, python, review" /><datalist id="peer-capabilities">{[...new Set(snapshot.agents.flatMap(a => a.capabilities))].map(c => <option key={c}>{c}</option>)}</datalist></label><label>Question<textarea name="question" required rows={4} maxLength={10000} placeholder="Give a teammate the context needed to help." /></label><p className="form-hint">Help requests and answers are shared with the project team.</p></>}
        {error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={close}>{dialog === 'profile' && !admin ? 'Close' : 'Cancel'}</button>{(dialog !== 'profile' || admin) && <button className="button primary" disabled={busy}>{busy ? <LoaderCircle size={15} className="spin" /> : dialog === 'profile' ? 'Save profile' : dialog === 'issue' ? 'Report problem' : 'Send help request'}</button>}</div>
      </form>}
       {dialog === 'connection' && selected && <>{agentToken ? <ConnectionDetails agent={selected} token={agentToken} copy={text => void copy(text)} /> : <div className="connection-dialog"><p>Use the token saved when you created this teammate with the AgentVerse HTTP API. Start its client, announce capabilities, and keep the session active.</p><pre>{location.origin}/api/</pre><p>If the saved token is lost, generate a replacement. This invalidates the previous connection token; active managed runs or claims must finish first.</p><button className="button secondary" disabled={busy} onClick={() => void rotate()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Globe size={15} />}Generate replacement token</button></div>}{copied && <p className="form-hint">Copied to clipboard.</p>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><button className="button primary" onClick={close}>{agentToken ? 'I saved the token' : 'Done'}</button></div></>}
    </Modal>}
  </>
}
