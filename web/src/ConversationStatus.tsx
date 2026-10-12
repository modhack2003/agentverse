import { useState } from 'react'
import { api } from './api'
import Modal from './Dialog'
import type { Agent, ChatDelivery, Message, Snapshot } from './types'

const readiness = { not_listening: 'Chat listener not running', offline: 'Chat listener offline', listening: 'Listening · reply not yet verified', busy: 'Answering a conversation', verified: 'Chat reply verified', error: 'Chat reply failed', unconfirmed: 'Chat reply needs recovery' }

export function ConversationReadiness({ agent }: { agent: Agent }) {
  const state = agent.conversation?.state || 'not_listening'
  return <p className={`chat-readiness ${state}`} role="status">{readiness[state]}{agent.conversation?.pending ? ` · ${agent.conversation.pending} queued` : ''}</p>
}

export function ConversationDelivery({ message, snapshot, token, reload }: { message: Message; snapshot: Snapshot; token: string; reload: () => Promise<void> }) {
  const [recover, setRecover] = useState<ChatDelivery | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  async function retry(delivery: ChatDelivery, confirmed = false) {
    if (busy) return
    setBusy(true); setError('')
    try {
      await api(token, `/projects/${snapshot.project.id}/messages/${message.id}/retry/${delivery.agent_id}`, 'POST', { confirmed_stopped: confirmed })
      setRecover(null)
      await reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <div className="chat-deliveries">
    {message.deliveries?.map(delivery => {
      const agent = snapshot.agents.find(a => a.id === delivery.agent_id)
      const listening = agent?.conversation && !['not_listening', 'offline'].includes(agent.conversation.state)
      const label = delivery.state === 'queued' ? listening ? 'Reply queued' : 'Waiting for a chat listener' : ({ working: 'Answering', answered: 'Replied', failed: 'Reply failed', unconfirmed: 'Previous reply needs recovery', cancelled: 'Access revoked' } as const)[delivery.state]
      return <div className={`chat-delivery ${delivery.state}`} key={delivery.agent_id}>
        <span>{agent?.name || 'Teammate'} · {label}</span>
        {delivery.error && <span className="subtle">{delivery.error}</span>}
        {snapshot.identity.admin && ['failed', 'unconfirmed'].includes(delivery.state) && <button className="text-button" disabled={busy} aria-label={`Retry reply from ${agent?.name || 'teammate'}`} onClick={() => delivery.state === 'unconfirmed' ? setRecover(delivery) : void retry(delivery)}>Retry reply</button>}
      </div>
    })}
    {error && <p className="form-error" role="alert">{error}</p>}
    {recover && <Modal title="Recover the previous reply" close={() => setRecover(null)}><p>Stop the previous agent session first. Retrying while it is still running could start a second invocation.</p><div className="dialog-actions"><button className="button secondary" onClick={() => setRecover(null)}>Cancel</button><button className="button primary" disabled={busy} onClick={() => void retry(recover, true)}>The previous session has stopped · retry</button></div>{error && <p className="form-error" role="alert">{error}</p>}</Modal>}
  </div>
}
