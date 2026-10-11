import json
import time
from types import SimpleNamespace

import pytest

from agentcommons.node import NodeService
from agentcommons.http_adapter import write_state
from conftest import agent, project
from test_remote_control import SESSION, PROFILES, configure, node


def test_node_token_replacement_permissions_identity_and_fencing(api):
    client, store = api
    p, other = project(client), project(client, 'Other')
    a, peer_headers, _ = agent(client, p, 'Atlas')
    n, old_headers, old_token = node(client, p, register=False)
    path = f'/api/projects/{p}/nodes/{n}/token'
    assert client.post(path, headers=peer_headers).status_code == 403
    assert client.post(f'/api/projects/{other}/nodes/{n}/token').status_code == 404
    stale_identity = store.runtimes.authenticate_node(f'Bearer {old_token}')
    replacement = client.post(path)
    assert replacement.status_code == 200
    result = replacement.json()
    assert result['node']['id'] == n
    assert result['token'] != old_token
    assert client.post('/api/nodes/me/register', headers=old_headers, json={'session_id': SESSION, 'profiles': PROFILES}).status_code == 401
    from agentcommons.models import NodeRegister
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        store.runtimes.register(stale_identity, NodeRegister(session_id=SESSION, profiles=PROFILES))
    assert error.value.status_code == 401
    new_headers = {'Authorization': f"Bearer {result['token']}"}
    assert client.post('/api/nodes/me/register', headers=new_headers, json={'session_id': SESSION, 'profiles': PROFILES}).status_code == 200
    configure(client, p, a, n)
    assert client.post(path).status_code == 409
    client.post('/api/nodes/me/disconnect', headers=new_headers, json={'session_id': SESSION})
    disconnected = client.get(f'/api/projects/{p}/nodes').json()[0]
    assert disconnected['last_contact'] > 0 and disconnected['last_seen'] == 0
    final = client.post(path)
    assert final.status_code == 200
    snapshot = client.get(f'/api/projects/{p}/snapshot').json()
    assert snapshot['agents'][0]['runtime']['node_id'] == n
    assert old_token not in json.dumps(snapshot) and result['token'] not in json.dumps(snapshot)
    assert client.post('/api/nodes/me/poll', headers=new_headers, json={'session_id': SESSION}).status_code == 401


@pytest.mark.parametrize('state', ['queued', 'starting', 'running', 'stopping', 'unconfirmed'])
def test_node_replacement_never_bypasses_active_or_uncertain_work(api, state):
    client, store = api
    p = project(client)
    a, _, _ = agent(client, p, 'Atlas')
    n, _, _ = node(client, p)
    configure(client, p, a, n)
    store.db.execute('UPDATE agent_runtimes SET state=? WHERE agent_id=?', (state, a))
    store.db.execute('UPDATE nodes SET last_seen=? WHERE id=?', (time.time() - 100, n))
    assert client.post(f'/api/projects/{p}/nodes/{n}/token').status_code == 409
    assert store.runtimes.runtime(a)['state'] == state


def test_runtime_evidence_report_fencing_and_generation_reset(api):
    client, _ = api
    p = project(client)
    a, _, _ = agent(client, p, 'Atlas')
    n, headers, _ = node(client, p)
    configure(client, p, a, n)
    path = f'/api/projects/{p}/agents/{a}'
    run = client.post(f'{path}/launch').json()
    report = {'session_id': SESSION, 'agent_id': a, 'run_id': run['run_id'], 'state': 'unconfirmed',
              'recovery': {'journal': 'missing', 'termination': 'unconfirmed'}}
    evidence = client.post('/api/nodes/me/report', headers=headers, json=report).json()
    assert evidence['last_report_at'] > 0
    assert evidence['recovery'] == report['recovery']
    assert evidence['run_contract'] == run['run_contract']
    assert client.post('/api/nodes/me/report', headers=headers, json={**report, 'run_id': 'run_' + '0' * 32}).status_code == 409
    assert client.post('/api/nodes/me/report', headers=headers, json={**report, 'recovery': {'journal': 'secret contents'}}).status_code == 422
    client.post('/api/nodes/me/report', headers=headers, json={**report, 'state': 'stopped', 'recovery': {'journal': 'available', 'termination': 'confirmed'}})
    fresh = client.post(f'{path}/launch').json()
    assert fresh['run_id'] != run['run_id']
    assert fresh['recovery'] == {} and fresh['last_report_at'] == 0


@pytest.mark.parametrize('mode,has_journal,state,expected', [
    ('managed_api', False, 'unconfirmed', 'missing'),
    ('managed_api', True, 'unconfirmed', 'available'),
    ('managed_cli', False, 'stopped', 'not_applicable'),
])
def test_node_reports_only_bounded_journal_evidence(tmp_path, mode, has_journal, state, expected):
    service = object.__new__(NodeService)
    service.logs, service.children, service.pending_reports = tmp_path, {}, {}
    service.profiles = {'fixture': SimpleNamespace(mode=mode)}
    run = 'run_' + 'a' * 32
    if has_journal:
        write_state(tmp_path / f'{run}.json', {'connector': {'headers': {'Authorization': 'provider-secret'}}, 'confirmed': False})
    service.queue_report({'agent_id': 'peer', 'run_id': run, 'profile_id': 'fixture'}, state)
    payload = service.pending_reports['peer']
    assert payload['recovery']['journal'] == expected
    assert payload['recovery']['termination'] == ('confirmed' if state == 'stopped' else 'unconfirmed')
    assert 'provider-secret' not in json.dumps(payload) and 'connector' not in json.dumps(payload)


def test_sdk_timeout_is_configurable():
    from agentverse import Client
    with Client('http://127.0.0.1', 'test-token', timeout=5) as peer:
        assert peer.http.timeout.read == 5
        assert peer.http.timeout.connect == 5


def test_latest_memory_read_preserves_project_permissions_and_versions(api):
    client, _ = api
    p, other = project(client), project(client, 'Other')
    _, peer_headers, _ = agent(client, p, 'Peer')
    _, outsider_headers, _ = agent(client, other, 'Outside')
    path = f'/api/projects/{p}/memories'
    note = client.post(path, json={'title': 'Compare', 'content': 'Original', 'tags': ['initial']}).json()
    assert client.get(path, headers=peer_headers).json()[0]['version'] == 1
    client.put(f"{path}/{note['id']}", json={'title': 'Compare', 'content': 'Concurrent saved value', 'expected_version': 1})
    assert client.get(path, headers=peer_headers).json()[0]['content'] == 'Concurrent saved value'
    assert client.get(path).json()[0]['version'] == 2
    assert client.get(path, headers=outsider_headers).status_code == 403
    assert client.get(path, headers={'Authorization': 'Bearer invalid'}).status_code == 401
