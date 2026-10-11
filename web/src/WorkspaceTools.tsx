import { useEffect, useState } from 'react'
import { api } from './api'
import Modal from './Dialog'

function download(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

type Diagnostics = { version: string; server_running: boolean; git_detected: boolean; port: number; tools: { kind: string; detected: boolean; note: string }[]; next_steps: string[] }

export default function WorkspaceTools({ token }: { token: string }) {
  const [local, setLocal] = useState(false), [open, setOpen] = useState(false)
  const [report, setReport] = useState<Diagnostics | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [stopping, setStopping] = useState(false)
  useEffect(() => { let alive = true; api<{ local: boolean }>('', '/local/onboarding').then(r => { if (alive) setLocal(r.local) }).catch(() => {}); return () => { alive = false } }, [])
  async function inspect() {
    setOpen(true); setError(''); setBusy(true)
    try { setReport(await api<Diagnostics>(token, '/local/diagnostics')) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function saveBackup() {
    setBusy(true); setError('')
    try {
      const response = await fetch('/api/local/backup', { headers: { Authorization: `Bearer ${token}` } })
      if (!response.ok) throw new Error('Backup failed. Run agentverse backup to see the error.')
      download(`agentverse-backup-${new Date().toISOString().slice(0, 10)}.zip`, await response.blob())
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function stop() {
    setBusy(true); setError('')
    try { await api(token, '/local/stop', 'POST', {}); setStopping(true) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  if (!local) return null
  return <><button className="text-button" onClick={() => void inspect()}>App settings</button>
    {open && <Modal title="App settings & recovery" close={() => setOpen(false)}>
      {stopping ? <p role="status">AgentVerse is stopping. Open its shortcut or run agentverse start to use it again. Your workspace is saved.</p> : <div className="dialog-form">
        <p>Download a backup before moving or updating your workspace. Backups contain credentials and project data; keep them private.</p>
        <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={() => void saveBackup()}>Download workspace backup</button><button className="button secondary" disabled={!report} onClick={() => download('agentverse-diagnostics.json', new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))}>Export diagnostics</button></div>
        {report && <><h3>Installation health</h3><p>Version {report.version} · {report.server_running ? 'Server running' : 'Server unreachable'} · Port {report.port}</p><p>Git: {report.git_detected ? 'detected' : 'install Git for managed coding work'}</p><ul>{report.tools.map(tool => <li key={tool.kind}>{tool.kind}: {tool.detected ? 'detected — verify provider login' : 'not detected on this server'}</li>)}</ul><p className="form-hint">Remote tools are checked on their own nodes, not on this server.</p>{report.next_steps.map(step => <p key={step}>{step}</p>)}<details><summary>Technical diagnostic report</summary><pre className="maintenance-report">{JSON.stringify(report, null, 2)}</pre></details></>}
        <p>Use your installed AgentVerse launcher with these commands:</p><pre>{'agentverse status\nagentverse update\nagentverse rollback\nagentverse restore /path/to/backup.zip\nagentverse autostart\nagentverse autostart --remove'}</pre>
        <p className="form-hint">Stop the app before updating or restoring. Updates keep an earlier application version and a pre-update backup. Use --home when managing a custom workspace.</p>
        <details><summary>Stop this workspace</summary><p>This disconnects everyone using this local server. Managed nodes detect a lost connection and stop workers when their leases expire.</p><button className="button secondary" disabled={busy} onClick={() => void stop()}>Stop AgentVerse</button></details>
        {error && <p className="form-error" role="alert">{error}</p>}
      </div>}
    </Modal>}
  </>
}
