"""Build offline portable distributions on their target operating system."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output, native_formats=False):
    from agentcommons.config import VERSION
    from agentcommons.updates import platform_key
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--name', 'agentverse', '--onedir',
        '--distpath', str(output / 'portable'), '--workpath', str(output / 'build'), '--specpath', str(output / 'build'),
        '--paths', str(ROOT / 'src'), '--collect-all', 'agentcommons', '--collect-all', 'agentverse',
        '--collect-data', 'mcp', '--collect-all', 'textual', '--collect-all', 'uvicorn', '--collect-all', 'fastapi',
        '--collect-all', 'socksio', '--hidden-import', 'anyio._backends._asyncio', str(ROOT / 'packaging/entry.py')]
    if sys.platform == 'darwin' and os.getenv('MACOS_SIGNING_IDENTITY'):
        from signing import macos_certificate
        macos_certificate()
        command += ['--codesign-identity', os.environ['MACOS_SIGNING_IDENTITY']]
    subprocess.run(command, cwd=ROOT, check=True)
    directory = output / 'portable/agentverse'
    if os.name == 'nt':
        from signing import windows_sign
        windows_sign(directory / 'agentverse.exe')
    name = f'agentverse-{VERSION}-{platform_key()}' 
    # Portable payloads contain only regular files/directories, even on macOS framework layouts.
    if any(path.is_symlink() for path in directory.rglob('*')):
        temporary = output / 'dereferenced'
        shutil.copytree(directory, temporary, symlinks=False)
        shutil.rmtree(directory)
        temporary.rename(directory)
    shutil.copy2(ROOT / 'LICENSE', directory / 'LICENSE.txt')
    (directory / 'INSTALL.txt').write_text('Extract the entire folder. Open agentverse' + ('.exe' if os.name == 'nt' else '') + '\nPython, Node and internet are not needed to run this package.\nCoding tools and provider logins are separate.\nData: ~/.agentverse; custom data: agentverse launch --home /path\nStart/Stop: agentverse start / agentverse stop\nBackups contain credentials; keep them private.\n', encoding='utf-8')
    if os.name == 'nt':
        archive = output / (name + '.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as target:
            for path in directory.rglob('*'):
                if path.is_file():
                    target.write(path, path.relative_to(directory.parent))
    else:
        archive = output / (name + '.tar.gz')
        with tarfile.open(archive, 'w:gz', dereference=True) as target:
            target.add(directory, arcname='agentverse')
    asset = {'name': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
             'platform': platform_key(), 'version': VERSION, 'python': platform.python_version()}
    (output / (name + '.json')).write_text(json.dumps(asset, indent=2))
    (output / (archive.name + '.sha256')).write_text(asset['sha256'] + '  ' + archive.name + '\n')
    if native_formats:
        if sys.platform.startswith('linux'):
            from linux import packages
            packages(directory, output, VERSION)
        elif os.name == 'nt':
            compiler = shutil.which('ISCC') or str(Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe')
            subprocess.run([compiler, f'/DAppVersion={VERSION}', f'/DSourceDir={directory}', f'/DOutputDir={output}', str(ROOT / 'packaging/windows.iss')], check=True)
            windows_sign(output / f'agentverse-{VERSION}-windows-setup.exe')
        elif sys.platform == 'darwin':
            app = output / 'AgentVerse.app'
            resources = app / 'Contents/Resources'
            shutil.copytree(directory, resources / 'agentverse')
            executable = app / 'Contents/MacOS/AgentVerse'
            executable.parent.mkdir(parents=True)
            executable.write_text('#!/bin/sh\nexec "$(dirname "$0")/../Resources/agentverse/agentverse" "$@"\n')
            executable.chmod(0o755)
            import plistlib
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName': 'AgentVerse', 'CFBundleExecutable': 'AgentVerse',
                'CFBundleIdentifier': 'io.agentverse.desktop', 'CFBundleVersion': VERSION, 'CFBundlePackageType': 'APPL'}))
            identity = os.getenv('MACOS_SIGNING_IDENTITY')
            if identity:
                subprocess.run(['codesign', '--force', '--deep', '--options', 'runtime', '--sign', identity, str(app)], check=True)
            subprocess.run(['hdiutil', 'create', '-volname', 'AgentVerse', '-srcfolder', str(app), '-ov', str(output / (name + '.dmg'))], check=True)
            from signing import notarize
            notarize(output / (name + '.dmg'))
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/native')
    parser.add_argument('--native-formats', action='store_true')
    args = parser.parse_args()
    print(build(args.output, args.native_formats))
