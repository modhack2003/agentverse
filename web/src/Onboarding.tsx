import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'

// Consume the capability from the URL before any rendering or network request.
const fragment = new URLSearchParams(location.hash.slice(1))
const initialSetup = fragment.get('setup') || ''
if (initialSetup) history.replaceState(null, '', location.pathname + location.search)

export default function Onboarding({ onLogin }: { onLogin: (token: string) => void }) {
  const [secret, setSecret] = useState(initialSetup)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [mode, setMode] = useState('local'), [remote, setRemote] = useState('')
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    const values = Object.fromEntries(new FormData(event.currentTarget))
    try {
      if (mode === 'remote') {
        const url = new URL(remote)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Enter an HTTP(S) workspace URL without embedded credentials.')
        location.assign(url.origin)
        return
      }
      if (values.password !== values.confirm) throw new Error('Passwords do not match.')
      const result = await api<{ token: string }>(secret, '/local/welcome', 'POST', values)
      setSecret(''); onLogin(result.token)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  if (!secret) return null
  return <main className="login-shell"><section className="login-card"><h1>Welcome to AgentVerse</h1>
    <p>Set up your workspace, then connect your first teammate. Your data stays in the workspace folder selected by the launcher.</p>
    <form className="dialog-form" onSubmit={submit}>
      <label>Where will you work?<select aria-label="Workspace location" value={mode} onChange={e => setMode(e.target.value)}><option value="local">This computer — new workspace</option><option value="remote">An existing workspace on another computer or server</option></select></label>
      {mode === 'remote' ? <label>Workspace URL<input type="url" required value={remote} onChange={e => setRemote(e.target.value)} placeholder="https://your-workspace.example" /></label> : <>
        <label>User ID<input name="username" autoComplete="username" pattern="[A-Za-z0-9_.@-]+" maxLength={100} required /></label>
        <label>Password<input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={256} required /></label>
        <label>Confirm password<input name="confirm" type="password" autoComplete="new-password" minLength={12} required /></label>
        <label>First project name (optional)<input name="project_name" maxLength={100} placeholder="My first project" /></label>
        <label>Project goal<textarea name="goal" maxLength={20000} rows={2} /></label>
        <p className="form-hint">Passwords are saved as a salted hash. Coding tools and provider logins are configured separately on the machine running each agent. Use the connection wizard after setup.</p>
      </>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button primary full" disabled={busy}>{busy ? 'Setting up…' : mode === 'remote' ? 'Open existing workspace' : 'Finish setup'}</button>
    </form></section></main>
}
export const hasSetupLink = Boolean(initialSetup)
