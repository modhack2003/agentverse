import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  Activity, ArrowDownToLine, ArrowRight, ArrowUpRight, BookOpen, Bot, Check, CheckCheck,
  ChevronDown, ChevronRight, CircleDot, Code2, GitBranch, GitPullRequest,
  Globe, Hash, LayoutDashboard, ListTodo, LoaderCircle, LockKeyhole, LogOut, Menu,
  MessageSquare, Pause, Play, Plus, Radio, Search, Send, Sparkles,
  Terminal, Users, Zap,
} from 'lucide-react'
import { api } from './api'
import Modal from './Dialog'
import RemoteAgents from './RemoteAgents'
import ConnectionDetails from './ConnectionDetails'
import { ThemePicker } from './Themes'
import { readStorage, writeStorage, removeStorage } from './storage'
import type { Agent, Memory, Project, Snapshot, Task } from './types'

const sections = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'tasks', label: 'Task board', icon: ListTodo },
  { id: 'chat', label: 'Team conversations', icon: MessageSquare },
  { id: 'memory', label: 'Shared memory', icon: BookOpen },
  { id: 'reviews', label: 'Code reviews', icon: GitPullRequest },
  { id: 'agents', label: 'Agents & connections', icon: Users },
]
const statuses = [
  { id: 'backlog', label: 'Ready to pick up', color: 'muted' },
  { id: 'in_progress', label: 'In progress', color: 'purple' },
  { id: 'review', label: 'Peer review', color: 'amber' },
  { id: 'done', label: 'Completed', color: 'green' },
] as const
const agentTools = [
  { value: 'opencode', label: 'OpenCode' },
  { value: 'omnirush', label: 'Omnirush' },
  { value: 'cline', label: 'Cline' },
  { value: 'claude', label: 'Claude' },
  { value: 'codex', label: 'Codex' },
  { value: 'kiro', label: 'Kiro' },
  { value: 'antigravity', label: 'Antigravity' },
  { value: 'agentzero', label: 'Agent Zero' },
  { value: 'custom', label: 'Other / custom tool' },
]
type Dialog = 'project' | 'task' | 'agent' | 'memory' | 'detail' | 'connect' | null

function Brand({ small = false }: { small?: boolean }) {
  return <div className={`brand ${small ? 'small' : ''}`}><span className="brand-mark"><i /><i /><i /><i /></span><span>Agent<span className="brand-light">Verse</span></span></div>
}
function KindIcon({ kind, size = 18 }: { kind: string; size?: number }) {
  const Icon = ({ opencode: Terminal, cline: Code2, omnirush: Zap, agentzero: CircleDot } as Record<string, typeof Bot>)[kind.toLowerCase().replace(/[ -]/g, '')] || Bot
  return <Icon size={size} />
}
function Avatar({ agent, human = false, small = false }: { agent?: Agent; human?: boolean; small?: boolean }) {
  return <span className={`avatar ${agent?.kind.toLowerCase().replace(/[ -]/g, '') || 'custom'} ${human ? 'human' : ''} ${small ? 'compact' : ''}`}>
    {human ? 'Y' : <KindIcon kind={agent?.kind || 'custom'} size={small ? 14 : 19} />}
  </span>
}
function Empty({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="empty-state">{icon}<h3>{title}</h3><p>{children}</p></div>
}
function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState('kali'), [password, setPassword] = useState('kali')
  const [token, setToken] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      if (username || password) {
        const result = await api<{ token: string }>('', '/login', 'POST', { username, password })
        onLogin(result.token)
      } else {
        await api(token, '/me'); onLogin(token)
      }
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <main className="login-shell"><div className="login-appearance"><ThemePicker /></div><div className="login-decoration"><span /><span /><span /></div>
    <div className="login-card"><Brand /><span className="eyebrow"><span className="status-dot green" /> A SHARED HOME FOR YOUR AGENTS</span>
      <h1>Great things happen<br />when agents <em>work together.</em></h1><p className="login-description">Bring your favorite agents into one workspace.<br />One goal. Shared context. A team that moves together.</p>
      <div className="login-agent-row">{['opencode', 'cline', 'omnirush', 'agentzero'].map(kind => <span key={kind} className={`avatar ${kind}`}><KindIcon kind={kind} /></span>)}<span>+ any agent</span></div>
      <form onSubmit={submit}><label htmlFor="user-id">User ID</label><div className="token-input"><LockKeyhole size={17} /><input id="user-id" type="text" autoComplete="username" placeholder="User ID" value={username} onChange={e => setUsername(e.target.value)} required /></div>
        <label htmlFor="login-password">Password</label><div className="token-input"><LockKeyhole size={17} /><input id="login-password" type="password" autoComplete="current-password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required /></div>
        <label className="legacy-login" htmlFor="access-token">Legacy access token <small>(agents and existing sessions)</small></label><div className="token-input"><LockKeyhole size={17} /><input id="access-token" aria-label="Workspace access token" type="password" autoComplete="off" placeholder="Optional bearer token" value={token} onChange={e => setToken(e.target.value)} /></div>
        {error && <p className="form-error" role="alert">{error}</p>}<button className="button primary full" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <>Enter your workspace <ArrowRight size={17} /></>}</button>
      </form><p className="login-footer"><Globe size={13} /> Self-hosted. Agent-neutral. Yours.</p>
    </div></main>
}

function TaskCard({ task, agents, onClick }: { task: Task; agents: Agent[]; onClick: () => void }) {
  const assignee = agents.find(a => a.id === task.assignee_id)
  return <button className={`task-card ${task.status === 'done' ? 'finished' : ''}`} onClick={onClick}>
    <div className="task-meta"><span className="task-number">{task.id.slice(-5).toUpperCase()}</span><span className={`priority ${task.priority}`}>{task.priority}</span></div>
    <h3>{task.title}</h3><p>{task.description || 'Ready for a teammate to pick up.'}</p>
    <div className="task-tags">{task.kind === 'planning' && <span><Sparkles size={11} /> planning</span>}{task.blocked && <span className="blocked"><LockKeyhole size={11} /> waiting on dependencies</span>}{task.branch && <span><GitBranch size={11} />{task.integration_sha ? 'merged' : 'branch'}</span>}</div>
    <div className="task-bottom">{assignee ? <span className="task-owner"><Avatar agent={assignee} small />{assignee.name}</span> : <span className="unassigned"><Users size={13} /> Open to the team</span>}<span className="task-comments">{task.dependencies.length > 0 && <><GitBranch size={12} /> {task.dependencies.length}</>}{task.status === 'done' && <CheckCheck size={16} />}</span></div>
  </button>
}

function Chat({ snapshot, token, reload, full = false, initialRecipient = '' }: { snapshot: Snapshot; token: string; reload: () => Promise<void>; full?: boolean; initialRecipient?: string }) {
  const [content, setContent] = useState(''), [target, setTarget] = useState(initialRecipient || '#general'), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { if (initialRecipient) setTarget(initialRecipient) }, [initialRecipient])
  const dm = !target.startsWith('#')
  const messages = snapshot.messages.filter(m => dm ? !!m.recipient_id && ((m.sender_id === snapshot.identity.actor_id && m.recipient_id === target) || (m.sender_id === target && m.recipient_id === snapshot.identity.actor_id)) : !m.recipient_id && m.channel === target.slice(1))
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [messages.length, target])
  async function send(e: FormEvent) {
    e.preventDefault(); if (!content.trim() || busy) return; setBusy(true); setError('')
    try { await api(token, `/projects/${snapshot.project.id}/messages`, 'POST', { content: content.trim(), channel: dm ? 'general' : target.slice(1), recipient_id: dm ? target : null }); setContent(''); await reload() }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <section className={`panel chat-panel ${full ? 'full-chat' : ''}`}>
    <div className="panel-heading"><div className="heading-icon"><MessageSquare size={17} /><h2>Team conversation</h2></div><span className="live-label"><span className="status-dot green" /> Shared context</span></div>
    <div className="channel-picker"><Hash size={16} /><select aria-label="Conversation" value={target} onChange={e => setTarget(e.target.value)}><optgroup label="Team channels"><option value="#general">general</option><option value="#engineering">engineering</option><option value="#reviews">reviews</option></optgroup><optgroup label="Direct messages">{snapshot.agents.filter(a => a.id !== snapshot.identity.actor_id).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}{!snapshot.identity.admin && <option value="human">Workspace owner</option>}</optgroup></select>{dm && <LockKeyhole size={13} />}</div>
    <div className="chat-messages">{messages.length === 0 && <Empty icon={<MessageSquare size={25} />} title={dm ? 'A conversation just for you two' : 'Start the conversation'}>Ideas, questions, and handoffs belong here.</Empty>}
      {messages.map(message => {
        const agent = snapshot.agents.find(a => a.id === message.sender_id)
        return <div className="message" key={message.id}><Avatar agent={agent} human={message.sender_id === 'human'} /><div className="message-body"><div className="message-head"><strong>{message.sender_id === 'human' ? 'You · workspace owner' : agent?.name || 'Teammate'}</strong><time>{new Date(message.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p>{message.content}</p>{message.task_id && <span className="message-task"><ListTodo size={11} /> Linked to {snapshot.tasks.find(t => t.id === message.task_id)?.title || 'a task'}</span>}</div></div>
      })}<div ref={end} /></div>
    <form className="chat-compose" onSubmit={send}><textarea aria-label="Message" placeholder={dm ? 'Send a private message…' : 'Talk to your team…'} value={content} onChange={e => setContent(e.target.value)} rows={2} maxLength={20000} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(e) } }} /><div><span>Enter to send · Shift + Enter for a new line</span><button className="send-button" aria-label="Send message" disabled={busy || !content.trim()}><Send size={15} /></button></div>{error && <p className="form-error" role="alert">{error}</p>}</form>
  </section>
}

export default function App() {
  const [token, setToken] = useState(() => readStorage('agentverse-token', true) || readStorage('agentcommons-token', true) || '')
  const [projects, setProjects] = useState<Project[]>([]), [projectId, setProjectId] = useState('')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null), [section, setSection] = useState('overview')
  const [dialog, setDialog] = useState<Dialog>(null), [task, setTask] = useState<Task | null>(null), [memory, setMemory] = useState<Memory | null>(null)
  const [connection, setConnection] = useState<{ agent: Agent; token: string } | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [formError, setFormError] = useState(''), [toast, setToast] = useState('')
  const [live, setLive] = useState(false), [mobileNav, setMobileNav] = useState(false), [search, setSearch] = useState(''), [dmRecipient, setDmRecipient] = useState('')
  const [memorySearch, setMemorySearch] = useState('')
  const [admin, setAdmin] = useState(false)
  const [agentTool, setAgentTool] = useState('opencode')
  const activeProject = useRef(projectId); activeProject.current = projectId
  const close = useCallback(() => { setDialog(null); setFormError(''); setConnection(null) }, [])

  const loadProjects = useCallback(async () => {
    const result = await api<Project[]>(token, '/projects'); setProjects(result)
    setProjectId(current => result.some(p => p.id === current) ? current : result[0]?.id || '')
  }, [token])
  const reload = useCallback(async () => {
    if (!projectId) return
    const result = await api<Snapshot>(token, `/projects/${projectId}/snapshot`)
    if (activeProject.current === projectId) { setSnapshot(result); setError('') }
  }, [token, projectId])

  useEffect(() => {
    if (!token) return
    let alive = true
    api<{ admin: boolean }>(token, '/me').then(me => { if (alive) setAdmin(me.admin) }).catch(() => {})
    loadProjects().catch(e => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [token, loadProjects])
  useEffect(() => {
    if (!projectId || !token) return
    setSnapshot(null); setLive(false)
    let stopped = false, socket: WebSocket | undefined, reconnect: ReturnType<typeof setTimeout> | undefined
    const refresh = () => reload().catch(e => { if (!stopped) setError(e.message) })
    async function connect() {
      try {
        const state = await api<Snapshot>(token, `/projects/${projectId}/snapshot`)
        if (stopped) return
        setSnapshot(state)
        const { ticket } = await api<{ ticket: string }>(token, `/realtime-ticket?project_id=${projectId}`, 'POST')
        if (stopped) return
        const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
        socket = new WebSocket(`${protocol}://${location.host}/api/live?ticket=${ticket}&after=${state.cursor}`)
        socket.onopen = () => { if (!stopped) setLive(true) }
        socket.onmessage = event => { const data = JSON.parse(event.data); if (data.type === 'events' && !stopped) void refresh() }
        socket.onclose = () => { if (!stopped) { setLive(false); reconnect = setTimeout(connect, 3000) } }
      } catch (e) { if (!stopped) { setError((e as Error).message); reconnect = setTimeout(connect, 5000) } }
    }
    void connect()
    const polling = setInterval(refresh, 15000)
    return () => { stopped = true; socket?.close(); clearInterval(polling); clearTimeout(reconnect) }
  }, [token, projectId, reload])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 3500); return () => clearTimeout(timer) }, [toast])
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); if (projectId && !document.querySelector('[role="dialog"]')) { setFormError(''); setDialog('task') } } }
    document.addEventListener('keydown', handler); return () => document.removeEventListener('keydown', handler)
  }, [projectId])

  function login(value: string) { writeStorage('agentverse-token', value, true); removeStorage('agentcommons-token', true); setToken(value); setError('') }
  function logout() { removeStorage('agentverse-token', true); removeStorage('agentcommons-token', true); setToken(''); setProjects([]); setSnapshot(null); setProjectId('') }
  function open(mode: Dialog) { setFormError(''); if (mode === 'agent') setAgentTool('opencode'); setDialog(mode) }
  function detail(value: Task) { setTask(value); open('detail') }
  async function mutate(path: string, body?: unknown, method = 'POST') {
    setBusy(true); setFormError('')
    try { const result = await api(token, path, method, body); await reload().catch(() => setError('Saved successfully; workspace refresh failed. Live updates will retry.')); return result }
    catch (e) { setFormError((e as Error).message); throw e } finally { setBusy(false) }
  }
  async function submitForm(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = new FormData(e.currentTarget)
    const field = (name: string) => String(form.get(name) || '').trim()
    try {
      if (dialog === 'project') {
        const result = await mutate('/projects', { name: field('name'), goal: field('goal'), repo_url: field('repo_url'), auto_plan: form.has('auto_plan') }) as Project
        await loadProjects(); setProjectId(result.id); setSection('overview'); setToast('Project created. Your team can start planning.'); close()
      } else if (dialog === 'task') {
        await mutate(`/projects/${projectId}/tasks`, { title: field('title'), description: field('description'), priority: field('priority'), dependencies: form.getAll('dependencies'), required_capabilities: field('required_capabilities').split(',').map(s => s.trim()).filter(Boolean) }); setToast('Task added to the team board.'); close()
      } else if (dialog === 'agent') {
        const result = await mutate(`/projects/${projectId}/agents`, { name: field('name'), kind: agentTool === 'custom' ? field('custom_kind') : agentTool, description: field('description'), limitations: field('limitations').split('\n').map(s => s.trim()).filter(Boolean), capabilities: field('capabilities').split(',').map(s => s.trim()).filter(Boolean) }) as { agent: Agent; token: string }
        setConnection(result); open('connect')
      } else if (dialog === 'memory') {
        await mutate(`/projects/${projectId}/memories${memory ? `/${memory.id}` : ''}`, { title: field('title'), content: field('content'), tags: field('tags').split(',').map(s => s.trim()).filter(Boolean), expected_version: memory?.version }, memory ? 'PUT' : 'POST'); setToast('Shared memory saved.'); close()
      }
    } catch { /* Form error is presented in the dialog. */ }
  }
  async function togglePause() {
    try { await mutate(`/projects/${projectId}`, { status: snapshot?.project.status === 'paused' ? 'active' : 'paused' }, 'PATCH'); await loadProjects() } catch { setError('Could not change the project status.') }
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setToast('Copied to clipboard.') } catch { setFormError('Clipboard access unavailable. Select and copy the text below.') }
  }

  if (!token) return <Login onLogin={login} />
  const agents = snapshot?.agents || [], tasks = snapshot?.tasks || []
  const online = agents.filter(a => a.online).length, done = tasks.filter(t => t.status === 'done').length
  const working = tasks.filter(t => t.status === 'in_progress').length, inReview = tasks.filter(t => t.status === 'review').length
  const filtered = tasks.filter(t => `${t.title} ${t.description}`.toLowerCase().includes(search.toLowerCase()))
  const project = snapshot?.project || projects.find(p => p.id === projectId)
  const selectedTask = tasks.find(t => t.id === task?.id) || task
  const actorName = (id: string) => id === 'human' ? 'You' : agents.find(a => a.id === id)?.name || snapshot?.nodes.find(node => node.id === id)?.name || 'Teammate'

  return <div className="app-shell">
    {mobileNav && <div className="nav-scrim" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? 'open' : ''}`}><Brand />
      <div className="workspace-select"><span className="workspace-avatar">AV</span><div><strong>Your workspace</strong><span>Independent agents. Shared goals.</span></div><ChevronDown size={14} /></div>
      <div className="sidebar-label">WORKSPACE</div>
      <nav>{sections.map(item => <button key={item.id} className={`nav-item ${section === item.id ? 'selected' : ''}`} onClick={() => { setSection(item.id); setMobileNav(false) }}><item.icon size={18} /><span>{item.label}</span>{item.id === 'reviews' && inReview > 0 && <span className="nav-count">{inReview}</span>}</button>)}</nav>
      <div className="sidebar-label projects-label">PROJECTS {admin && <button className="icon-button" aria-label="Create project" onClick={() => open('project')}><Plus size={15} /></button>}</div>
      <div className="project-list">{projects.map(p => <button key={p.id} className={`project-item ${projectId === p.id ? 'selected' : ''}`} onClick={() => { setProjectId(p.id); setMobileNav(false) }}><span className={`status-dot ${p.status === 'active' ? 'purple' : 'muted'}`} /><span>{p.name}</span>{projectId === p.id && <ChevronRight size={13} />}</button>)}{projects.length === 0 && <span className="sidebar-empty">Your next big idea goes here.</span>}</div>
      <div className="sidebar-bottom"><div className="team-principle"><span><Sparkles size={18} /></span><strong>Better, together.</strong><p>Every agent has a voice.<br />Every project has a team.</p></div><button className="profile-button" onClick={logout}><span className="profile-avatar">{admin ? 'Y' : 'A'}</span><span><strong>{admin ? 'Workspace owner' : 'Agent session'}</strong><small>Connected remotely</small></span><LogOut size={16} /></button></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumbs"><button className="icon-button mobile-menu" onClick={() => setMobileNav(!mobileNav)} aria-label="Open navigation"><Menu size={20} /></button><span>Workspace</span><ChevronRight size={14} /><strong>{project?.name || 'Getting started'}</strong></div><div className="topbar-actions"><span className={`connection-state ${live ? 'connected' : ''}`}><span className={`status-dot ${live ? 'green' : 'amber'}`} />{live ? 'Live workspace' : projectId ? 'Connecting…' : 'Ready to connect'}</span><ThemePicker /><a href="https://github.com/modhack2003/agentverse" target="_blank" rel="noreferrer" className="docs-link">Documentation <ArrowUpRight size={13} /></a><span className="top-avatar">{admin ? 'Y' : 'A'}</span></div></header>
      <main className="main-content">
        {error && <div className="error-banner" role="alert">{error}<button onClick={logout}>Reconnect</button></div>}
        <div className="page-heading"><div><div className="eyebrow">YOUR AGENTS. ONE COMMON GROUND.</div><h1>{section === 'overview' ? 'Your team, in sync.' : sections.find(s => s.id === section)?.label}</h1><p>{({ overview: 'A little coordination. A lot of possibility.', tasks: 'Clear ownership. Shared progress. Nothing lost between agents.', chat: 'Ideas, questions, and handoffs — all in one conversation.', memory: 'The context your whole team can build on.', reviews: 'A second set of eyes, from an equal teammate.', agents: 'Different tools. Different strengths. One connected team.' } as Record<string, string>)[section]}</p></div><div className="page-actions">{admin && project && <button className="button secondary pause-button" onClick={() => void togglePause()} disabled={busy}>{project.status === 'paused' ? <Play size={15} /> : <Pause size={15} />}{project.status === 'paused' ? 'Resume' : 'Pause'}</button>}{project && <button className="button primary" onClick={() => { if (section === 'memory') { setMemory(null); open('memory') } else if (section === 'agents') open('agent'); else open('task') }} disabled={section === 'agents' && !admin}><Plus size={16} />{section === 'memory' ? 'Add memory' : section === 'agents' ? 'Connect agent' : 'New task'}</button>}</div></div>
        {!projectId && <section className="welcome-panel"><div className="welcome-symbol"><Sparkles size={40} /></div><span className="eyebrow">A NEW KIND OF TEAMWORK</span><h2>One project. Unlimited perspectives.</h2><p>Create a project, share the goal, and connect your agents.<br />They’ll plan, pick up work, and help each other move it forward.</p>{admin && <button className="button primary" onClick={() => open('project')}><Plus size={17} /> Create your first project</button>}<div className="welcome-capabilities"><span><MessageSquare size={18} /> Natural conversations</span><span><GitBranch size={18} /> Parallel work</span><span><BookOpen size={18} /> Shared memory</span></div></section>}
        {projectId && !snapshot && !error && <div className="loading-state"><LoaderCircle size={25} className="spin" /> Bringing your workspace together…</div>}
        {snapshot && <>
          {project?.status === 'paused' && <div className="pause-banner"><Pause size={16} /> This project is paused. Agents will wait before claiming or submitting new work.</div>}
          {section === 'overview' && <>
            <section className="objective"><div className="objective-icon"><Sparkles size={22} /></div><div className="objective-text"><span className="eyebrow">THE COMMON GOAL</span><h2>{snapshot.project.goal}</h2><div>{snapshot.project.repo_url ? <span><GitBranch size={13} /> {snapshot.project.repo_url}</span> : <span><Globe size={13} /> Remote collaborative workspace</span>}<span className="objective-divider" /><span><Users size={13} /> Peer-to-peer team</span></div></div><span className={`badge ${snapshot.project.status === 'active' ? 'green' : 'amber'}`}><span className={`status-dot ${snapshot.project.status === 'active' ? 'green' : 'amber'}`} />{snapshot.project.status === 'active' ? 'Active project' : 'Paused'}</span></section>
            <div className="stats-grid">{[
              { label: 'Agents online', value: online, total: `${agents.length} connected to this project`, icon: Radio, color: 'green' },
              { label: 'Work in motion', value: working, total: `${tasks.filter(t => t.status === 'backlog').length} tasks ready in the queue`, icon: Zap, color: 'purple' },
              { label: 'Awaiting a teammate', value: inReview, total: 'Independent peer reviews', icon: GitPullRequest, color: 'amber' },
              { label: 'Tasks completed', value: done, total: tasks.length ? `${Math.round(done / tasks.length * 100)}% of the current plan` : 'Every small step counts', icon: CheckCheck, color: 'blue' },
            ].map(stat => <div className="stat-card" key={stat.label}><div><span>{stat.label}</span><stat.icon className={`text-${stat.color}`} size={17} /></div><strong>{stat.value.toString().padStart(2, '0')}</strong><small>{stat.total}</small>{stat.label === 'Tasks completed' && <div className="progress-track"><i style={{ width: `${tasks.length ? done / tasks.length * 100 : 0}%` }} /></div>}</div>)}</div>
            <div className="overview-grid"><div className="overview-left"><section className="panel team-panel"><div className="panel-heading"><div className="heading-icon"><Users size={17} /><h2>The team</h2><span className="count-pill">{agents.length}</span></div>{admin && <button className="text-button" onClick={() => open('agent')}>Connect agent <Plus size={14} /></button>}</div>{agents.length ? <div className="team-strip">{agents.map(agent => <button className="team-member" key={agent.id} onClick={() => { setDmRecipient(agent.id); setSection('chat') }}><div className="team-member-avatar"><Avatar agent={agent} /><span className={`status-dot ${agent.online ? 'green' : 'muted'}`} /></div><strong>{agent.name}</strong><span>{agent.online ? agent.status === 'working' ? 'Working on a task' : 'Ready to help' : 'Waiting to connect'}</span></button>)}</div> : <Empty icon={<Bot size={25} />} title="Your teammates are one connection away">Connect an agent to begin automatic planning and collaboration.</Empty>}</section>
              <section className="work-section"><div className="section-heading"><div><h2>Work in motion</h2><span>The next steps toward your common goal</span></div><button className="text-button" onClick={() => setSection('tasks')}>View board <ArrowRight size={14} /></button></div><div className="mini-board">{statuses.slice(0, 3).map(status => <div className="mini-column" key={status.id}><div className="column-title"><span className={`status-dot ${status.color}`} /><h3>{status.label}</h3><span>{tasks.filter(t => t.status === status.id).length}</span></div>{tasks.filter(t => t.status === status.id).slice(0, 2).map(t => <TaskCard key={t.id} task={t} agents={agents} onClick={() => detail(t)} />)}{!tasks.some(t => t.status === status.id) && <div className="empty-column">{status.id === 'backlog' ? 'Room for the next idea' : status.id === 'in_progress' ? 'Ready when the team is' : 'Good work deserves a review'}</div>}</div>)}</div></section>
              <section className="panel activity-panel"><div className="panel-heading"><div className="heading-icon"><Activity size={17} /><h2>Around the workspace</h2></div><span className="subtle">Latest activity</span></div><div className="activity-list">{snapshot.events.slice(-5).reverse().map(event => <div className="activity-item" key={event.id}><span className="activity-icon">{event.kind.startsWith('message') ? <MessageSquare size={14} /> : event.kind.startsWith('memory') ? <BookOpen size={14} /> : <CircleDot size={14} />}</span><div><strong>{actorName(event.actor_id)}</strong> <span>{event.detail}</span></div><time>{new Date(event.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>)}</div></section>
            </div><Chat snapshot={snapshot} token={token} reload={reload} /></div>
          </>}
          {section === 'tasks' && <><div className="board-toolbar"><span><ListTodo size={16} /> {tasks.length} tasks across the team</span><div className="search-field"><Search size={15} /><input aria-label="Search tasks" placeholder="Find a task…" value={search} onChange={e => setSearch(e.target.value)} /></div></div><div className="task-board">{statuses.map(status => <section className="board-column" key={status.id}><div className="column-title"><span className={`status-dot ${status.color}`} /><h3>{status.label}</h3><span>{filtered.filter(t => t.status === status.id).length}</span><button className="icon-button" aria-label={`Add task to ${status.label}`} onClick={() => open('task')}><Plus size={14} /></button></div>{filtered.filter(t => t.status === status.id).map(t => <TaskCard key={t.id} task={t} agents={agents} onClick={() => detail(t)} />)}{!filtered.some(t => t.status === status.id) && <div className="empty-column">Nothing here yet. Progress will show up as your team works.</div>}</section>)}</div></>}
          {section === 'chat' && <Chat snapshot={snapshot} token={token} reload={reload} full initialRecipient={dmRecipient} />}
          {section === 'memory' && <><div className="board-toolbar"><span><BookOpen size={16} />{snapshot.memories.length} shared notes</span><div className="search-field"><Search size={15} /><input aria-label="Search memory" placeholder="Search notes and tags…" value={memorySearch} onChange={e => setMemorySearch(e.target.value)} /></div></div><div className="memory-grid">{snapshot.memories.filter(note => `${note.title} ${note.content} ${note.tags.join(' ')}`.toLowerCase().includes(memorySearch.toLowerCase())).map(note => <button key={note.id} className="panel memory-card" onClick={() => { setMemory(note); open('memory') }}><div className="memory-top"><span className="memory-icon"><BookOpen size={19} /></span><span>v{note.version}</span></div><h2>{note.title}</h2><p>{note.content}</p><div className="memory-tags">{note.tags.map(tag => <span key={tag}>{tag}</span>)}</div><div className="memory-footer">{actorName(note.author_id)}<span>{new Date(note.updated_at * 1000).toLocaleDateString()}</span></div></button>)}{snapshot.memories.length === 0 && <div className="panel spanning"><Empty icon={<BookOpen size={30} />} title="Build a shared understanding">Save decisions, architecture notes, and handoffs. Your agents can read and update them through MCP or the API.</Empty></div>}{snapshot.memories.length > 0 && !snapshot.memories.some(note => `${note.title} ${note.content} ${note.tags.join(' ')}`.toLowerCase().includes(memorySearch.toLowerCase())) && <div className="panel spanning"><Empty icon={<Search size={28} />} title="No matching memories">Try a different phrase, title, or tag.</Empty></div>}</div></>}
          {section === 'reviews' && <div className="review-list">{tasks.filter(t => t.status === 'review').map(t => <button className="panel review-card" key={t.id} onClick={() => detail(t)}><span className="review-icon"><GitPullRequest size={23} /></span><div><span className="eyebrow">READY FOR A SECOND SET OF EYES</span><h2>{t.title}</h2><p>{t.summary}</p><span className="branch-label"><GitBranch size={13} />{t.branch} · {t.commit_sha?.slice(0, 8)}</span></div><span className="badge amber">{t.reviewer_id ? `Reviewing: ${actorName(t.reviewer_id)}` : 'Waiting for a peer'}</span><ChevronRight size={20} /></button>)}{inReview === 0 && <div className="panel"><Empty icon={<GitPullRequest size={30} />} title="All caught up">Committed work appears here for an independent teammate to review.</Empty></div>}{snapshot.reviews.length > 0 && <><h2 className="history-heading">Review history</h2>{snapshot.reviews.map(review => <div className="panel review-history" key={review.id}><div><span className={`badge ${review.decision === 'approve' ? 'green' : 'amber'}`}>{review.decision === 'approve' ? 'Approved' : 'Changes requested'}</span><strong>{tasks.find(t => t.id === review.task_id)?.title}</strong><span className="subtle">by {actorName(review.reviewer_id)}</span></div><p>{review.comment}</p><code>{review.commit_sha.slice(0, 12)}</code></div>)}</>}</div>}
          {section === 'agents' && <RemoteAgents snapshot={snapshot} token={token} reload={reload} avatar={agent => <Avatar agent={agent} />} invite={() => open('agent')} message={agent => { setDmRecipient(agent.id); setSection('chat') }} />}
        </>}
        <footer className="page-footer"><span><span className="status-dot green" /> Built for agents. Designed for people.</span><span>AgentVerse <span className="footer-version">v0.2</span></span></footer>
      </main>
    </div>
    {toast && <div className="toast" role="status"><Check size={16} />{toast}</div>}
    {dialog && <Modal title={dialog === 'project' ? 'Start something together.' : dialog === 'task' ? 'Give the team a next step.' : dialog === 'agent' ? 'Meet your new teammate.' : dialog === 'memory' ? memory ? 'Update shared memory' : 'Remember something useful.' : dialog === 'connect' ? `${connection?.agent.name} is ready to connect.` : selectedTask?.title || 'Task details'} description={dialog === 'project' ? 'A clear goal gives every agent common ground.' : dialog === 'agent' ? 'Each teammate gets an independent identity and access token.' : dialog === 'connect' ? 'Save this token now. It is shown once and stored as a hash on the server.' : undefined} close={close}>
      {['project', 'task', 'agent', 'memory'].includes(dialog) && <form onSubmit={submitForm} className="dialog-form">
        {dialog === 'project' && <><label>Project name<input name="name" placeholder="e.g. Build our next big idea" required maxLength={100} /></label><label>The goal<textarea name="goal" placeholder="What should your team accomplish?" required rows={4} maxLength={20000} /></label><label>Git repository URL <span className="optional">optional</span><input name="repo_url" placeholder="https://github.com/your-team/project" maxLength={2000} /></label><label className="checkbox-label"><input type="checkbox" name="auto_plan" defaultChecked /><span>Let the first available agent turn this goal into a team plan.</span></label></>}
        {dialog === 'task' && <><label>Task title<input name="title" required placeholder="A clear, focused next step" maxLength={200} /></label><label>Description & acceptance criteria<textarea name="description" rows={4} placeholder="What should be done, and how will the team know it works?" maxLength={20000} /></label><label>Priority<select name="priority" defaultValue="medium"><option value="low">Low — when there's room</option><option value="medium">Medium — normal priority</option><option value="high">High — pick up next</option></select></label><label>Required capabilities <span className="optional">optional, comma-separated</span><input name="required_capabilities" placeholder="e.g. python, testing" /></label>{tasks.length > 0 && <fieldset className="dependency-options"><legend>Depends on <span className="optional">optional</span></legend>{tasks.map(t => <label className="checkbox-label" key={t.id}><input type="checkbox" name="dependencies" value={t.id} /><span>{t.title}</span></label>)}</fieldset>}<p className="form-hint">A matching teammate can claim this task once its dependencies are complete. Leave capabilities empty to open it to everyone.</p></>}
         {dialog === 'agent' && <><label>Teammate name<input name="name" required placeholder="e.g. Atlas, my OpenCode agent" maxLength={80} /></label><label>Agent tool<select name="kind" aria-label="Agent tool" value={agentTool} onChange={e => setAgentTool(e.target.value)} required>{agentTools.map(tool => <option key={tool.value} value={tool.value}>{tool.label}</option>)}</select></label>{agentTool === 'custom' && <label>Custom tool ID<input name="custom_kind" required maxLength={60} pattern="[A-Za-z0-9 _-]+" placeholder="e.g. future-wrapper" /></label>}<label>Strengths <span className="optional">comma-separated</span><input name="capabilities" placeholder="frontend, python, testing, review" /></label><label>Role & context<textarea name="description" rows={2} maxLength={5000} placeholder="What should teammates know about this agent?" /></label><label>Limitations <span className="optional">one per line</span><textarea name="limitations" rows={2} placeholder="e.g. No browser access" /></label><p className="form-hint">Choose the tool from the list. Select Other / custom only when the tool is not listed. HTTP is the primary connection; managed Launch requires a configured node runtime.</p></>}
        {dialog === 'memory' && <><label>Title<input name="title" defaultValue={memory?.title} required maxLength={200} placeholder="A decision, a handoff, a useful discovery" /></label><label>Shared knowledge<textarea name="content" defaultValue={memory?.content} required rows={9} maxLength={50000} placeholder="Give your teammates the context they need…" /></label><label>Tags<input name="tags" defaultValue={memory?.tags.join(', ')} placeholder="architecture, decision, handoff" /></label>{memory && <p className="form-hint">Editing version {memory.version}. Conflicting edits are detected before saving.</p>}</>}
        {formError && <p className="form-error" role="alert">{formError}</p>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <>{dialog === 'project' ? 'Create project' : dialog === 'task' ? 'Add task' : dialog === 'agent' ? 'Create connection' : 'Save memory'}<ArrowRight size={15} /></>}</button></div>
      </form>}
      {dialog === 'connect' && connection && <><ConnectionDetails agent={connection.agent} token={connection.token} copy={text => void copy(text)} />{formError && <p className="form-error">{formError}</p>}<div className="dialog-actions"><button className="button primary" onClick={close}><Check size={16} />I saved the token</button></div></>}
      {dialog === 'detail' && selectedTask && <div className="task-detail"><div className="detail-tags"><span className={`badge ${statuses.find(s => s.id === selectedTask.status)?.color}`}>{statuses.find(s => s.id === selectedTask.status)?.label}</span><span className={`priority ${selectedTask.priority}`}>{selectedTask.priority} priority</span><span className="subtle">{selectedTask.kind}</span></div><p className="detail-description">{selectedTask.description || 'No additional description.'}</p><div className="detail-meta"><span>Owner <strong>{selectedTask.assignee_id ? actorName(selectedTask.assignee_id) : 'Open to the team'}</strong></span><span>Dependencies <strong>{selectedTask.dependencies.length || 'None'}</strong></span></div>{selectedTask.dependencies.length > 0 && <div className="detail-dependencies">{selectedTask.dependencies.map(dep => <span key={dep}><GitBranch size={13} />{tasks.find(t => t.id === dep)?.title}<span className="subtle">{tasks.find(t => t.id === dep)?.status}</span></span>)}</div>}{selectedTask.summary && <><h3>Work summary</h3><p className="detail-description">{selectedTask.summary}</p></>}{selectedTask.branch && <div className="branch-detail"><GitBranch size={16} /><code>{selectedTask.branch}</code><span>{selectedTask.commit_sha?.slice(0, 12)}</span></div>}{selectedTask.diff && <details className="diff-detail"><summary>Inspect submitted diff</summary><pre>{selectedTask.diff}</pre></details>}{snapshot?.reviews.filter(r => r.task_id === selectedTask.id).map(r => <div className="review-history" key={r.id}><span className={`badge ${r.decision === 'approve' ? 'green' : 'amber'}`}>{r.decision.replace('_', ' ')}</span><strong>{actorName(r.reviewer_id)}</strong><p>{r.comment}</p></div>)}{formError && <p className="form-error">{formError}</p>}<div className="dialog-actions"><button className="button secondary" onClick={() => { setSection('chat'); close() }}><MessageSquare size={15} />Discuss with the team</button>{admin && selectedTask.status === 'in_progress' && <button className="button secondary" disabled={busy} onClick={async () => { try { await mutate(`/projects/${projectId}/tasks/${selectedTask.id}/release`, { reason: 'Released by workspace owner.' }); setToast('Task returned to the team.'); close() } catch { /* visible form error */ } }}><ArrowDownToLine size={15} />Release task</button>}{admin && selectedTask.reviewer_id && <button className="button secondary" disabled={busy} onClick={async () => { try { await mutate(`/projects/${projectId}/tasks/${selectedTask.id}/review-release`); close() } catch { /* visible form error */ } }}>Release review</button>}</div></div>}
      {dialog === 'detail' && selectedTask?.integration_sha && <div className="branch-detail"><CheckCheck size={16} /><span>Merged into the shared base</span><code>{selectedTask.integration_sha}</code></div>}
    </Modal>}
  </div>
}
