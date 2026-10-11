"""Per-user desktop shortcuts and optional native login/background startup."""

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys

from .local import private_write
from .processes import external_run


def identifier(home):
    return 'agentverse-' + hashlib.sha256(str(home).encode()).hexdigest()[:12]


def launch_command(home, action):
    """Shortcuts and services follow the selected version through one stable file."""
    metadata_path = home / 'installation.json'
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    else:
        metadata = {'kind': 'native', 'executable': sys.executable} if getattr(sys, 'frozen', False) else {'kind': 'python', 'python': sys.executable}
        private_write(metadata_path, json.dumps(metadata).encode())
    if metadata.get('kind') == 'native' and metadata.get('executable'):
        from .updates import write_native_launcher
        write_native_launcher(home, metadata['executable'])
    elif metadata.get('kind') == 'python' and metadata.get('python'):
        from .installer import write_launcher
        write_launcher(home, Path(metadata['python']))
    else:
        raise ValueError('Installation selection is damaged. Rerun the installer to restore the launcher; your data is kept.')
    launcher = home / ('agentverse.cmd' if os.name == 'nt' else 'agentverse')
    return [str(launcher), action, '--home', str(home)]


def desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def shortcut(home, autostart=False, remove=False):
    name = identifier(home)
    argv = launch_command(home, 'launch') if not remove else []
    if autostart:
        argv += ['--no-browser']
    if os.name == 'nt':
        folder = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs'
        if autostart:
            folder /= 'Startup'
        path = folder / (name + '.lnk')
        if remove:
            path.unlink(missing_ok=True)
            return path
        folder.mkdir(parents=True, exist_ok=True)
        # Pass values as JSON on stdin, never interpolate credentials or user paths into PowerShell code.
        script = "$v = [Console]::In.ReadToEnd() | ConvertFrom-Json; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($v.path); $s.TargetPath = $v.target; $s.Arguments = $v.arguments; $s.WorkingDirectory = $v.cwd; $s.Save()"
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        external_run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                       input=json.dumps({'path': str(path), 'target': argv[0],
                                         'arguments': subprocess.list2cmdline(argv[1:]), 'cwd': str(home)}),
                       text=True, check=True, capture_output=True)
    elif sys.platform == 'darwin':
        if autostart:
            path = Path.home() / 'Library/LaunchAgents' / (name + '.plist')
            if remove:
                if path.exists():
                    external_run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
                path.unlink(missing_ok=True)
                return path
            service_argv = launch_command(home, 'serve')
            private_write(path, plistlib.dumps({'Label': name, 'ProgramArguments': service_argv,
                'RunAtLoad': True, 'KeepAlive': False, 'StandardOutPath': str(home / 'service.log'),
                'StandardErrorPath': str(home / 'service.log'), 'EnvironmentVariables': {'PYTHON_DOTENV_DISABLED': '1'}}))
            external_run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True, capture_output=True)
        else:
            path = Path.home() / 'Desktop' / (name + '.command')
            if remove:
                path.unlink(missing_ok=True)
                return path
            private_write(path, ('#!/bin/sh\nexec ' + shlex.join(argv) + '\n').encode())
            path.chmod(0o700)
    else:
        folder = Path.home() / ('.config/autostart' if autostart else '.local/share/applications')
        path = folder / (name + '.desktop')
        if remove:
            path.unlink(missing_ok=True)
            return path
        private_write(path, ('[Desktop Entry]\nType=Application\nName=AgentVerse\nTerminal=false\n'
            'Categories=Development;\nExec=' + ' '.join(desktop_quote(arg) for arg in argv) + '\n').encode())
        path.chmod(0o700)
    return path


def service(home, remove=False):
    if sys.platform == 'darwin' or os.name == 'nt':
        return shortcut(home, autostart=True, remove=remove)
    name = identifier(home) + '.service'
    path = Path.home() / '.config/systemd/user' / name
    if remove:
        external_run(['systemctl', '--user', 'disable', '--now', name], check=True, capture_output=True)
        path.unlink(missing_ok=True)
    else:
        def quote(value):
            return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'
        argv = launch_command(home, 'serve')
        private_write(path, ('[Unit]\nDescription=AgentVerse workspace\nAfter=network.target\n[Service]\nType=simple\n'
            'ExecStart=' + ' '.join(quote(arg) for arg in argv) + '\nEnvironment=PYTHON_DOTENV_DISABLED=1\n'
            'Restart=on-failure\nRestartSec=5\n[Install]\nWantedBy=default.target\n').encode())
        external_run(['systemctl', '--user', 'daemon-reload'], check=True, capture_output=True)
        external_run(['systemctl', '--user', 'enable', '--now', name], check=True, capture_output=True)
    return path
