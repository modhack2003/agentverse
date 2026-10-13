import { useEffect, useRef, useState } from 'react'
import { Copy } from 'lucide-react'
import { api } from './api'
import { connectionPrompt } from './connectionPrompt'
import type { AgentOS, PromptMode } from './connectionPrompt'
import type { Agent, Message, Project } from './types'

export default function ConnectionPrompt({ agent, project, agentToken, workspaceToken, copy }: { agent: Agent; project: Project; agentToken: string; workspaceToken: string; copy: (text: string) => void }) {
  const [mode, setMode] = useState<PromptMode>('worker'), [os, setOS] = useState<AgentOS>('windows')
  const [includeToken, setIncludeToken] = useState(false), [status, setStatus] = useState(''), [busy, setBusy] = useState(false)
  const [server, setServer] = useState(location.origin)
  const controller = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  const test = useRef<{ request: string; content: string; phrase: string } | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort() } }, [])
  let endpoint = '', loopback = false
  try {
    const parsed = new URL(server.trim())
    if (['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password && parsed.pathname === '/' && !parsed.search && !parsed.hash) {
      endpoint = parsed.origin
      loopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
    }
  } catch { /* A partially typed URL is not ready to copy. */ }
  const prompt = endpoint ? connectionPrompt(agent, project, endpoint, includeToken ? agentToken : '', mode, os) : ''

  async function checkChat() {
    if (busy) return
    const abort = new AbortController(); controller.current = abort
    setBusy(true); setStatus('Sending an owner DM to this teammate…')
    if (!test.current) {
      const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
      const phrase = `AgentVerse-chat-${id}`
      test.current = { request: id, phrase, content: `Connection verification: please answer this message with the exact phrase ${phrase}. This is a chat check; do not create a task or change files.` }
    }
    const pending = test.current
    const deadline = setTimeout(() => abort.abort('timeout'), 120000)
    try {
      const sent = await api<Message>(workspaceToken, `/projects/${project.id}/messages`, 'POST', { content: pending.content,
        recipient_id: agent.id, intent: 'chat', client_request_id: pending.request }, abort.signal)
      while (!abort.signal.aborted) {
        const rows = await api<Message[]>(workspaceToken, `/projects/${project.id}/messages?recipient_id=${encodeURIComponent(agent.id)}&limit=100`, 'GET', undefined, abort.signal)
        if (abort.signal.aborted) return
        const delivery = rows.find(m => m.id === sent.id)?.deliveries?.find(d => d.agent_id === agent.id)
        if (delivery?.state === 'answered') {
          const reply = rows.find(m => m.id === delivery.reply_id && m.sender_id === agent.id && m.reply_to_id === sent.id)
          setStatus(reply?.content.includes(pending.phrase) ? 'Chat check passed: this teammate answered your unique test message. Provider identity and reply quality still depend on its configured runtime.' : 'A reply arrived, but it did not contain the requested phrase. Inspect the owner DM and the configured model before accepting the test.')
          test.current = null
          return
        }
        if (delivery && ['failed', 'unconfirmed', 'cancelled'].includes(delivery.state)) {
          setStatus(`Chat check ${delivery.state}: ${delivery.error || 'Inspect this message in Team conversation and recover its reply there.'}`)
          test.current = null
          return
        }
        setStatus(delivery?.state === 'working' ? 'The listener is answering your test message…' : 'Your test is queued. Waiting for a persistent chat listener…')
        await new Promise<void>(resolve => {
          const finish = () => { clearTimeout(timer); abort.signal.removeEventListener('abort', finish); resolve() }
          const timer = setTimeout(finish, 1000)
          abort.signal.addEventListener('abort', finish, { once: true })
        })
      }
    } catch (e) {
      if (!abort.signal.aborted) setStatus(`Chat check could not complete: ${(e as Error).message}. Retry uses the same test message if the send response was lost.`)
    } finally {
      clearTimeout(deadline)
      if (mounted.current && abort.signal.aborted && abort.signal.reason === 'timeout') setStatus('No verified reply within two minutes. The test remains in the owner DM; check the listener, provider login and reply status there.')
      if (controller.current === abort) { controller.current = null; if (mounted.current) setBusy(false) }
    }
  }
  return <section className="connection-prompt">
    <h3>Give your agent a connection prompt</h3>
    <p>Copy this into the AI agent on its own machine. It includes the assigned identity, setup steps, persistent listening and a human reply test.</p>
    <label>Workspace URL reachable from the agent<input type="url" value={server} maxLength={2048} onChange={e => setServer(e.target.value)} /></label>
    {!endpoint && <p className="form-error" role="alert">Use an HTTP(S) workspace origin without credentials, a path, query or fragment.</p>}
    {loopback && <p className="form-hint">A localhost address points at the agent’s own computer. For another machine, enter the workspace address that machine can reach.</p>}
    <label>Connection approach<select value={mode} onChange={e => setMode(e.target.value as PromptMode)}><option value="worker">Automatic HTTP worker · recommended</option><option value="mcp">Native MCP · requires an active agent loop</option></select></label>
    <label>Agent operating system<select value={os} onChange={e => setOS(e.target.value as AgentOS)}><option value="windows">Windows / PowerShell</option><option value="posix">macOS / Linux</option></select></label>
    {agentToken ? <label className="checkbox-label"><input type="checkbox" checked={includeToken} onChange={e => setIncludeToken(e.target.checked)} /><span>Include this teammate’s private token in the copied prompt</span></label> : <p>Use the saved agent token on its machine. You can copy this prompt without replacing a working token.</p>}
    {includeToken && <p className="form-hint">Share this credential-bearing prompt only with your own agent. Keep it out of public chats and repositories.</p>}
    <textarea aria-label="Generated connection prompt" rows={12} readOnly value={prompt} spellCheck={false} />
    <button className="button primary" disabled={!endpoint} onClick={() => copy(prompt)}><Copy size={15} />Copy connection prompt</button>
    <h3>Verify a real reply</h3><p>Start the listener, then send a unique chat test. This sends one owner DM and waits up to two minutes for its matching reply.</p>
    <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={() => void checkChat()}>Send chat test</button>{busy && <button className="button secondary" onClick={() => { setStatus('Stopped waiting. The test remains in the owner DM and the agent may still answer it.'); controller.current?.abort() }}>Stop waiting</button>}</div>
    {status && <p role="status" className="form-hint">{status}</p>}
  </section>
}
