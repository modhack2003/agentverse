export type Project = { id: string; name: string; goal: string; repo_url: string; status: 'active' | 'paused'; created_at: number }
export type ModelOption = { id: string; name: string }
export type RuntimeProfile = { id: string; name: string; kind: string; models: ModelOption[] }
export type RemoteNode = { id: string; name: string; online: boolean; last_seen: number; profiles: RuntimeProfile[] }
export type AgentRuntime = { agent_id: string; node_id: string; profile_id: string; model: string; desired_state: 'running' | 'stopped'; state: 'stopped' | 'queued' | 'starting' | 'running' | 'stopping' | 'failed'; run_id: string | null; pid: number | null; error: string; updated_at: number }
export type Agent = { id: string; name: string; kind: string; capabilities: string[]; status: string; online: boolean; last_seen: number; runtime: AgentRuntime | null; revoked: boolean }
export type Task = {
  id: string; title: string; description: string; priority: 'low' | 'medium' | 'high'; kind: string;
  status: 'backlog' | 'in_progress' | 'review' | 'done'; assignee_id: string | null; reviewer_id: string | null;
  dependencies: string[]; blocked: boolean; branch: string | null; commit_sha: string | null;
  summary: string | null; diff: string | null; revision: number; integration_sha: string | null
}
export type Message = { id: string; sender_id: string; recipient_id: string | null; channel: string; content: string; created_at: number; task_id: string | null }
export type Memory = { id: string; title: string; content: string; tags: string[]; version: number; author_id: string; updated_at: number }
export type Review = { id: string; task_id: string; reviewer_id: string; decision: string; comment: string; commit_sha: string; created_at: number }
export type Event = { id: number; kind: string; actor_id: string; detail: string; subject_id: string; created_at: number }
export type Snapshot = { project: Project; agents: Agent[]; nodes: RemoteNode[]; tasks: Task[]; messages: Message[]; memories: Memory[]; reviews: Review[]; events: Event[]; cursor: number; identity: { actor_id: string; admin: boolean } }
