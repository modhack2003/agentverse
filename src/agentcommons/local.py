"""Local app lifecycle, diagnostics and portable, consistent workspace backups."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile

from .config import VERSION
from .processes import module_command
from .setup import prepare_setup, read_setup


def private_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive(home, name='server'):
    """OS locks release after a crash; stale PID files never kill unrelated processes."""
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / (name + '.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                stream.write(b'0')
                stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError(f'AgentVerse {name} is already running for this workspace.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def available_port(preferred=8000):
    for port in [preferred, *range(8000, 8100)]:
        try:
            with socket.socket() as sock:
                if os.name != 'nt':
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def local_request(home, path, data=None, timeout=3):
    config = read_setup(home)
    request = urllib.request.Request(f"http://127.0.0.1:{config['port']}/api/local/{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': 'Bearer ' + config['admin_token'], 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def status(home):
    if not (home / 'config.json').exists():
        return {'running': False, 'configured': False}
    try:
        result = local_request(home, 'status')
        if result.get('home') != str(home):
            raise ValueError('A different workspace is using this port.')
        return result
    except (OSError, urllib.error.URLError):
        return {'running': False, 'configured': True, 'port': read_setup(home)['port']}


def stop(home):
    state = status(home)
    if not state['running']:
        return state
    local_request(home, 'stop', {})
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if not status(home)['running']:
            try:
                with exclusive(home):
                    return {'running': False, 'configured': True}
            except ValueError:
                pass
        time.sleep(0.15)
    raise ValueError('Server did not stop in time. Check server.log before retrying.')


def start(home, browser=True, port=None):
    config = prepare_setup(home, None)
    if getattr(sys, 'frozen', False) and not (home / 'installation.json').exists():
        private_write(home / 'installation.json', json.dumps({'kind': 'native', 'executable': sys.executable}).encode())
    if status(home)['running']:
        if port is not None and port != config['port']:
            raise ValueError('Stop the app before changing its port.')
        if browser:
            fragment = local_request(home, "setup-link", {})["fragment"] if not config.get("onboarding_complete") else ""
            webbrowser.open(f"http://127.0.0.1:{config['port']}" + fragment)
        return status(home)
    with exclusive(home):
        config = prepare_setup(home, port if port is not None else available_port(config['port']))
    welcome = secrets.token_urlsafe(32) if not config.get('onboarding_complete') else ''
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENTVERSE_', 'AGENTCOMMONS_'))}
    env.update(PYTHON_DOTENV_DISABLED='1', AGENTVERSE_WELCOME_TOKEN=welcome)
    if getattr(sys, 'frozen', False):
        env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    flags = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    log_path = home / 'server.log'
    if log_path.is_symlink():
        raise ValueError('Refusing a symlink for server.log.')
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as log:
        process = subprocess.Popen(module_command('agentcommons.cli', 'serve', '--home', home),
                                   cwd=home, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **flags)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = status(home)
        if state['running']:
            if browser:
                url = f"http://127.0.0.1:{config['port']}"
                if welcome:
                    url += '#setup=' + welcome
                webbrowser.open(url)
            return state
        if process.poll() is not None:
            raise ValueError(f'Server could not start. Read {log_path} for the error.')
        time.sleep(0.1)
    raise ValueError(f'Startup timed out. Read {log_path}; use agentverse status before retrying.')


def backup(home, destination=None):
    config = read_setup(home)
    destination = Path(destination).expanduser().resolve() if destination else home / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3) + '.zip')
    if destination == home / 'config.json' or destination == home / config['database']:
        raise ValueError('Backup destination cannot replace workspace files.')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / 'workspace.db'
        source = home / config['database']
        if source.exists():
            with sqlite3.connect(source) as connection, sqlite3.connect(db_path) as target:
                connection.backup(target)
        else:
            with sqlite3.connect(db_path) as target:
                target.execute('PRAGMA user_version=0')
        payloads = {'config.json': json.dumps(config).encode(), 'workspace.db': db_path.read_bytes()}
        manifest = {'format': 1, 'application_version': VERSION, 'created_at': time.time(),
                    'sha256': {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()}}
        archive = Path(temporary) / 'backup.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for key, value in payloads.items():
                output.writestr(key, value)
            output.writestr('manifest.json', json.dumps(manifest))
        private_write(destination, archive.read_bytes())
    return destination


def restore(home, archive):
    """Validate without extracting arbitrary ZIP paths, and preserve a recovery backup."""
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if {e.filename for e in entries} != {'manifest.json', 'config.json', 'workspace.db'} or len(entries) != 3:
            raise ValueError('This is not an AgentVerse workspace backup.')
        if any(e.file_size > 512 * 1024 * 1024 for e in entries):
            raise ValueError('Backup exceeds the 512 MB per-file restore limit.')
        payloads = {entry.filename: source.read(entry) for entry in entries}
    manifest = json.loads(payloads.pop('manifest.json'))
    if manifest.get('format') != 1 or any(hashlib.sha256(value).hexdigest() != manifest.get('sha256', {}).get(key) for key, value in payloads.items()):
        raise ValueError('Backup integrity check failed.')
    with tempfile.TemporaryDirectory() as temporary:
        check = Path(temporary)
        (check / 'config.json').write_bytes(payloads['config.json'])
        read_setup(check)
        (check / 'workspace.db').write_bytes(payloads['workspace.db'])
        with sqlite3.connect(check / 'workspace.db') as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Backup database is damaged.')
    with exclusive(home):
        previous = backup(home) if (home / 'config.json').exists() else None
        data = home / 'data'
        data.mkdir(exist_ok=True, mode=0o700)
        original_config = (home / 'config.json').read_bytes() if (home / 'config.json').exists() else None
        original_db = (data / 'agentverse.db').read_bytes() if (data / 'agentverse.db').exists() else None
        try:
            private_write(home / 'config.json', payloads['config.json'])
            private_write(data / 'agentverse.db', payloads['workspace.db'])
            for suffix in ('-wal', '-shm'):
                (data / ('agentverse.db' + suffix)).unlink(missing_ok=True)
        except BaseException:
            if original_config is not None:
                private_write(home / 'config.json', original_config)
            if original_db is not None:
                private_write(data / 'agentverse.db', original_db)
            raise
    return {'restored': True, 'recovery_backup': str(previous) if previous else None}


def diagnostics(home, config=None):
    from .node import doctor
    report = doctor(config)
    # Shareable reports omit local paths, tokens, commands, environment and database content.
    for tool in report['tools']:
        tool.pop('executable', None)
    report.pop('home', None)
    for key in ('profiles', 'diagnostics'):
        report.pop(key, None)
    report.update(version=VERSION, local_setup=(home / 'config.json').exists())
    if report['local_setup']:
        state = status(home)
        report.update(server_running=state['running'], port=read_setup(home)['port'])
    report['next_steps'] = [
        'For managed coding work, install Git and prepare a clone with an initial commit.' if not report['git_detected'] else 'Git detected; use node doctor to validate the project clone.',
        'Tool detection does not verify provider login, MCP attachment or model execution. Run a bounded task to verify those separately.',
    ]
    return report


def uninstall(home, delete_data=False):
    read_setup(home)  # Never remove similarly named folders from an unconfigured directory.
    with exclusive(home):
        # Only paths created by the installer; never delete an arbitrary --home recursively.
        for name in ('venv', 'versions'):
            path = home / name
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)
        if delete_data:
            for name in ('data', 'backups'):
                path = home / name
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)
            for name in ('config.json', 'server.log', 'installation.json'):
                (home / name).unlink(missing_ok=True)
    return {'uninstalled': True, 'data_kept': not delete_data}
