import json
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
import httpx


from agentverse import Client
from agentcommons.worker import Worker
from conftest import agent, project


def session(client, headers, identifier='a' * 32):
    assert client.post('/api/agents/chat/register', headers=headers, json={'session_id': identifier}).status_code == 200
    return identifier


def claim(client, headers, identifier):
    response = client.post('/api/agents/chat/claim', headers=headers, json={'session_id': identifier})
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, headers, identifier, turn, reply='A real callback reply', task=None):
    result = {'reply': reply}
    if task:
        result['task_request'] = task
    return client.post(f"/api/agents/chat/{turn['message']['id']}/finish", headers=headers,
                       json={'session_id': identifier, 'claim_token': turn['claim_token'], 'result': result})


def test_broadcast_once_task_dispatch_and_lost_success(api):
    client, _ = api
    p = project(client)
    a, ha, _ = agent(client, p, 'Alpha')
    b, hb, _ = agent(client, p, 'Beta')
    sa, sb = session(client, ha), session(client, hb, 'b' * 32)
    payload = {'content': 'Build a small homepage', 'client_request_id': 'same-human-send'}
    message = client.post(f'/api/projects/{p}/messages', json=payload).json()
    assert client.post(f'/api/projects/{p}/messages', json=payload).json()['id'] == message['id']
    assert client.post(f'/api/projects/{p}/messages', json={**payload, 'content': 'Different'}).status_code == 409
    ta, tb = claim(client, ha, sa), claim(client, hb, sb)
    assert ta['can_create_tasks'] and not tb['can_create_tasks']
    assert client.post('/api/agents/chat/claim', headers=ha, json={'session_id': sa}).status_code == 409
    planned = finish(client, ha, sa, ta, 'I will plan that work.', {'title': 'Homepage', 'description': 'A usable homepage'})
    assert planned.status_code == 200
    assert finish(client, ha, sa, ta, 'Lost success retry', {'title': 'Duplicate', 'description': ''}).json()['id'] == planned.json()['id']
    assert finish(client, hb, sb, tb, task={'title': 'Duplicate'}).status_code == 403
    assert finish(client, hb, sb, tb, 'I can review it.').status_code == 200
    snapshot = client.get(f'/api/projects/{p}/snapshot').json()
    assert len(snapshot['tasks']) == 1 and snapshot['tasks'][0]['kind'] == 'planning'
    assert snapshot['tasks'][0]['created_by'] == 'human'
    assert len(snapshot['messages']) == 3
    original = next(m for m in snapshot['messages'] if m['id'] == message['id'])
    assert original['dispatch_task_id'] == snapshot['tasks'][0]['id']
    assert {d['state'] for d in original['deliveries']} == {'answered'}
    assert all(a['conversation']['state'] == 'verified' for a in snapshot['agents'])
    assert claim(client, ha, sa) is None and claim(client, hb, sb) is None
    assert {m['sender_id'] for m in snapshot['messages']} == {'human', a, b}


def test_mentions_private_context_and_no_reply_storm(api):
    client, _ = api
    p = project(client)
    a, ha, _ = agent(client, p, 'Alpha')
    b, hb, _ = agent(client, p, 'Beta')
    sa, sb = session(client, ha), session(client, hb, 'b' * 32)
    client.post(f'/api/projects/{p}/messages', headers=ha, json={'content': 'Private secret', 'recipient_id': b})
    tb = claim(client, hb, sb)
    assert not tb['can_create_tasks']
    assert finish(client, hb, sb, tb, 'Private answer @Alpha').status_code == 200
    assert claim(client, ha, sa) is None
    assert not client.get(f'/api/projects/{p}/messages').json()
    client.post(f'/api/projects/{p}/messages', json={'content': '@Beta can we talk?', 'intent': 'chat'})
    tb = claim(client, hb, sb)
    assert [m['content'] for m in tb['history']] == ['@Beta can we talk?']
    assert finish(client, hb, sb, tb, 'Yes @Alpha, we can.').status_code == 200
    assert claim(client, ha, sa) is None and claim(client, hb, sb) is None
    public = client.get(f'/api/projects/{p}/messages').json()
    assert [m['content'] for m in public] == ['@Beta can we talk?', 'Yes @Alpha, we can.']
    assert public[1]['recipient_id'] is None
    assert client.get(f'/api/projects/{p}/tasks').json() == []


def test_backlog_over_history_window_and_channel_isolation(api):
    client, _ = api
    p = project(client)
    _, h, _ = agent(client, p, 'Backlog reader')
    for i in range(105):
        client.post(f'/api/projects/{p}/messages', json={'content': f'Message {i}', 'channel': 'engineering', 'intent': 'chat'})
    client.post(f'/api/projects/{p}/messages', json={'content': 'Other channel', 'channel': 'reviews', 'intent': 'chat'})
    sid = session(client, h)
    for i in range(105):
        turn = claim(client, h, sid)
        assert turn['message']['content'] == f'Message {i}'
        assert turn['history'][-1]['content'] == f'Message {i}'
        assert len(turn['history']) <= 30
        assert all(m['channel'] == 'engineering' for m in turn['history'])
        assert finish(client, h, sid, turn, f'Reply {i}').status_code == 200
    assert claim(client, h, sid)['message']['content'] == 'Other channel'


def test_listener_takeover_stale_finish_and_confirmed_retry(api):
    client, store = api
    p = project(client)
    a, h, _ = agent(client, p, 'Restarted peer')
    sid = session(client, h)
    assert client.post('/api/agents/chat/register', headers=h, json={'session_id': 'b' * 32}).status_code == 409
    message = client.post(f'/api/projects/{p}/messages', json={'content': 'hi'}).json()
    old = claim(client, h, sid)
    store.db.execute('UPDATE chat_turns SET lease_until=0 WHERE agent_id=?', (a,))
    store.db.execute('UPDATE chat_sessions SET last_seen=0 WHERE agent_id=?', (a,))
    status = client.get(f'/api/projects/{p}/messages').json()[0]['deliveries'][0]
    assert status['state'] == 'unconfirmed'
    retry = f"/api/projects/{p}/messages/{message['id']}/retry/{a}"
    assert client.post(retry, json={}).status_code == 409
    assert client.post(retry, json={'confirmed_stopped': True}).status_code == 200
    newer = session(client, h, 'b' * 32)
    turn = claim(client, h, newer)
    assert finish(client, h, sid, old).status_code == 409
    assert finish(client, h, newer, turn).status_code == 200
    assert len(client.get(f'/api/projects/{p}/messages').json()) == 2


def test_chat_failure_does_not_claim_success_and_can_retry(api):
    client, _ = api
    p = project(client)
    a, h, _ = agent(client, p, 'Broken provider')
    sid = session(client, h)
    message = client.post(f'/api/projects/{p}/messages', json={'content': 'hi'}).json()
    turn = claim(client, h, sid)
    failure = client.post(f"/api/agents/chat/{message['id']}/fail", headers=h, json={
        'session_id': sid, 'claim_token': turn['claim_token'], 'error': 'Provider authentication failed'})
    assert failure.json()['state'] == 'failed'
    snapshot = client.get(f'/api/projects/{p}/snapshot').json()
    assert snapshot['agents'][0]['conversation']['state'] == 'error'
    assert len(snapshot['messages']) == 1
    assert client.post(f"/api/projects/{p}/messages/{message['id']}/retry/{a}", json={}).status_code == 200
    turn = claim(client, h, sid)
    assert finish(client, h, sid, turn).status_code == 200


def test_explicit_work_message_pause_and_cross_project_permissions(api):
    client, _ = api
    p = project(client)
    _, h, _ = agent(client, p, 'Peer')
    sid = session(client, h)
    request = client.post(f'/api/projects/{p}/messages', json={'content': 'Create the homepage', 'intent': 'task'}).json()
    assert request['dispatch_task_id']
    turn = claim(client, h, sid)
    assert not turn['can_create_tasks']
    assert finish(client, h, sid, turn).status_code == 200
    other = project(client, 'Other project')
    assert client.post(f'/api/projects/{other}/messages', headers=h, json={'content': 'Wrong scope'}).status_code == 403
    client.patch(f'/api/projects/{p}', json={'status': 'paused'})
    assert client.post(f'/api/projects/{p}/messages', json={'content': 'More work', 'intent': 'task'}).status_code == 409
    assert len(client.get(f'/api/projects/{p}/tasks').json()) == 1


def test_sdk_listener_invokes_callback_for_each_new_human_turn(live_server):
    url, admin = live_server
    p = project(admin)
    a, _, token = agent(admin, p, 'Live SDK peer')
    calls = []
    stop = threading.Event()

    def respond(turn):
        calls.append(turn['message']['content'])
        return f"Answer {len(calls)}: {turn['message']['content']}"

    def listen():
        with Client(url, token) as peer:
            peer.connect(capabilities=['conversation'])
            peer.listen(respond, stop=stop, interval=.05)

    thread = threading.Thread(target=listen)
    thread.start()
    try:
        for content in ['hello guys', 'can we talk?']:
            admin.post(f'/api/projects/{p}/messages', json={'content': content})
            deadline = time.monotonic() + 10
            while True:
                messages = admin.get(f'/api/projects/{p}/messages').json()
                if any(m['sender_id'] == a and m['content'].endswith(content) for m in messages):
                    break
                assert time.monotonic() < deadline
                time.sleep(.03)
        assert calls == ['hello guys', 'can we talk?']
        assert admin.get(f'/api/projects/{p}/snapshot').json()['agents'][0]['conversation']['state'] == 'verified'
    finally:
        stop.set()
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_managed_chat_to_plan_code_and_independent_review(live_server, tmp_path, monkeypatch):
    url, client = live_server
    for key in ['GIT_AUTHOR_NAME', 'GIT_COMMITTER_NAME']:
        monkeypatch.setenv(key, 'Conversation fixture')
    for key in ['GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_EMAIL']:
        monkeypatch.setenv(key, 'fixture@example.test')
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'init', '--initial-branch=main', str(repo)], check=True, capture_output=True)
    subprocess.run(['git', 'commit', '--allow-empty', '-m', 'Initial'], cwd=repo, check=True, capture_output=True)
    p = project(client)
    a, _, ta = agent(client, p, 'Coding peer')
    b, _, tb = agent(client, p, 'Review peer')
    fixture = Path(__file__).parent / 'fixtures/conversation_cli.py'
    command = shlex.join([sys.executable, str(fixture), '{prompt_file}'])
    client.post(f'/api/projects/{p}/messages', json={'content': 'hi'})
    Worker(url, ta, repo, command, push=False).run(once=True)
    Worker(url, tb, repo, command, push=False).run(once=True)
    assert client.get(f'/api/projects/{p}/tasks').json() == []
    client.post(f'/api/projects/{p}/messages', json={'content': 'Build feature.txt'})
    Worker(url, ta, repo, command, push=False).run(once=True)
    Worker(url, tb, repo, command, push=False).run(once=True)
    tasks = client.get(f'/api/projects/{p}/tasks').json()
    assert len(tasks) == 1 and tasks[0]['kind'] == 'planning'
    Worker(url, ta, repo, command, push=False).run(once=True)
    Worker(url, ta, repo, command, push=False).run(once=True)
    Worker(url, tb, repo, command, push=False).run(once=True)
    snapshot = client.get(f'/api/projects/{p}/snapshot').json()
    assert all(t['status'] == 'done' for t in snapshot['tasks'])
    assert snapshot['reviews'][0]['reviewer_id'] == b
    assert any(m['sender_id'] == a and m['content'] == 'Hello! I can talk with you.' for m in snapshot['messages'])
    assert any(m['task_id'] and 'Feature committed' in m['content'] for m in snapshot['messages'])
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True) == ''


def test_sdk_lost_publication_response_does_not_invoke_model_twice(live_server, monkeypatch):
    url, admin = live_server
    p = project(admin)
    _, _, token = agent(admin, p, 'Lost response peer')
    admin.post(f'/api/projects/{p}/messages', json={'content': 'hello'})
    with Client(url, token) as peer:
        original = peer.post
        failures = set()
        calls = []

        def post(path, data=None):
            result = original(path, data)
            operation = path.rsplit('/', 1)[-1]
            if operation in {'claim', 'finish'} and operation not in failures:
                failures.add(operation)
                raise httpx.ReadError('Success response was lost')
            return result

        monkeypatch.setattr(peer, 'post', post)
        peer.listen(lambda turn: calls.append(turn['message']['id']) or 'A single model invocation', once=True)
        assert len(calls) == 1
        assert failures == {'claim', 'finish'}
    assert len(admin.get(f'/api/projects/{p}/messages').json()) == 2


def test_unconfirmed_cancellation_blocks_new_work_until_confirmed_recovery(api):
    client, _ = api
    p = project(client)
    a, h, _ = agent(client, p, 'Uncertain API peer')
    sid = session(client, h)
    message = client.post(f'/api/projects/{p}/messages', json={'content': 'hi'}).json()
    turn = claim(client, h, sid)
    assert client.post(f"/api/agents/chat/{message['id']}/fail", headers=h, json={
        'session_id': sid, 'claim_token': turn['claim_token'], 'error': 'Cancellation unconfirmed', 'cancellation_confirmed': False}).json()['state'] == 'unconfirmed'
    task = client.post(f'/api/projects/{p}/tasks', json={'title': 'Another task'}).json()
    assert client.post(f"/api/projects/{p}/tasks/{task['id']}/claim", headers=h).status_code == 409
    assert client.post(f"/api/projects/{p}/messages/{message['id']}/retry/{a}", json={}).status_code == 409
    assert client.post('/api/agents/chat/stop', headers=h, json={'session_id': sid}).status_code == 200
    assert client.post('/api/agents/chat/heartbeat', headers=h, json={'session_id': sid}).status_code == 409
    assert finish(client, h, sid, turn).status_code == 409
    assert client.post(f"/api/projects/{p}/messages/{message['id']}/retry/{a}", json={'confirmed_stopped': True}).status_code == 200
    session(client, h, 'b' * 32)
    assert client.post(f"/api/projects/{p}/tasks/{task['id']}/claim", headers=h).status_code == 200


def test_mcp_conversation_turns_share_the_http_queue(api):
    client, _ = api
    p = project(client)
    _, h, _ = agent(client, p, 'MCP listener')
    h = {**h, 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-06-18'}

    def call(name, arguments):
        response = client.post('/mcp/', headers=h, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})
        result = response.json()['result']
        assert not result.get('isError'), result
        return json.loads(result['content'][0]['text'])

    call('register_chat_listener', {'session_id': 'a' * 32})
    client.post(f'/api/projects/{p}/messages', json={'content': 'hello MCP'})
    turn = call('claim_chat_turn', {'session_id': 'a' * 32})
    call('finish_chat_turn', {'message_id': turn['message']['id'], 'session_id': 'a' * 32, 'claim_token': turn['claim_token'], 'result': {'reply': 'MCP model reply'}})
    assert client.get(f'/api/projects/{p}/messages').json()[-1]['content'] == 'MCP model reply'


def test_stopping_listener_holds_its_invocation_and_stale_heartbeat_cannot_stop_replacement(api):
    client, _ = api
    p = project(client)
    a, h, _ = agent(client, p, 'Session owner')
    sid = session(client, h)
    message = client.post(f'/api/projects/{p}/messages', json={'content': 'hello'}).json()
    turn = claim(client, h, sid)
    assert client.post('/api/agents/chat/stop', headers=h, json={'session_id': sid}).status_code == 200
    assert client.get(f'/api/projects/{p}/messages').json()[0]['deliveries'][0]['state'] == 'unconfirmed'
    assert finish(client, h, sid, turn).status_code == 409
    assert client.post(f"/api/projects/{p}/messages/{message['id']}/retry/{a}", json={'confirmed_stopped': True}).status_code == 200
    replacement = session(client, h, 'b' * 32)
    assert client.post('/api/agents/chat/heartbeat', headers=h, json={'session_id': sid, 'status': 'offline'}).status_code == 409
    assert client.post('/api/agents/chat/stop', headers=h, json={'session_id': sid}).status_code == 409
    assert client.post('/api/agents/chat/heartbeat', headers=h, json={'session_id': replacement}).status_code == 200
    assert client.get(f'/api/projects/{p}/snapshot').json()['agents'][0]['conversation']['state'] == 'listening'


def test_unknown_mentions_do_not_broadcast_and_empty_replies_do_not_verify(api):
    client, _ = api
    p = project(client)
    _, h, _ = agent(client, p, 'Named peer')
    sid = session(client, h)
    assert client.post(f'/api/projects/{p}/messages', json={'content': '@missing hi'}).status_code == 422
    assert client.post(f'/api/projects/{p}/messages', json={'content': '  '}).status_code == 422
    client.post(f'/api/projects/{p}/messages', json={'content': 'hi'})
    turn = claim(client, h, sid)
    assert finish(client, h, sid, turn, '  ').status_code == 422
    assert client.get(f'/api/projects/{p}/snapshot').json()['agents'][0]['conversation']['last_reply_at'] == 0


def test_large_shared_context_preserves_the_current_input_and_bounds_model_context(api):
    client, _ = api
    p = project(client)
    _, h, _ = agent(client, p, 'Context reader')
    for i in range(20):
        assert client.post(f'/api/projects/{p}/memories', json={'title': f'Large memory {i}', 'content': 'M' * 50000}).status_code == 201
    text = 'Actual current request ' + 'X' * 19000
    client.post(f'/api/projects/{p}/messages', json={'content': text})
    sid = session(client, h)
    turn = claim(client, h, sid)
    assert turn['message']['content'] == text
    assert len(json.dumps(turn)) < 120000
    assert any('Context truncated' in memory['content'] for memory in turn['memory'])


def test_stuck_sdk_callback_is_held_until_it_really_ends(live_server):
    url, admin = live_server
    p = project(admin)
    _, _, token = agent(admin, p, 'Slow callback')
    admin.post(f'/api/projects/{p}/messages', json={'content': 'hello'})
    blocked, stop = threading.Event(), threading.Event()
    peer = Client(url, token)
    thread = threading.Thread(target=lambda: peer.listen(lambda _: blocked.wait(10) or 'Late answer', stop=stop, interval=.05, timeout=.15))
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while admin.get(f'/api/projects/{p}/messages').json()[0]['deliveries'][0]['state'] != 'unconfirmed':
            assert time.monotonic() < deadline
            time.sleep(.02)
        assert admin.get(f'/api/projects/{p}/snapshot').json()['agents'][0]['conversation']['state'] == 'unconfirmed'
        assert len(admin.get(f'/api/projects/{p}/messages').json()) == 1
        blocked.set()
        deadline = time.monotonic() + 5
        while admin.get(f'/api/projects/{p}/messages').json()[0]['deliveries'][0]['state'] != 'failed':
            assert time.monotonic() < deadline
            time.sleep(.02)
    finally:
        stop.set()
        blocked.set()
        thread.join(timeout=10)
        peer.close()
    assert not thread.is_alive()


def test_callback_errors_are_actionable_without_leaking_credentials(live_server, monkeypatch):
    url, admin = live_server
    p = project(admin)
    _, _, token = agent(admin, p, 'Provider failure')
    secret = 'synthetic-provider-key-not-real'
    monkeypatch.setenv('TEST_PROVIDER_API_KEY', secret)
    admin.post(f'/api/projects/{p}/messages', json={'content': 'hello'})

    def respond(_):
        raise RuntimeError(f'Provider login failed; api_key={secret}; agent credential {token}')

    with Client(url, token) as peer:
        peer.listen(respond, once=True)
    message = admin.get(f'/api/projects/{p}/messages').json()[0]
    error = message['deliveries'][0]['error']
    assert 'Provider login failed' in error
    assert secret not in error and token not in error


def test_managed_api_bridge_replies_to_human_chat(live_server, tmp_path):
    from test_team_and_adapters import jobs_server
    from test_remote_control import node
    from agentcommons.node import NodeConfig, NodeService

    url, client = live_server
    repo = tmp_path / 'api-chat-repo'
    subprocess.run(['git', 'init', '--initial-branch=main', str(repo)], check=True, capture_output=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '--allow-empty', '-m', 'Initial'], cwd=repo, check=True, capture_output=True)
    p = project(client)
    a, _, _ = agent(client, p, 'API conversation peer')
    n, _, token = node(client, p, register=False)
    with jobs_server('completed', {'reply': 'The jobs-protocol model answered your message.'}) as (endpoint, evidence):
        service = NodeService(url, token, NodeConfig(repo=str(repo), log_dir=str(tmp_path / 'logs'), profiles=[{
            'id': 'api', 'name': 'API chat bridge', 'kind': 'custom', 'driver': 'http', 'http': {'url': endpoint}, 'push': False}]))
        try:
            service.register()
            path = f'/api/projects/{p}/agents/{a}'
            assert client.put(path + '/runtime', json={'node_id': n, 'profile_id': 'api'}).status_code == 200
            client.post(f'/api/projects/{p}/messages', json={'content': 'hi API peer'})
            assert client.post(path + '/launch').status_code == 200
            deadline = time.monotonic() + 20
            while True:
                service.step()
                snapshot = client.get(f'/api/projects/{p}/snapshot').json()
                if any(m['content'] == 'The jobs-protocol model answered your message.' for m in snapshot['messages']):
                    assert snapshot['agents'][0]['conversation']['state'] == 'verified'
                    assert snapshot['agents'][0]['runtime']['mode'] == 'managed_api'
                    break
                assert time.monotonic() < deadline, snapshot
                time.sleep(.05)
            assert 'answering an AgentVerse conversation' in evidence['payload']['prompt']
            assert client.post(path + '/stop').status_code == 200
            service.step()
        finally:
            service.shutdown()
