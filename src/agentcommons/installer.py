#!/usr/bin/env python3
"""Install a stable AgentVerse release, including its dashboard, into an isolated environment."""

import argparse
from contextlib import ExitStack, contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
import zipfile

VERSION = '0.4.1'
SOURCE = f'https://github.com/modhack2003/agentverse/archive/refs/tags/v{VERSION}.zip'


@contextmanager
def installation_lock(home, name):
    path = home / (name + '.lock')
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), 'r+b', buffering=0) as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b'0')
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Stop the app and any other installer before updating this workspace.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def python_at(environment):
    return environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def atomic_write(path, content):
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6))
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def snapshot(home):
    """Consistent pre-upgrade backup, including for older installations."""
    if not (home / 'config.json').exists():
        return None
    config = json.loads((home / 'config.json').read_text(encoding='utf-8'))
    path = home / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-pre-update-' + secrets.token_hex(3) + '.zip')
    path.parent.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / 'workspace.db'
        source = home / 'data/agentverse.db'
        with closing(sqlite3.connect(target)) as output:
            if source.exists():
                with closing(sqlite3.connect(source)) as db:
                    db.backup(output)
        payloads = {'config.json': json.dumps(config).encode(), 'workspace.db': target.read_bytes()}
        manifest = {'format': 1, 'application_version': VERSION, 'created_at': time.time(),
                    'sha256': {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()}}
        archive = Path(temporary) / 'backup.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for name, content in payloads.items():
                output.writestr(name, content)
            output.writestr('manifest.json', json.dumps(manifest))
        atomic_write(path, archive.read_bytes())
    return path


def reject_running(home):
    path = home / 'config.json'
    if not path.exists():
        return
    config = json.loads(path.read_text(encoding='utf-8'))
    request = urllib.request.Request(f"http://127.0.0.1:{config['port']}/api/me",
        headers={'Authorization': 'Bearer ' + config['admin_token']})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            if response.status == 200:
                raise ValueError('Stop the running app before updating: agentverse stop --home ' + str(home))
    except urllib.error.HTTPError:
        pass
    except (urllib.error.URLError, OSError):
        pass


def write_launcher(home, python):
    args = [str(python), '-m', 'agentcommons.cli']
    if os.name == 'nt':
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        content = '$env:AGENTVERSE_HOME = ' + quote(home) + '\n& ' + ' '.join(quote(value) for value in args) + ' @args\n'
        atomic_write(home / 'agentverse.ps1', content.encode('utf-8-sig'))
        batch = '@echo off\n"%SystemRoot%\\System32\\chcp.com" 65001 >nul\nsetlocal DisableDelayedExpansion\nset \"AGENTVERSE_HOME=' + str(home).replace('%', '%%') + '\"\n' + subprocess.list2cmdline(args).replace('%', '%%') + ' %*\n'
        atomic_write(home / 'agentverse.cmd', batch.replace('\n', '\r\n').encode())
    else:
        content = '#!/bin/sh\nexport AGENTVERSE_HOME=' + shlex.quote(str(home)) + '\nexec ' + shlex.join(args) + ' "$@"\n'
        path = home / 'agentverse'
        atomic_write(path, content.encode())
        path.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home() / '.agentverse')
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--source', default=SOURCE, help='Trusted package archive, local wheel, or source directory')
    parser.add_argument('--wheelhouse', type=Path, help='Install offline from a complete directory of dependency wheels')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required, or use a portable native download.')
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('Port must be from 1 to 65535.')
    home = args.home.expanduser().resolve()
    environment = None
    committed = False
    locks = ExitStack()
    try:
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        locks.enter_context(installation_lock(home, "update"))
        locks.enter_context(installation_lock(home, "server"))
        reject_running(home)
        previous_path = home / 'installation.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
        if not previous and python_at(home / 'venv').exists():
            previous = {'kind': 'python', 'python': str(python_at(home / 'venv'))}
        recovery = snapshot(home)
        environment = home / 'versions' / ('python-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
        print(f'Creating a fresh environment in {environment}', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
        python = python_at(environment)
        command = [str(python), '-m', 'pip', 'install', args.source]
        if args.wheelhouse:
            command += ['--no-index', '--find-links', str(args.wheelhouse.expanduser().resolve())]
        subprocess.run(command, check=True)
        subprocess.run([str(python), '-c', 'from agentcommons.server import create_app; from agentcommons.setup import prepare_setup; from pathlib import Path; import agentcommons; assert (Path(agentcommons.__file__).parent / "web/index.html").is_file()'], check=True)
        setup_env = dict(os.environ, PYTHON_DOTENV_DISABLED='1')
        setup = [str(python), '-m', 'agentcommons.cli', 'setup', '--home', str(home), '--no-start']
        if args.port is not None:
            setup += ['--port', str(args.port)]
        subprocess.run(setup, check=True, env=setup_env)
        metadata = {'kind': 'python', 'python': str(python), 'previous': previous, 'recovery_backup': str(recovery) if recovery else None}
        atomic_write(previous_path, json.dumps(metadata, indent=2).encode())
        committed = True
        write_launcher(home, python)
        print(f'Installed. Your persistent launcher is {home / ("agentverse.cmd" if os.name == "nt" else "agentverse")}', flush=True)
        if recovery:
            print(f'Pre-update backup: {recovery}', flush=True)
        locks.close()
        if not args.no_start:
            launch = [str(python), '-m', 'agentcommons.cli', 'launch', '--home', str(home)]
            if args.no_browser:
                launch += ['--no-browser']
            subprocess.run(launch, check=True, env=setup_env)
    except KeyboardInterrupt:
        print('\nStopped. Workspace files are kept. Rerun the installer to continue.')
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Installation/setup did not complete: {exc}', file=sys.stderr)
        print('Existing credentials and database are preserved. If Python venv is missing on Debian/Ubuntu, install python3-venv.', file=sys.stderr)
        return 1
    finally:
        locks.close()
        if environment and not committed and environment.exists():
            shutil.rmtree(environment)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
