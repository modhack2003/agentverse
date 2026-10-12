"""Exercise a portable executable outside the checkout with no Python/Node on PATH."""

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


def managed_node(executable, home, cwd, base, request):
    """Verify the frozen node starts a frozen worker that runs an external coding tool."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENTVERSE_', 'AGENTCOMMONS_'))
           and k not in {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'}}
    repo = cwd / 'managed repo ü'
    repo.mkdir()
    env.update(GIT_AUTHOR_NAME='Portable test', GIT_AUTHOR_EMAIL='portable@example.test',
               GIT_COMMITTER_NAME='Portable test', GIT_COMMITTER_EMAIL='portable@example.test')
    for args in (['init', '--initial-branch=main'], ['commit', '--allow-empty', '-m', 'Initial fixture']):
        subprocess.run(['git', *args], cwd=repo, env=env, check=True, capture_output=True)
    project = request('/api/projects', {'name': 'Portable managed node', 'goal': 'Verify child runtime', 'auto_plan': False})['id']
    peer = request(f'/api/projects/{project}/agents', {'name': 'Managed fixture', 'kind': 'custom'})['agent']['id']
    node = request(f'/api/projects/{project}/nodes', {'name': 'Portable node'})
    trace = cwd / 'native-agent-trace.json'
    env.update(AGENTVERSE_NODE_TOKEN=node['token'], AGENTCOMMONS_TEST_TRACE=str(trace),
               AGENTVERSE_ADMIN_TOKEN='must-not-reach-the-worker', PYTHON_DOTENV_DISABLED='1')
    config = cwd / 'node.json'
    fixture = Path(__file__).parent.resolve() / 'fixtures/controlled_cli.py'
    chat_fixture = Path(__file__).parent.resolve() / 'fixtures/conversation_cli.py'
    config.write_text(json.dumps({'repo': str(repo), 'log_dir': str(cwd / 'node-logs'), 'profiles': [{
        'id': 'fixture', 'name': 'Fixture', 'kind': 'custom', 'argv': [sys.executable, str(fixture), '{prompt_file}', '{model}'],
        'models': [{'id': 'fixture/model', 'name': 'Fixture model'}], 'push': False}, {
        'id': 'chat-fixture', 'name': 'Conversation fixture', 'kind': 'custom',
        'argv': [sys.executable, str(chat_fixture), '{prompt_file}'], 'push': False}]}))
    from agentcommons.processes import start_process, terminate_process
    with (cwd / 'node.log').open('w') as log:
        process = start_process([str(executable), '--internal-module', 'agentcommons.cli', 'node', '--server', base,
                                 '--config', str(config), '--interval', '1'], env=env, cwd=cwd, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while True:
                snapshot = request(f'/api/projects/{project}/snapshot')
                if snapshot['nodes'][0]['online']:
                    break
                assert process.poll() is None, (cwd / 'node.log').read_text(encoding="utf-8")
                assert time.monotonic() < deadline
                time.sleep(.1)
            path = f'/api/projects/{project}/agents/{peer}'
            request(path + '/runtime', {'node_id': node['node']['id'], 'profile_id': 'fixture', 'model': 'fixture/model'}, method='PUT')
            request(f'/api/projects/{project}/tasks', {'title': 'Managed portable fixture task'})
            request(path + '/launch', {})
            deadline = time.monotonic() + 30
            while not trace.exists():
                assert process.poll() is None, (cwd / 'node.log').read_text(encoding="utf-8")
                assert time.monotonic() < deadline, '\n'.join(path.read_text(encoding="utf-8") for path in (cwd / 'node-logs').glob('*.log'))
                time.sleep(.1)
            evidence = json.loads(trace.read_text(encoding="utf-8"))
            assert evidence['argv_model'] == evidence['env_model'] == 'fixture/model'
            assert evidence['admin_token'] is None and evidence['node_token'] is None
            request(path + '/stop', {})
            deadline = time.monotonic() + 30
            while True:
                snapshot = request(f'/api/projects/{project}/snapshot')
                if snapshot['agents'][0]['runtime']['state'] == 'stopped':
                    assert snapshot['tasks'][0]['status'] == 'backlog'
                    break
                assert time.monotonic() < deadline, snapshot
                time.sleep(.1)
            chat_peer = request(f'/api/projects/{project}/agents', {'name': 'Portable chat fixture', 'kind': 'custom'})['agent']['id']
            chat_path = f'/api/projects/{project}/agents/{chat_peer}'
            request(chat_path + '/runtime', {'node_id': node['node']['id'], 'profile_id': 'chat-fixture'}, method='PUT')
            greeting = request(f'/api/projects/{project}/messages', {'content': '@Portable chat fixture hi', 'intent': 'chat'})
            request(chat_path + '/launch', {})
            deadline = time.monotonic() + 30
            while True:
                snapshot = request(f'/api/projects/{project}/snapshot')
                if any(m['reply_to_id'] == greeting['id'] and m['content'] == 'Hello! I can talk with you.' for m in snapshot['messages']):
                    assert next(a for a in snapshot['agents'] if a['id'] == chat_peer)['conversation']['state'] == 'verified'
                    break
                assert time.monotonic() < deadline, snapshot
                time.sleep(.1)
            request(chat_path + '/stop', {})
            print('PASS: frozen node/worker invokes the configured conversation tool and publishes a verified human-visible reply.')
        finally:
            terminate_process(process, grace=10)
    return project


def verify(executable, package_archive=None):
    executable = Path(executable).resolve()
    env = {key: value for key, value in os.environ.items() if not key.startswith(('AGENTVERSE_', 'AGENTCOMMONS_'))
           and key not in {'PYTHONPATH', 'VIRTUAL_ENV', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'}}
    env['PYTHON_DOTENV_DISABLED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    with tempfile.TemporaryDirectory(prefix='agentverse-native-') as temporary:
        cwd = Path(temporary)
        home = (cwd / 'workspace with spaces ü').resolve()
        env['PATH'] = str(cwd)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def run(*args):
            command = [str(executable), *map(str, args)]
            result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout
        run('--help')
        with socket.socket() as occupied:
            if os.name != 'nt':
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                occupied.bind(('127.0.0.1', 8000))
                occupied.listen()
            except OSError:
                # A prior fixture, a Windows reserved port or TIME_WAIT can also
                # prevent binding. The saved-port assertion below still verifies fallback.
                pass
            run('start', '--home', home, '--no-browser')
        shortcut = json.loads(run('shortcut', '--home', home))
        assert Path(shortcut['path']).is_file()
        config = json.loads((home / 'config.json').read_text(encoding="utf-8"))
        assert config['port'] != 8000
        base = f"http://127.0.0.1:{config['port']}"
        def request(path, body=None, token=None, method=None):
            headers = {'Authorization': 'Bearer ' + (token or config['admin_token']), 'Content-Type': 'application/json',
                       'Accept': 'application/json, text/event-stream'}
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
            with opener.open(req, timeout=10) as response:
                return json.loads(response.read())
        try:
            assert request('/api/health')['version'] == '0.4.1'
            with opener.open(base) as response:
                html = response.read().decode()
            assert 'AgentVerse' in html
            for asset in re.findall(r'(?:src|href)="(/(?:assets/[^"\s]+|favicon\.svg|manifest\.webmanifest))"', html):
                with opener.open(base + asset) as response:
                    assert response.status == 200 and response.read()
            fragment = request('/api/local/setup-link', {})['fragment']
            welcomed = request('/api/local/welcome', {'username': 'portable-owner', 'password': 'portable-password-123',
                                'project_name': 'Portable first project'}, fragment.removeprefix('#setup='))
            assert welcomed['token'].startswith('web_')
            project = welcomed['project']['id']
            request(f'/api/projects/{project}/tasks', {'title': 'Portable task'})
            peer = request(f'/api/projects/{project}/agents', {'name': 'Portable peer', 'kind': 'custom'})
            mcp = request('/mcp/', {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'portable-test', 'version': '1'}}}, peer['token'])
            assert mcp['result']['serverInfo']['name'] == 'AgentVerse'
            run('doctor', '--home', home, '--export', cwd / 'diagnostics.json')
            assert config['admin_token'] not in (cwd / 'diagnostics.json').read_text(encoding="utf-8")
            before = json.loads(run('status', '--home', home))
            assert json.loads(run('start', '--home', home, '--no-browser'))['pid'] == before['pid']
            extra_project = managed_node(executable, home, cwd, base, request)
            archive = cwd / 'backup.zip'
            run('backup', '--home', home, '--output', archive)
            with zipfile.ZipFile(archive) as output:
                assert set(output.namelist()) == {'config.json', 'workspace.db', 'manifest.json'}
            request('/api/projects', {'name': 'Later project', 'goal': 'Changed after backup', 'auto_plan': False})
            run('stop', '--home', home)
            run('restore', '--home', home, archive)
            run('start', '--home', home, '--no-browser')
            assert {row['id'] for row in request('/api/projects')} == {project, extra_project}
            assert request(f'/api/projects/{project}/tasks')[0]['title'] == 'Portable task'
            assert request('/api/login', {'username': 'portable-owner', 'password': 'portable-password-123'})['token'].startswith('web_')
            run('restart', '--home', home, '--no-browser')
            assert json.loads(run('status', '--home', home))['running']
        finally:
            run('stop', '--home', home)
        assert not json.loads(run('status', '--home', home))['running']
        if package_archive:
            import hashlib
            archive = Path(package_archive).resolve()
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            run('update', '--home', home, '--source', archive, '--sha256', digest)
            metadata = json.loads((home / 'installation.json').read_text(encoding="utf-8"))
            assert metadata['previous']['kind'] == 'native'
            assert Path(metadata['executable']).exists() and Path(metadata['recovery_backup']).exists()
            launcher = home / ('agentverse.cmd' if os.name == 'nt' else 'agentverse')
            launcher_command = [str(launcher), 'status']
            if os.name == 'nt':
                launcher_command = [str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/cmd.exe'), '/c', *launcher_command]
            selected = json.loads(subprocess.check_output(launcher_command, cwd=cwd, env=env, text=True, encoding='utf-8'))
            assert selected['home'] == str(home) and selected['configured'], selected
            run('rollback', '--home', home)
            assert json.loads((home / 'installation.json').read_text(encoding="utf-8"))['executable'] == str(executable)
        if package_archive:
            # Exercise uninstall from a selected runtime, including Windows loaded-file cleanup.
            result = subprocess.run([metadata['executable'], 'uninstall', '--home', str(home)], cwd=cwd,
                                    env=dict(env, AGENTVERSE_REDIRECTED='1'), text=True, encoding='utf-8',
                                    capture_output=True, timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
            deadline = time.monotonic() + 45
            while (home / 'versions').exists():
                log = home / 'uninstall-cleanup.log'
                assert time.monotonic() < deadline, 'Deferred runtime removal did not finish. ' + (log.read_text(errors='replace') if log.exists() else 'No cleanup log.')
                time.sleep(.1)
        else:
            run('uninstall', '--home', home)
        assert (home / 'config.json').exists() and (home / 'data/agentverse.db').exists()
        print('PASS: portable runtime without Python/Node/Git on PATH; occupied port, first-run password/project, dashboard assets, peer/MCP, background lifecycle, restart persistence, diagnostics, backup/restore and data-preserving uninstall.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--archive', help='Also verify a checksum-protected update and rollback')
    args = parser.parse_args()
    verify(args.executable, args.archive)
