"""Frozen launcher, including child CLI/API entry points without an external Python."""

import os
import json
import subprocess
from pathlib import Path
import runpy
import sys

if sys.stdout is None or sys.stderr is None:
    home = Path.home() / '.agentverse'
    home.mkdir(exist_ok=True)
    stream = (home / 'launcher.log').open('a')
    sys.stdout = sys.stderr = stream

if len(sys.argv) >= 3 and sys.argv[1] == '--internal-module':
    module = sys.argv[2]
    if module not in {'agentcommons.cli', 'agentcommons.http_adapter', 'agentcommons.installer'}:
        raise SystemExit('Unsupported internal module.')
    sys.argv = [sys.argv[0], *sys.argv[3:]]
    runpy.run_module(module, run_name='__main__')
else:
    # Existing desktop shortcuts follow the selected version after an update/rollback.
    if os.getenv('AGENTVERSE_REDIRECTED') != '1':
        arguments = sys.argv[1:]
        home = Path.home() / '.agentverse'
        if '--home' in arguments and arguments.index('--home') + 1 < len(arguments):
            home = Path(arguments[arguments.index('--home') + 1]).expanduser().resolve()
        metadata = home / 'installation.json'
        if metadata.is_file():
            saved = json.loads(metadata.read_text())
            target = Path(saved.get('executable', '')) if saved.get('kind') == 'native' else None
            if target and target.is_file() and target.resolve() != Path(sys.executable).resolve():
                env = dict(os.environ, AGENTVERSE_REDIRECTED='1', PYINSTALLER_RESET_ENVIRONMENT='1')
                raise SystemExit(subprocess.call([str(target), *arguments], env=env))
    from agentcommons.cli import main
    try:
        main()
    except BaseException as exc:
        if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
            print(f'AgentVerse could not open: {exc}', file=sys.stderr)
        raise
