"""Durable, scoped conversation turns; replies and task dispatch commit once."""

import secrets
import time

from fastapi import HTTPException

from .models import MessageCreate, TaskCreate
from .context import chat_history, shared_memory, team_context
from .errors import safe_error


def fail(code, detail):
    raise HTTPException(code, detail)


class Conversations:
    def __init__(self, store):
        self.store = store
        columns = {row['name'] for row in store.db.execute('PRAGMA table_info(messages)')}
        for name, declaration in {'reply_to_id': 'TEXT', 'intent': "TEXT NOT NULL DEFAULT 'chat'",
                                  'dispatch_task_id': 'TEXT', 'coordinator_id': 'TEXT', 'client_request_id': 'TEXT'}.items():
            if name not in columns:
                store.db.execute(f'ALTER TABLE messages ADD COLUMN {name} {declaration}')
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                agent_id TEXT PRIMARY KEY REFERENCES agents(id), session_id TEXT NOT NULL,
                run_id TEXT, last_seen REAL NOT NULL, last_reply_at REAL NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS chat_turns (
                message_id TEXT NOT NULL REFERENCES messages(id), agent_id TEXT NOT NULL REFERENCES agents(id),
                state TEXT NOT NULL DEFAULT 'queued', session_id TEXT, run_id TEXT, claim_token TEXT,
                lease_until REAL, reply_id TEXT, error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                PRIMARY KEY(message_id,agent_id)
            );
            CREATE INDEX IF NOT EXISTS chat_queue ON chat_turns(agent_id,state,created_at);
            CREATE INDEX IF NOT EXISTS chat_lease ON chat_turns(state,lease_until);
            CREATE UNIQUE INDEX IF NOT EXISTS message_requests ON messages(project_id,sender_id,client_request_id)
                WHERE client_request_id IS NOT NULL;
        """)
        columns = {row['name'] for row in store.db.execute('PRAGMA table_info(chat_turns)')}
        if 'claim_request_id' not in columns:
            store.db.execute('ALTER TABLE chat_turns ADD COLUMN claim_request_id TEXT')

    def enqueue(self, principal, message_id):
        row = self.store.one('SELECT * FROM messages WHERE id=?', (message_id,))
        if row['reply_to_id'] and not principal.admin:
            return
        # Only explicit mentions/DMs trigger peer replies. Automatic replies never re-enqueue.
        peers = self.store.all('SELECT id,name FROM agents WHERE project_id=? AND revoked=0', (row['project_id'],))
        targets = []
        if row['recipient_id']:
            targets = [p['id'] for p in peers if p['id'] == row['recipient_id']]
        else:
            import re
            from collections import Counter
            folded = re.sub(r'```.*?```|`[^`]*`', '', row['content'].casefold(), flags=re.DOTALL)
            counts = Counter(p['name'].casefold() for p in peers)
            if any(counts[p['name'].casefold()] > 1 and re.search(r'(?<!\w)@' + re.escape(p['name'].casefold()) + r'(?![\w-])', folded) for p in peers):
                fail(422, 'That teammate name is ambiguous. Choose a direct message or mention the agent ID.')
            targets = [p['id'] for p in peers if re.search(r'(?<!\w)@' + re.escape(p['name'].casefold()) + r'(?![\w-])', folded)
                       or re.search(r'(?<!\w)@' + re.escape(p['id']) + r'(?!\w)', folded)]
            if not targets and principal.admin and re.match(r'\s*@[\w-]+', folded):
                fail(422, 'That @mention does not match a teammate. Use their exact name or choose a direct message.')
            if not targets and principal.admin:
                targets = [p['id'] for p in peers]
        for target in dict.fromkeys(targets):
            if target != principal.actor:
                self.store.db.execute('INSERT OR IGNORE INTO chat_turns(message_id,agent_id,created_at) VALUES(?,?,?)',
                                      (message_id, target, row['created_at']))
        if principal.admin and row['intent'] == 'task':
            self.dispatch(principal, row, TaskCreate(title=row['content'][:200], description=row['content'], kind='planning'))

    def dispatch(self, principal, message, request):
        if message['dispatch_task_id']:
            return message['dispatch_task_id']
        # The task records the owner's original request, including its provenance.
        from .store import Principal
        owner = Principal()
        self.store.project(owner, message['project_id'], active=True)
        description = message['content']
        if request.description and request.description != description:
            description = (description + '\n\nPlanning context:\n' + request.description)[:20000]
        task_id = self.store._create_task(owner, message['project_id'], TaskCreate(
            title=request.title, description=description, priority=request.priority, kind='planning'))
        self.store.db.execute('UPDATE messages SET dispatch_task_id=? WHERE id=?', (task_id, message['id']))
        self.store.event(message['project_id'], 'chat.dispatched', principal, message['id'], 'Created a planning task from the owner request')
        return task_id

    def expire(self):
        from types import SimpleNamespace
        expired = self.store.all("SELECT t.agent_id,t.message_id,m.project_id,m.recipient_id,m.sender_id FROM chat_turns t JOIN messages m ON m.id=t.message_id WHERE t.state='working' AND t.lease_until<?", (time.time(),))
        self.store.db.execute("UPDATE chat_turns SET state='unconfirmed',error='The listener stopped renewing its turn. Stop the old session before retrying.' "
                              "WHERE state='working' AND lease_until<?", (time.time(),))
        for turn in expired:
            self.store.event(turn['project_id'], 'chat.unconfirmed', SimpleNamespace(actor=turn['agent_id']), turn['message_id'],
                             'The conversation listener stopped renewing this reply', turn['sender_id'] if turn['recipient_id'] else None)

    def sweep(self):
        with self.store.transaction():
            self.expire()

    def register(self, principal, session_id):
        if principal.admin:
            fail(403, 'Use this agent’s own token to register a conversation listener.')
        with self.store.transaction():
            self.store.runtimes.can_claim(principal)
            self.expire()
            current = self.store.one('SELECT * FROM chat_sessions WHERE agent_id=?', (principal.agent_id,))
            if current and current['session_id'] != session_id and current['last_seen'] > time.time() - 90:
                fail(409, 'Another conversation listener is active for this agent. Stop it or use a separate teammate identity.')
            self.store.db.execute("INSERT INTO chat_sessions(agent_id,session_id,run_id,last_seen) VALUES(?,?,?,?) "
                                  "ON CONFLICT(agent_id) DO UPDATE SET last_reply_at=CASE WHEN chat_sessions.session_id=excluded.session_id THEN chat_sessions.last_reply_at ELSE 0 END,"
                                  "session_id=excluded.session_id,run_id=excluded.run_id,last_seen=excluded.last_seen,error=''",
                                  (principal.agent_id, session_id, principal.run_id, time.time()))
            self.store.event(principal.project_id, 'chat.listening', principal, principal.agent_id, 'Conversation listener started')
        return {'listening': True, 'session_id': session_id, 'heartbeat_seconds': 25}

    def session(self, principal, session_id):
        row = self.store.one('SELECT * FROM chat_sessions WHERE agent_id=?', (principal.agent_id,))
        if principal.admin or not row or not row['last_seen'] or row['session_id'] != session_id or row['run_id'] != principal.run_id:
            fail(409, 'This conversation session is no longer current.')
        return row

    def pulse(self, principal, session_id, stop=False, status='idle'):
        with self.store.transaction():
            self.session(principal, session_id)
            now = time.time()
            stop = stop or status == 'offline'
            self.store.db.execute('UPDATE chat_sessions SET last_seen=? WHERE agent_id=?', (0 if stop else now, principal.agent_id))
            self.store.db.execute('UPDATE agents SET last_seen=?,status=? WHERE id=?', (now, 'offline' if stop else status, principal.agent_id))
            if not stop:
                self.store.db.execute("UPDATE chat_turns SET lease_until=? WHERE agent_id=? AND session_id=? AND state='working'",
                                      (now + 90, principal.agent_id, session_id))
            else:
                self.store.db.execute("UPDATE chat_turns SET state='unconfirmed',error='The listener stopped before finishing this reply. Confirm its runtime has stopped before retrying.' "
                                      "WHERE agent_id=? AND session_id=? AND state='working'", (principal.agent_id, session_id))
        runtime = self.store.runtimes.runtime(principal.agent_id) if principal.run_id else None
        return {'ok': True, 'stop_requested': bool(runtime and runtime['desired_state'] == 'stopped')}

    def claim(self, principal, session_id, request_id=None):
        with self.store.transaction():
            self.session(principal, session_id)
            self.store.project(principal, principal.project_id, active=True)
            self.expire()
            self.store.runtimes.can_claim(principal)
            active = self.store.one("SELECT * FROM chat_turns WHERE agent_id=? AND state IN ('working','unconfirmed')", (principal.agent_id,))
            if active and active['state'] == 'working' and request_id and active['claim_request_id'] == request_id and active['session_id'] == session_id and active['run_id'] == principal.run_id:
                return self.turn(principal, active['message_id'], active['claim_token'])
            if active:
                fail(409, 'Finish or recover the current conversation turn first.')
            row = self.store.one("SELECT t.*,m.created_at FROM chat_turns t JOIN messages m ON m.id=t.message_id "
                                 "WHERE t.agent_id=? AND t.state='queued' ORDER BY m.created_at,m.id LIMIT 1", (principal.agent_id,))
            if not row:
                return None
            claim = secrets.token_urlsafe(32)
            self.store.db.execute("UPDATE chat_turns SET state='working',session_id=?,run_id=?,claim_token=?,lease_until=?,claim_request_id=?,error='' "
                                  "WHERE message_id=? AND agent_id=?",
                                  (session_id, principal.run_id, claim, time.time() + 90, request_id, row['message_id'], principal.agent_id))
            message = self.store.one('SELECT * FROM messages WHERE id=?', (row['message_id'],))
            if message['sender_id'] == 'human' and not message['coordinator_id']:
                self.store.db.execute('UPDATE messages SET coordinator_id=? WHERE id=?', (principal.agent_id, message['id']))
                message['coordinator_id'] = principal.agent_id
            self.store.event(principal.project_id, 'chat.working', principal, message['id'], 'Answering a conversation message', message['sender_id'] if message['recipient_id'] else None)
            return self.turn(principal, message['id'], claim)

    def turn(self, principal, message_id, claim):
        message = self.store.one('SELECT * FROM messages WHERE id=?', (message_id,))
        # Context is limited to this channel/DM and ends at this input, never at later messages.
        rows = self.store.messages(principal, principal.project_id, 29, before=message['id'],
                                   channel=None if message['recipient_id'] else message['channel'],
                                   recipient_id=(message['sender_id'] if message['recipient_id'] == principal.actor else message['recipient_id']))
        return {'message': message, 'history': chat_history(rows + [message]), 'claim_token': claim,
                'project': self.store.project(principal, principal.project_id),
                'team': team_context(self.store.team.peers(principal, principal.project_id)),
                'memory': shared_memory(self.store.memories(principal, principal.project_id)),
                'can_create_tasks': message['sender_id'] == 'human' and message['intent'] == 'auto'
                and message['coordinator_id'] == principal.agent_id and not message['dispatch_task_id']}

    def owned(self, principal, message_id, data):
        row = self.store.one('SELECT * FROM chat_turns WHERE message_id=? AND agent_id=?', (message_id, principal.agent_id))
        if not row or not secrets.compare_digest(row['claim_token'] or '', data.claim_token) or row['session_id'] != data.session_id or row['run_id'] != principal.run_id:
            fail(409, 'Conversation turn ownership changed; this result cannot be published.')
        return row

    def finish(self, principal, message_id, data):
        with self.store.transaction():
            row = self.owned(principal, message_id, data)
            if row['state'] == 'answered':
                return self.store.one('SELECT * FROM messages WHERE id=?', (row['reply_id'],))
            self.session(principal, data.session_id)
            self.store.runtimes.can_claim(principal)
            if row['state'] != 'working':
                fail(409, 'This turn is no longer accepting a reply.')
            message = self.store.one('SELECT * FROM messages WHERE id=?', (message_id,))
            if data.result.task_request:
                if message['sender_id'] != 'human' or message['intent'] != 'auto' or message['coordinator_id'] != principal.actor:
                    fail(403, 'Only the coordinating reply to an owner work request can create a task.')
                self.store.project(principal, principal.project_id, active=True)
                self.dispatch(principal, message, data.result.task_request)
                message = self.store.one('SELECT * FROM messages WHERE id=?', (message_id,))
            recipient = None if not message['recipient_id'] else message['sender_id']
            reply_id = self.store._message(principal, message['project_id'], MessageCreate(
                content=data.result.reply, channel=message['channel'], recipient_id=recipient,
                reply_to_id=message_id, task_id=message['dispatch_task_id'] or message['task_id'], intent='chat'))
            self.store.db.execute("UPDATE chat_turns SET state='answered',reply_id=?,error='' WHERE message_id=? AND agent_id=?",
                                  (reply_id, message_id, principal.agent_id))
            self.store.db.execute("UPDATE chat_sessions SET last_reply_at=?,error='' WHERE agent_id=?", (time.time(), principal.agent_id))
        return self.store.one('SELECT * FROM messages WHERE id=?', (reply_id,))

    def failure(self, principal, message_id, data):
        error = safe_error(data.error)
        with self.store.transaction():
            row = self.owned(principal, message_id, data)
            if row['state'] == 'answered':
                return {'state': 'answered'}
            if row['state'] not in ('working', 'unconfirmed'):
                return {'state': row['state']}
            state = 'failed' if data.cancellation_confirmed else 'unconfirmed'
            self.store.db.execute('UPDATE chat_turns SET state=?,error=? WHERE message_id=? AND agent_id=?',
                                  (state, error, message_id, principal.agent_id))
            self.store.db.execute('UPDATE chat_sessions SET error=? WHERE agent_id=?', (error, principal.agent_id))
            if data.cancellation_confirmed:
                self.store.db.execute('UPDATE messages SET coordinator_id=NULL WHERE id=? AND coordinator_id=? AND dispatch_task_id IS NULL',
                                      (message_id, principal.agent_id))
            message = self.store.one('SELECT sender_id,recipient_id FROM messages WHERE id=?', (message_id,))
            self.store.event(principal.project_id, 'chat.failed', principal, message_id, 'Conversation failed; see reply status', message['sender_id'] if message['recipient_id'] else None)
        return {'state': state}

    def retry(self, principal, project_id, message_id, agent_id, confirmed_stopped):
        self.store.admin_only(principal)
        with self.store.transaction():
            self.store.project(principal, project_id, active=True)
            self.store.agent(principal, project_id, agent_id)
            message = self.store.one('SELECT * FROM messages WHERE id=? AND project_id=?', (message_id, project_id))
            where, args = self.store.visible_sql(principal)
            if not message or not self.store.one(f'SELECT id FROM messages WHERE id=? AND {where}', (message_id, *args)):
                fail(404, 'Conversation message not found.')
            self.expire()
            row = self.store.one('SELECT * FROM chat_turns WHERE message_id=? AND agent_id=?', (message_id, agent_id))
            if not row or row['state'] not in ('failed', 'unconfirmed'):
                fail(409, 'Only a failed or unconfirmed reply can be retried.')
            if row['state'] == 'unconfirmed' and not confirmed_stopped:
                fail(409, 'Stop the old agent session and confirm it has stopped before retrying.')
            self.store.db.execute("UPDATE chat_turns SET state='queued',claim_token=NULL,session_id=NULL,run_id=NULL,error='' WHERE message_id=? AND agent_id=?",
                                  (message_id, agent_id))
            self.store.event(project_id, 'chat.retry', principal, message_id, 'Conversation reply queued again', message['recipient_id'])
        return {'queued': True}

    def view(self, message):
        result = dict(message)
        result['deliveries'] = self.store.all('SELECT agent_id,state,error,reply_id,lease_until FROM chat_turns WHERE message_id=? ORDER BY agent_id', (message['id'],))
        for delivery in result['deliveries']:
            if delivery['state'] == 'working' and delivery['lease_until'] < time.time():
                delivery.update(state='unconfirmed', error='The listener stopped renewing this reply. Stop its old session before retrying.')
            delivery.pop('lease_until')
        return result

    def status(self, agent_id):
        row = self.store.one('SELECT * FROM chat_sessions WHERE agent_id=?', (agent_id,))
        pending = self.store.one("SELECT COUNT(*) AS count FROM chat_turns WHERE agent_id=? AND state='queued'", (agent_id,))['count']
        state = 'not_listening'
        if row:
            state = 'offline' if row['last_seen'] < time.time() - 90 else 'error' if row['error'] else 'verified' if row['last_reply_at'] else 'listening'
            if state != 'offline' and self.store.one("SELECT 1 FROM chat_turns WHERE agent_id=? AND state='working'", (agent_id,)):
                state = 'busy'
            if self.store.one("SELECT 1 FROM chat_turns WHERE agent_id=? AND state='unconfirmed'", (agent_id,)):
                state = 'unconfirmed'
        return {'state': state, 'pending': pending, 'last_reply_at': row['last_reply_at'] if row else 0,
                'error': 'The last conversation reply failed. Inspect its reply status.' if row and row['error'] else ''}
