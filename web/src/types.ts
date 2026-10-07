export type Project = { id: string; name: string; goal: string; repo_url: string; status: 'active' | 'paused'; created_at: number }
export type ModelOption = { id: string; name: string }
export type ConnectionMode = 'managed_cli' | 'managed_api' | 'connected'
export type SettingValue = string | number | boolean | null
export type SettingField = { key: string; label: string; type: 'text' | 'number' | 'boolean' | 'choice'; default: SettingValue; options: string[]; minimum: number | null; maximum: number | null; help: string }
export type RuntimeProfile = { id: string; name: string; kind: string; models: ModelOption[]; mode: ConnectionMode; driver: string; protocol_version: number; tool_version: string; capabilities: string[]; limitations: string[]; availability: 'available' | 'unavailable' | 'needs_setup'; diagnostic: string; settings_schema: SettingField[] }
export type Diagnostic = { code: string; severity: 'info' | 'warning' | 'error'; message: string; profile_id: string | null }
export type RemoteNode = { id: string; name: string; online: boolean; last_seen: number; profiles: RuntimeProfile[]; diagnostics: Diagnostic[]; capacity: number; protocol_version: number }
export type RuntimeConfig = { node_id: string; profile_id: string; model: string; settings: Record<string, SettingValue> }
export type AgentRuntime = RuntimeConfig & { agent_id: string; mode: ConnectionMode; desired_state: 'running' | 'stopped'; state: 'external' | 'stopped' | 'queued' | 'starting' | 'running' | 'stopping' | 'failed' | 'unconfirmed'; run_id: string | null; pid: number | null; error: string; updated_at: number }
export type Agent = { id: string; name: string; kind: string; description: string; capabilities: string[]; limitations: string[]; configured_capabilities: string[]; configured_limitations: string[]; profile_version: number; session_info: { connection?: string; tool_version?: string; capabilities?: string[]; limitations?: string[] }; status: string; online: boolean; last_seen: number; runtime: AgentRuntime | null; revoked: boolean }
export type Task = {
  id: string; title: string; description: string; priority: 'low' | 'medium' | 'high'; kind: string;
  status: 'backlog' | 'in_progress' | 'review' | 'done'; assignee_id: string | null; reviewer_id: string | null;
  dependencies: string[]; required_capabilities: string[]; blocked: boolean; branch: string | null; commit_sha: string | null;
  summary: string | null; diff: string | null; revision: number; integration_sha: string | null
}
export type Message = { id: string; sender_id: string; recipient_id: string | null; channel: string; content: string; created_at: number; task_id: string | null }
export type Memory = { id: string; title: string; content: string; tags: string[]; version: number; author_id: string; updated_at: number }
export type Review = { id: string; task_id: string; reviewer_id: string; decision: string; comment: string; commit_sha: string; created_at: number }
export type Event = { id: number; kind: string; actor_id: string; detail: string; subject_id: string; created_at: number }
export type AgentIssue = { id: string; agent_id: string; severity: 'info' | 'warning' | 'error'; title: string; detail: string; resolved: number; created_at: number }
export type HelpRequest = { id: string; sender_id: string; capability: string; question: string; task_id: string | null; recipient_id: string | null; assignee_id: string | null; state: 'open' | 'in_progress' | 'answered'; answer: string | null; created_at: number }
export type Snapshot = { project: Project; agents: Agent[]; nodes: RemoteNode[]; tasks: Task[]; messages: Message[]; memories: Memory[]; reviews: Review[]; events: Event[]; issues: AgentIssue[]; help_requests: HelpRequest[]; cursor: number; identity: { actor_id: string; admin: boolean } }
