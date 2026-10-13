"""Onboarding, consistent backups, safe restore and managed process cleanup."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from agentcommons.local import backup, diagnostics, exclusive, restore, uninstall
from agentcommons.passwords import verify_password
from agentcommons.processes import start_process, terminate_process
from agentcommons.server import create_app
from agentcommons.setup import prepare_setup, read_setup
from agentcommons.updates import unpack
from conftest import project


@pytest.fixture
def local_app(tmp_path, monkeypatch):
    home = tmp_path / 'workspace with spaces ü'
    config = prepare_setup(home)
    secret = 'first-run-private-capability'
    monkeypatch.setenv('AGENTVERSE_WELCOME_TOKEN', secret)
    app = create_app(str(home / config['database']), config['admin_token'], local_home=home)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        yield home, config, secret, client, app


def test_welcome_is_private_one_time_and_password_survives_restart(local_app, monkeypatch):
    home, config, secret, client, app = local_app
    body = {'username': 'owner', 'password': 'a-long-password-123', 'project_name': 'My first project'}
    assert client.post('/api/local/welcome', json=body).status_code == 401
    headers = {'Authorization': 'Bearer ' + secret}
    response = client.post('/api/local/welcome', json=body, headers=headers)
    assert response.status_code == 200, response.text
    session = response.json()['token']
    assert session.startswith('web_') and session != config['admin_token']
    assert client.get('/api/me', headers={'Authorization': 'Bearer ' + session}).json()['admin']
    saved = read_setup(home)
    assert body['password'] not in (home / 'config.json').read_text()
    assert verify_password(body['password'], saved['login']['password_hash'])
    assert not verify_password('incorrect', saved['login']['password_hash'])
    assert client.post('/api/local/welcome', json=body, headers=headers).status_code == 401
    assert client.get('/api/local/onboarding').json()['available'] is False
    assert client.get('/api/projects', headers={'Authorization': 'Bearer ' + session}).json()[0]['name'] == body['project_name']
    # Read saved hashed credentials into a newly constructed server.
    another = create_app(str(home / config['database']), config['admin_token'], local_home=home)
    with TestClient(another) as restarted:
        assert restarted.post('/api/login', json={'username': 'owner', 'password': body['password']}).status_code == 200
        assert restarted.post('/api/login', json={'username': 'owner', 'password': 'wrong'}).status_code == 401


def test_setup_link_reissue_and_admin_only_maintenance(local_app):
    home, config, secret, client, app = local_app
    auth = {'Authorization': 'Bearer ' + config['admin_token']}
    assert client.post('/api/local/setup-link').status_code == 401
    replacement = client.post('/api/local/setup-link', headers=auth, json={}).json()['fragment'].removeprefix('#setup=')
    assert replacement != secret
    assert client.post('/api/local/welcome', headers={'Authorization': 'Bearer ' + secret}, json={'username': 'owner', 'password': 'long-enough-password'}).status_code == 401
    assert client.get('/api/local/diagnostics').status_code == 401
    report = client.get('/api/local/diagnostics', headers=auth).json()
    assert config['admin_token'] not in json.dumps(report) and str(home) not in json.dumps(report)
    response = client.get('/api/local/backup', headers=auth)
    assert response.status_code == 200 and response.headers['content-type'] == 'application/zip'
    assert client.post('/api/local/stop', headers=auth, json={}).status_code == 409


def test_live_database_backup_restore_is_consistent_and_preserves_recovery(local_app, tmp_path):
    home, config, secret, client, app = local_app
    client.headers['Authorization'] = 'Bearer ' + config['admin_token']
    first = project(client, 'Before backup')
    archive = backup(home)
    project(client, 'After backup')
    # Runtime lock is the authoritative guard even if the HTTP port is unreachable.
    with exclusive(home):
        with pytest.raises(ValueError, match='already running'):
            restore(home, archive)
    # Store connection remains open in this fixture; real restore requires the launcher stopped.
    app.state.store.close()
    result = restore(home, archive)
    assert Path(result['recovery_backup']).exists()
    another = create_app(str(home / config['database']), config['admin_token'], local_home=home)
    with TestClient(another, headers={'Authorization': 'Bearer ' + config['admin_token']}) as restored:
        assert [p['id'] for p in restored.get('/api/projects').json()] == [first]


def test_reject_corrupt_and_traversal_backup_before_changing_workspace(tmp_path):
    home = tmp_path / 'home'
    config = prepare_setup(home)
    archive = backup(home)
    with zipfile.ZipFile(archive) as source:
        content = {name: source.read(name) for name in source.namelist()}
    content['config.json'] = b'corrupted'
    with zipfile.ZipFile(archive, 'w') as target:
        for name, value in content.items():
            target.writestr(name, value)
    with pytest.raises(ValueError, match='integrity'):
        restore(home, archive)
    assert read_setup(home) == config
    with zipfile.ZipFile(archive, 'w') as target:
        target.writestr('../outside', b'bad')
    with pytest.raises(ValueError, match='not an AgentVerse'):
        restore(home, archive)
    with pytest.raises(ValueError, match='Unsafe'):
        unpack(archive, tmp_path / 'extracted')
    assert not (tmp_path / 'outside').exists()


def test_uninstall_keeps_data_and_does_not_remove_unrelated_files(tmp_path):
    config = prepare_setup(tmp_path)
    (tmp_path / 'unrelated.txt').write_text('keep')
    (tmp_path / 'versions').mkdir()
    (tmp_path / 'versions/app').write_text('app')
    assert uninstall(tmp_path)['data_kept']
    assert read_setup(tmp_path) == config
    assert not (tmp_path / 'versions').exists()
    assert uninstall(tmp_path, delete_data=True)['data_kept'] is False
    assert (tmp_path / 'unrelated.txt').read_text() == 'keep'


@pytest.mark.parametrize('ending', ['leader_exit', 'stop', 'timeout'])
def test_process_tree_cleanup_on_every_platform(tmp_path, ending):
    # The parent may exit before cleanup; descendants must still be stopped.
    marker = tmp_path / 'heartbeat.txt'
    child = f"import time,pathlib\nwhile True:\n pathlib.Path({str(marker)!r}).write_text(str(time.time()))\n time.sleep(.03)"
    code = f"import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c',{child!r}])\ntime.sleep(.4)\n" + ('' if ending == 'leader_exit' else 'time.sleep(60)')
    process = start_process([sys.executable, '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(.03)
        if ending == 'leader_exit':
            process.wait(timeout=10)
        elif ending == 'timeout':
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=.1)
        terminate_process(process, grace=.2)
        before = marker.read_text()
        time.sleep(.2)
        assert marker.read_text() == before
    finally:
        terminate_process(process, grace=.1)


def test_installer_source_and_package_copy_match():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'install.py').read_bytes() == (root / 'src/agentcommons/installer.py').read_bytes()
    from agentcommons.installer import SOURCE
    assert '/refs/tags/' in SOURCE


@pytest.mark.skipif(os.name == 'nt', reason='Darwin/POSIX process-group behavior')
@pytest.mark.parametrize('state', ['zombie', 'live', 'unknown'])
def test_macos_group_permission_error_requires_positive_death_evidence(monkeypatch, state):
    from agentcommons import processes
    process = start_process([sys.executable, '-c', 'pass'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.wait(timeout=10)
    monkeypatch.setattr(processes.sys, 'platform', 'darwin')

    def denied(*_):
        raise PermissionError('Simulated Darwin group signal rejection')

    monkeypatch.setattr(processes.os, 'killpg', denied)
    output = f'{process.pid} {process.pid} ' + ('Z' if state == 'zombie' else 'S') + '\n'
    monkeypatch.setattr(processes, 'external_run', lambda *_, **kwargs: subprocess.CompletedProcess([], 1 if state == 'unknown' else 0, output, ''))
    if state == 'zombie':
        terminate_process(process, grace=.1)
    else:
        with pytest.raises(PermissionError):
            terminate_process(process, grace=.1)


def test_diagnostic_export_contains_no_environment_secrets(tmp_path, monkeypatch):
    config = prepare_setup(tmp_path)
    monkeypatch.setenv('PRIVATE_PROVIDER_KEY', 'must-not-export')
    report = json.dumps(diagnostics(tmp_path))
    assert 'must-not-export' not in report and config['admin_token'] not in report
    assert str(tmp_path) not in report


def test_bounded_connection_checks_do_not_take_over_nodes(live_server):
    from agentcommons.connection_check import check
    from conftest import agent, project
    from test_remote_control import node
    url, client = live_server
    p = project(client)
    _, _, token = agent(client, p, 'Diagnostics peer')
    assert check(url, token, mcp=True)['ok']
    assert not check(url, 'invalid')['ok']
    node_id, headers, node_token = node(client, p)
    assert check(url, node_token, node=True)['ok']
    before = client.get(f'/api/projects/{p}/snapshot').json()['nodes'][0]
    assert before['id'] == node_id
    assert client.post('/api/nodes/me/poll', headers=headers, json={'session_id': 'a' * 32}).status_code == 200
    assert not check('http://127.0.0.1:1', token)['ok']
    with pytest.raises(ValueError, match='without embedded'):
        check('https://user:secret@example.test', token)


def test_frozen_external_programs_receive_original_library_paths(monkeypatch):
    from agentcommons.processes import external_environment
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    report = external_environment({'LD_LIBRARY_PATH': '/bundled/lib', 'LD_LIBRARY_PATH_ORIG': '/tools/lib',
                                   '_PYI_ARCHIVE_FILE': 'internal', 'MODEL_API_KEY': 'keep-for-tool'})
    assert report['LD_LIBRARY_PATH'] == '/tools/lib'
    assert '_PYI_ARCHIVE_FILE' not in report
    assert report['MODEL_API_KEY'] == 'keep-for-tool'
    assert 'LD_LIBRARY_PATH' not in external_environment({'LD_LIBRARY_PATH': '/bundled/lib'})


def test_uninstall_refuses_unconfigured_directory(tmp_path):
    (tmp_path / 'versions').mkdir()
    (tmp_path / 'versions/unrelated').write_text('keep')
    with pytest.raises(FileNotFoundError):
        uninstall(tmp_path, delete_data=True)
    assert (tmp_path / 'versions/unrelated').read_text() == 'keep'


def test_unicode_node_config_and_worker_prompt(tmp_path):
    import shlex
    from agentcommons.node import load_config
    from agentcommons.worker import execute_agent
    path = tmp_path / 'node.json'
    path.write_text(json.dumps({'repo': 'C:/工作/项目', 'profiles': [{'id': 'peer', 'name': 'Peer', 'kind': 'custom', 'mode': 'connected'}]}, ensure_ascii=False), encoding='utf-8')
    assert load_config(path).repo == 'C:/工作/项目'
    script = tmp_path / 'cli.py'
    script.write_text('import sys,json\nfrom pathlib import Path\nprompt=Path(sys.argv[1]).read_text(encoding="utf-8")\nprint(json.dumps({"summary":prompt},ensure_ascii=False))\n', encoding='utf-8')
    phrase = 'বাংলা 中文 🚀'
    assert execute_agent(shlex.join([sys.executable, str(script), '{prompt_file}']), phrase, tmp_path, 10)['summary'] == phrase


def test_startup_uses_persistent_workspace_launcher(tmp_path):
    tmp_path = tmp_path.resolve()
    import os
    from agentcommons.startup import launch_command
    prepare_setup(tmp_path)
    command = launch_command(tmp_path, 'status')
    assert command[0] == str(tmp_path / ('agentverse.cmd' if os.name == 'nt' else 'agentverse'))
    if os.name == 'nt':
        command = [str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/cmd.exe'), '/c', *command]
    result = subprocess.check_output(command, text=True, encoding='utf-8')
    assert json.loads(result)['home'] == str(tmp_path)
    assert json.loads((tmp_path / 'installation.json').read_text())['python'] == sys.executable
