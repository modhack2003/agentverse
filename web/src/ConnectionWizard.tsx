import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'
import Modal from './Dialog'
import type { Snapshot } from './types'

export default function ConnectionWizard({ token, snapshot }: { token: string; snapshot: Snapshot }) {
  const [open, setOpen] = useState(false), [mode, setMode] = useState('managed_cli')
  const [profile, setProfile] = useState('codex'), [config, setConfig] = useState(''), [error, setError] = useState('')
  const [validated, setValidated] = useState('')
  const [busy, setBusy] = useState(false), [checks, setChecks] = useState('')
  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    const values = Object.fromEntries(new FormData(event.currentTarget))
    try {
      const argv: unknown = mode === 'managed_cli' ? JSON.parse(String(values.argv)) : []
      if (!Array.isArray(argv) || argv.some(arg => typeof arg !== 'string')) throw new Error('Command must be a JSON array of strings.')
      const models = String(values.models || '').split(',').map(id => id.trim()).filter(Boolean).map(id => ({ id, name: id }))
      const data = { repo: String(values.repo), profiles: [{ id: profile, name: profile, kind: profile, mode,
        driver: mode === 'managed_api' ? 'http' : mode === 'connected' ? 'connected' : 'cli', argv, models,
        base: String(values.base || 'main'), push: values.push === 'on',
        ...(mode === 'managed_api' ? { http: { url: String(values.url), token_env: String(values.token_env || '') } } : {}) }] }
      const result = await api<{ config: unknown }>(token, '/local/node-config', 'POST', data)
      setConfig(JSON.stringify(result.config, null, 2)); setValidated(JSON.stringify(result.config, null, 2))
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function validateImported() {
    setBusy(true); setError('')
    try { const result = await api<{ config: unknown }>(token, '/local/node-config', 'POST', JSON.parse(config)); setConfig(JSON.stringify(result.config, null, 2)); setValidated(JSON.stringify(result.config, null, 2)) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  function save() {
    const url = URL.createObjectURL(new Blob([config], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'agentverse-node.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function check() {
    setBusy(true); setError('')
    try {
      const current = await api<Snapshot>(token, `/projects/${snapshot.project.id}/snapshot`)
      setChecks([`Workspace authentication: passed`, `Nodes online: ${current.nodes.filter(n => n.online).length}/${current.nodes.length}`,
        ...current.agents.map(a => `${a.name}: ${a.online ? 'heartbeat present' : 'no recent heartbeat'}; runtime ${a.runtime?.state || 'not configured'}`),
        'Provider login, native MCP attachment and model execution: verify separately using the bounded task below.'].join('\n'))
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <><button className="button secondary" onClick={() => setOpen(true)}>Connection wizard</button>
    {open && <Modal title="Connect and verify an agent" close={() => setOpen(false)}><div className="dialog-form">
      <p>1. Install and sign in to your coding tool on its machine. For managed coding work, install Git and prepare a clone with an initial commit. Commands and provider credentials stay on that machine.</p>
      <form className="dialog-form" onSubmit={generate}>
        <label>Connection mode<select value={mode} onChange={e => setMode(e.target.value)}><option value="managed_cli">Managed CLI — dashboard launch and stop</option><option value="managed_api">Managed API — jobs protocol and cancellation</option><option value="connected">Connected session — start in its own client</option></select></label>
        <label>Tool kind<select value={profile} onChange={e => setProfile(e.target.value)}>{['codex', 'claude', 'opencode', 'cline', 'kiro', 'antigravity', 'agentzero', 'omnirush', 'custom'].map(kind => <option key={kind}>{kind}</option>)}</select></label>
        <label>Repository on the agent machine<input name="repo" placeholder="C:\Projects\my-repo or /home/user/my-repo" required={mode !== 'connected'} /></label>
        {mode === 'managed_cli' && <label>Verified headless command (JSON array)<textarea name="argv" rows={3} placeholder={'["your-tool", "verified-headless-option", "{prompt_file}"]'} required /><small>Use the exact command supported by your installed tool version. JSON preserves Windows paths and spaces. No shell is used.</small></label>}
        {mode === 'managed_api' && <><label>Jobs-protocol URL<input name="url" type="url" required /></label><label>Token environment variable<input name="token_env" placeholder="MY_PROVIDER_TOKEN" pattern="[A-Za-z_][A-Za-z0-9_]*" /></label><p className="form-hint">This requires the AgentVerse jobs protocol, not a generic chat-completions endpoint.</p></>}
        {mode !== 'connected' && <><label>Verified model IDs (comma separated)<input name="models" required /></label><label>Base branch<input name="base" defaultValue="main" required /></label><label className="checkbox-label"><input name="push" type="checkbox" /><span>Allow workers to push their task branches</span></label></>}
        <button className="button secondary" disabled={busy}>Generate node profile</button>
      </form>
      <label>Import or edit node configuration<textarea aria-label="Node configuration" value={config} onChange={e => setConfig(e.target.value)} rows={8} placeholder="Paste an existing configuration, or generate one above" /></label>
      <div className="dialog-actions"><button className="button secondary" disabled={busy || !config} onClick={() => void validateImported()}>Validate configuration</button><button className="button secondary" disabled={!config || config !== validated} onClick={save}>Download configuration</button></div>
      <p>2. Save the file on the agent machine. Add a remote node here, use its invitation token, and run:</p><pre>{'agentverse doctor --config agentverse-node.json\nagentverse node --server ' + location.origin + ' --config agentverse-node.json'}</pre><p className="form-hint">Set AGENTVERSE_NODE_TOKEN on that machine. Then create a teammate and select Configure → runtime → model/settings → Launch. Connected sessions can use the teammate’s connection recipe directly.</p>
      <p>3. Check the connection, then verify real work.</p><button className="button secondary" disabled={busy} onClick={() => void check()}>Check workspace connections</button>{checks && <pre role="status">{checks}</pre>}
      <p>For a bounded acceptance task, ask the agent to create a small text file containing a unique phrase, submit its branch, and have another teammate review it. Confirm the result, model choice and Stop behavior before unattended work.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div></Modal>}
  </>
}
