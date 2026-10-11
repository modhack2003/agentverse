"""Stable updates with side-by-side installs, checksum checks and rollback."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

from .local import backup, exclusive, private_write, status
from .processes import module_command

RELEASE_API = 'https://api.github.com/repos/modhack2003/agentverse/releases/latest'


def platform_key():
    system = {'win32': 'windows', 'darwin': 'macos'}.get(sys.platform, 'linux')
    machine = platform.machine().lower()
    architecture = 'arm64' if machine in {'arm64', 'aarch64'} else 'x64' if machine in {'x86_64', 'amd64'} else machine
    return system + '-' + architecture


def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'AgentVerse-updater'}), timeout=20) as response:
        return json.loads(response.read(2 * 1024 * 1024))


def latest():
    release = fetch_json(RELEASE_API)
    manifest = next((asset for asset in release.get('assets', []) if asset['name'] == 'agentverse-manifest.json'), None)
    if not manifest:
        raise ValueError('Latest release has no verified portable manifest yet. Download a release manually or retry after the build finishes.')
    return fetch_json(manifest['browser_download_url'])


def unpack(archive, target):
    """No traversal, symlinks, devices or unexpectedly large extracted archives."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if sum(entry.file_size for entry in entries) > 2 * 1024**3:
                raise ValueError('Portable archive exceeds the extraction limit.')
            for entry in entries:
                path = Path(entry.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unsafe archive entry.')
            source.extractall(target)
    else:
        with tarfile.open(archive) as source:
            entries = source.getmembers()
            if sum(entry.size for entry in entries) > 2 * 1024**3:
                raise ValueError('Portable archive exceeds the extraction limit.')
            if any(not (entry.isfile() or entry.isdir()) or Path(entry.name).is_absolute() or '..' in Path(entry.name).parts for entry in entries):
                raise ValueError('Unsafe archive entry.')
            source.extractall(target, filter='data')


def update(home, source=None, checksum=None):
    if status(home)['running']:
        raise ValueError('Stop AgentVerse before updating; use agentverse stop.')
    if not getattr(sys, 'frozen', False):
        command = module_command('agentcommons.installer', '--home', home, '--no-start')
        if not source:
            import re
            version = latest().get('version', '')
            if not re.fullmatch(r'\d+\.\d+\.\d+', version):
                raise ValueError('Stable release manifest contains an invalid version.')
            source = f'https://github.com/modhack2003/agentverse/archive/refs/tags/v{version}.zip'
        command += ['--source', source]
        subprocess.run(command, check=True)
        return {'updated': True, 'launcher': str(home / ('agentverse.cmd' if os.name == 'nt' else 'agentverse'))}
    with exclusive(home), exclusive(home, 'update'):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            if source:
                archive = Path(source).expanduser().resolve()
                if not checksum:
                    raise ValueError('Use --sha256 with a manually supplied portable update archive.')
            else:
                manifest = latest()
                asset = manifest.get('platforms', {}).get(platform_key())
                if not asset:
                    raise ValueError(f'No portable release for {platform_key()}.')
                checksum = asset['sha256']
                archive = temporary / asset['name']
                with urllib.request.urlopen(asset['url'], timeout=60) as response, archive.open('wb') as out:
                    shutil.copyfileobj(response, out)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
                raise ValueError('Update checksum mismatch. No installation files were changed.')
            recovery = backup(home)
            staged = temporary / 'unpacked'
            unpack(archive, staged)
            suffix = '.exe' if os.name == 'nt' else ''
            executable = next(staged.glob('agentverse/agentverse' + suffix), None)
            if executable is None:
                raise ValueError('Archive does not contain the expected portable executable.')
            validation_env = dict(os.environ, AGENTVERSE_REDIRECTED='1', PYINSTALLER_RESET_ENVIRONMENT='1')
            subprocess.run([str(executable), '--help'], check=True, capture_output=True, env=validation_env)
            version = hashlib.sha256(archive.read_bytes()).hexdigest()[:16]
            destination = home / 'versions' / ('native-' + version)
            if destination.exists():
                raise ValueError('This portable version is already installed.')
            destination.parent.mkdir(exist_ok=True)
            shutil.copytree(executable.parent, destination)
            previous_path = home / 'installation.json'
            previous = json.loads(previous_path.read_text()) if previous_path.exists() else {'kind': 'native', 'executable': sys.executable}
            metadata = {'kind': 'native', 'executable': str(destination / executable.name), 'previous': previous, 'recovery_backup': str(recovery)}
            private_write(previous_path, json.dumps(metadata).encode())
            write_native_launcher(home, metadata['executable'])
            return {'updated': True, 'launcher': str(home / ('agentverse.cmd' if os.name == 'nt' else 'agentverse')), 'backup': str(recovery)}


def write_native_launcher(home, executable):
    import shlex
    if os.name == 'nt':
        text = "$env:AGENTVERSE_HOME = '" + str(home).replace("'", "''") + "'\n& '" + executable.replace("'", "''") + "' @args\n"
        private_write(home / 'agentverse.ps1', text.encode('utf-8-sig'))
        batch = '@echo off\nchcp 65001 >nul\nsetlocal DisableDelayedExpansion\nset \"AGENTVERSE_HOME=' + str(home).replace('%', '%%') + '\"\n' + subprocess.list2cmdline([executable]).replace('%', '%%') + ' %*\n'
        private_write(home / 'agentverse.cmd', batch.replace('\n', '\r\n').encode())
    else:
        path = home / 'agentverse'
        private_write(path, ('#!/bin/sh\nexport AGENTVERSE_HOME=' + shlex.quote(str(home)) + '\nexec ' + shlex.quote(executable) + ' "$@"\n').encode())
        path.chmod(0o700)


def rollback(home):
    with exclusive(home):
        path = home / 'installation.json'
        current = json.loads(path.read_text())
        previous = current.get('previous')
        if not previous:
            raise ValueError('No previous installation is available.')
        if previous['kind'] == 'python':
            from .installer import write_launcher
            executable = Path(previous['python'])
            command = [str(executable), '-m', 'agentcommons.cli', '--help']
        else:
            executable = Path(previous['executable'])
            command = [str(executable), '--help']
        subprocess.run(command, check=True, capture_output=True, env=dict(os.environ, AGENTVERSE_REDIRECTED="1", PYINSTALLER_RESET_ENVIRONMENT="1"))
        backup(home)
        if previous['kind'] == 'python':
            write_launcher(home, executable)
        else:
            write_native_launcher(home, str(executable))
        private_write(path, json.dumps(previous).encode())
        return {'rolled_back': True, 'data_preserved': True, 'pre_update_backup': current.get('recovery_backup'),
                'note': 'Application version changed. If an older version cannot read the database, restore the recorded pre-update backup before starting.'}
