import { useEffect, useState } from 'react'
import { Check, HelpCircle, Plus, TriangleAlert } from 'lucide-react'
import { api } from './api'
import type { AgentIssue, HelpRequest, Snapshot } from './types'

export default function CoordinationHistory({ snapshot, token, busy, resolve, ask }: {
  snapshot: Snapshot; token: string; busy: boolean; resolve: (id: string) => Promise<void>; ask: () => void
}) {
  return <div className="peer-coordination">
    <History key={`${snapshot.project.id}/issues`} kind="issues" snapshot={snapshot} token={token} busy={busy} resolve={resolve} ask={ask} />
    <History key={`${snapshot.project.id}/help`} kind="help" snapshot={snapshot} token={token} busy={busy} resolve={resolve} ask={ask} />
  </div>
}

function History({ kind, snapshot, token, busy, resolve, ask }: {
  kind: 'issues' | 'help'; snapshot: Snapshot; token: string; busy: boolean; resolve: (id: string) => Promise<void>; ask: () => void
}) {
  const [state, setState] = useState<'active' | 'history' | 'all'>('active'), [pages, setPages] = useState(1)
  const [rows, setRows] = useState<(AgentIssue | HelpRequest)[]>([]), [more, setMore] = useState(false)
  const [loading, setLoading] = useState(false), [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    setLoading(true); setError('')
    async function load() {
      const result: (AgentIssue | HelpRequest)[] = []
      let before = '', hasMore = false
      for (let page = 0; page < pages; page++) {
        const batch = await api<(AgentIssue | HelpRequest)[]>(token, `/projects/${snapshot.project.id}/${kind}?state=${state}&limit=100${before ? `&before=${encodeURIComponent(before)}` : ''}`)
        if (cancelled) return
        result.push(...batch); hasMore = batch.length === 100
        if (!hasMore) break
        before = batch[batch.length - 1].id
      }
      if (!cancelled) { setRows(result); setMore(hasMore) }
    }
    void load().catch(e => { if (!cancelled) setError(e.message) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, snapshot.project.id, snapshot.cursor, kind, state, pages])
  const name = (id: string | null) => snapshot.agents.find(agent => agent.id === id)?.name || 'Teammate'
  return <section className="panel coordination-panel">
    <div className="panel-heading"><h2>{kind === 'issues' ? <><TriangleAlert size={16} />Agent problems</> : <><HelpCircle size={16} />Teammates helping teammates</>}</h2>
      {kind === 'help' && <button className="text-button" onClick={ask}>Ask for help <Plus size={13} /></button>}
    </div>
    <label className="channel-picker">{kind === 'issues' ? 'Problem history' : 'Help history'}<select aria-label={kind === 'issues' ? 'Problem history' : 'Help history'} value={state} onChange={event => { setState(event.target.value as typeof state); setPages(1); setRows([]) }}>
      <option value="active">{kind === 'issues' ? 'Unresolved problems' : 'Open and in-progress requests'}</option>
      <option value="history">{kind === 'issues' ? 'Resolved history' : 'Answered history'}</option><option value="all">All history</option>
    </select></label>
    {rows.map(row => 'question' in row ? <div className="coordination-item" key={row.id}><strong>{row.question}</strong><small>{row.capability || 'General help'} · {row.state.replace('_', ' ')}{row.assignee_id ? ` · ${name(row.assignee_id)}` : row.recipient_id ? ` · suggested: ${name(row.recipient_id)}` : ' · open to a matching peer'}</small>{row.answer && <p>{row.answer}</p>}</div>
      : <div className="coordination-item" key={row.id}><strong>{row.title}</strong><small>{name(row.agent_id)} · {row.severity}{row.resolved ? ' · resolved' : ''}</small><p>{row.detail}</p>{!row.resolved && (snapshot.identity.admin || snapshot.identity.actor_id === row.agent_id) && <button className="text-button" disabled={busy} onClick={() => void resolve(row.id)}>Mark resolved <Check size={13} /></button>}</div>)}
    {!loading && !rows.length && !error && <p className="coordination-empty">{kind === 'issues' ? 'No problems in this view.' : 'No help requests in this view. Ask for a capability and a matching teammate can help.'}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}{loading && <p className="subtle">Loading history…</p>}
    {more && <button className="text-button" disabled={loading} onClick={() => setPages(current => current + 1)}>{kind === 'issues' ? 'Load more problems' : 'Load more help requests'}</button>}
  </section>
}
