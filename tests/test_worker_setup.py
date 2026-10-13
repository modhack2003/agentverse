import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from agentcommons.processes import start_process, terminate_process
from agentcommons.worker import Worker, execute_agent
from agentcommons.worker_setup import load_command
from conftest import agent, project


def repository(path):
    path.mkdir()
    for args in (['init', '--initial-branch=main'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                                                 'commit', '--allow-empty', '-m', 'Initial']):
        subprocess.run(['git', *args], cwd=path, check=True, capture_output=True)
    return path


def test_command_json_preserves_unicode_spaces_and_literal_shell_arguments(tmp_path):
    folder = tmp_path / 'tool folder ü'
    folder.mkdir()
    script = folder / 'model tool.py'
    script.write_text('import sys,json\nfrom pathlib import Path\nprint(json.dumps({"reply":Path(sys.argv[1]).read_text(encoding="utf-8"),"argv":sys.argv[2:]},ensure_ascii=False))', encoding='utf-8')
    path = tmp_path / 'command.json'
    args = [sys.executable, str(script), '{prompt_file}', 'C:\\Projects\\my repo\\工作', '$() ; & literal']
    path.write_text(json.dumps(args, ensure_ascii=False), encoding='utf-8-sig')
    result = execute_agent(load_command(path), 'Prompt with 工作 and ü', tmp_path, 10)
    assert result == {'reply': 'Prompt with 工作 and ü', 'argv': args[3:]}
    for value in ({'argv': args}, [], [''], [1], ['tool', '\0']):
        path.write_text(json.dumps(value), encoding='utf-8')
        with pytest.raises(ValueError):
            load_command(path)


def test_preflight_checks_identity_base_and_tool_without_announcing_or_claiming(live_server, tmp_path):
    url, admin = live_server
    p = project(admin)
    a, _, token = agent(admin, p, 'Setup check')
    repo = repository(tmp_path / 'repo with spaces ü')
    command = tmp_path / 'argv.json'
    command.write_text(json.dumps([sys.executable, 'not-invoked.py', '{prompt_file}']), encoding='utf-8')
    env = {**os.environ, 'AGENTVERSE_AGENT_TOKEN': token, 'PYTHON_DOTENV_DISABLED': '1'}
    args = [sys.executable, '-m', 'agentcommons.cli', 'worker', '--server', url, '--repo', str(repo),
            '--command-file', str(command), '--expected-agent', a, '--expected-project', p, '--check']
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['agent_id'] == a and report['project_id'] == p and 'model execution' in report['unverified']
    snapshot = admin.get(f'/api/projects/{p}/snapshot').json()
    assert not snapshot['agents'][0]['online'] and snapshot['agents'][0]['conversation']['state'] == 'not_listening'
    assert snapshot['messages'] == [] and snapshot['tasks'] == []
    bad = args.copy()
    bad[bad.index('--expected-agent') + 1] = 'another-agent'
    mismatch = subprocess.run(bad, env=env, capture_output=True, text=True, timeout=15)
    assert mismatch.returncode != 0 and 'different teammate or project' in mismatch.stderr and token not in mismatch.stderr
    bad = args + ['--base', 'missing-base']
    assert subprocess.run(bad, env=env, capture_output=True, timeout=15).returncode != 0
    command.write_text(json.dumps(['agentverse-test-missing-tool', '{prompt_file}']))
    missing = subprocess.run(args, env=env, capture_output=True, text=True, timeout=15)
    assert missing.returncode != 0 and 'executable is missing' in missing.stderr


def test_persistent_cli_command_file_answers_two_human_messages(live_server, tmp_path):
    url, admin = live_server
    p = project(admin)
    a, _, token = agent(admin, p, 'Prompt worker')
    repo = repository(tmp_path / 'persistent repo ü')
    command = tmp_path / 'agentverse-command.json'
    command.write_text(json.dumps([sys.executable, str(Path(__file__).parent / 'fixtures/conversation_cli.py'), '{prompt_file}']))
    env = {**os.environ, 'AGENTVERSE_AGENT_TOKEN': token, 'PYTHON_DOTENV_DISABLED': '1'}
    with (tmp_path / 'worker.log').open('w') as log:
        process = start_process([sys.executable, '-m', 'agentcommons.cli', 'worker', '--server', url, '--repo', str(repo),
            '--command-file', str(command), '--expected-agent', a, '--expected-project', p, '--no-push', '--interval', '1'],
            env=env, stdout=log, stderr=log)
        try:
            for content in ['hi', 'can we talk?']:
                sent = admin.post(f'/api/projects/{p}/messages', json={'content': content, 'intent': 'chat'}).json()
                deadline = time.monotonic() + 20
                while True:
                    rows = admin.get(f'/api/projects/{p}/messages').json()
                    if any(m['reply_to_id'] == sent['id'] and m['sender_id'] == a for m in rows):
                        break
                    assert process.poll() is None, (tmp_path / 'worker.log').read_text()
                    assert time.monotonic() < deadline, rows
                    time.sleep(.05)
            snapshot = admin.get(f'/api/projects/{p}/snapshot').json()
            assert snapshot['agents'][0]['conversation']['state'] == 'verified'
            assert snapshot['tasks'] == [] and len(snapshot['messages']) == 4
            auth = {'Authorization': f'Bearer {token}'}
            admin.post('/api/agents/heartbeat', headers=auth, json={'status': 'offline'})
            assert admin.post('/api/agents/chat/register', headers=auth, json={'session_id': 'd' * 32}).status_code == 200
            assert process.wait(timeout=10) == 0
            assert admin.get(f'/api/projects/{p}/snapshot').json()['agents'][0]['conversation']['state'] == 'listening'
        finally:
            terminate_process(process, grace=10)


def test_failed_task_reports_redact_provider_and_agent_credentials(live_server, tmp_path, monkeypatch):
    url, admin = live_server
    p = project(admin)
    _, _, token = agent(admin, p, 'Broken provider')
    repo = repository(tmp_path / 'repo')
    script = tmp_path / 'failed_tool.py'
    script.write_text('import os,sys\nprint("Provider login failed: " + os.environ["TEST_PROVIDER_API_KEY"] + " " + os.environ["AGENTVERSE_AGENT_TOKEN"])\nsys.exit(1)')
    secret = 'synthetic-secret-that-must-stay-private'
    monkeypatch.setenv('TEST_PROVIDER_API_KEY', secret)
    admin.post(f'/api/projects/{p}/tasks', json={'title': 'Check failure'})
    with pytest.raises(RuntimeError):
        Worker(url, token, repo, [sys.executable, str(script), '{prompt_file}'], push=False).run(once=True)
    snapshot = admin.get(f'/api/projects/{p}/snapshot').json()
    assert snapshot['tasks'][0]['status'] == 'backlog'
    text = json.dumps(snapshot)
    assert 'Provider login failed' in text and secret not in text and token not in text


def test_conflicting_worker_cannot_mark_the_existing_listener_offline(live_server, tmp_path):
    url, admin = live_server
    p = project(admin)
    _, _, token = agent(admin, p, 'Existing listener')
    auth = {'Authorization': f'Bearer {token}'}
    session = 'e' * 32
    admin.post('/api/agents/chat/register', headers=auth, json={'session_id': session})
    repo = repository(tmp_path / 'repo')
    with pytest.raises(RuntimeError, match='Another conversation listener is active'):
        Worker(url, token, repo, [sys.executable, 'not-invoked.py']).run(once=True)
    snapshot = admin.get(f'/api/projects/{p}/snapshot').json()
    assert snapshot['agents'][0]['conversation']['state'] == 'listening'
    assert admin.post('/api/agents/chat/heartbeat', headers=auth, json={'session_id': session}).status_code == 200
