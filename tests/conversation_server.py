"""Browser fixture: two actual workers, tool processes and separate Git clones."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time

from fastapi import FastAPI
import uvicorn

from agentverse import Client
from agentcommons.worker import Worker

TOKEN = 'browser-test-only-token-not-a-secret'
with tempfile.TemporaryDirectory(prefix='agentverse-chat-browser-') as temporary:
    root = Path(temporary)
    os.environ.update(GIT_AUTHOR_NAME='Chat acceptance', GIT_COMMITTER_NAME='Chat acceptance',
                      GIT_AUTHOR_EMAIL='chat@example.test', GIT_COMMITTER_EMAIL='chat@example.test')

    def git(*args, cwd=None):
        subprocess.run(['git', *map(str, args)], cwd=cwd, check=True, capture_output=True)

    origin = root / 'origin.git'
    git('init', '--bare', '--initial-branch=main', origin)
    git('clone', origin, root / 'alpha')
    git('commit', '--allow-empty', '-m', 'Initial', cwd=root / 'alpha')
    git('push', 'origin', 'main', cwd=root / 'alpha')
    git('clone', origin, root / 'beta')
    workers, threads = [], []
    with Client('http://127.0.0.1:8000', TOKEN) as owner:
        project = owner.post('/api/projects', {'name': 'Conversation acceptance', 'goal': 'Complete work from human team chat.', 'auto_plan': False})
        peers = []
        for name, folder in [('ChatAlpha', 'alpha'), ('ChatBeta', 'beta')]:
            peer = owner.post(f"/api/projects/{project['id']}/agents", {'name': name, 'kind': 'custom'})
            command = shlex.join([sys.executable, str(Path(__file__).parent / 'fixtures/conversation_cli.py'),
                                  '{prompt_file}', str(root / (folder + '-failure-once'))])
            worker = Worker('http://127.0.0.1:8000', peer['token'], root / folder, command, interval=.15)
            workers.append(worker)
            thread = threading.Thread(target=worker.run, daemon=True)
            threads.append(thread)
            thread.start()
            peers.append({'id': peer['agent']['id'], 'name': name})
        deadline = time.monotonic() + 20
        while not all(a['conversation']['state'] == 'listening' for a in owner.snapshot(project['id'])['agents']):
            assert time.monotonic() < deadline
            time.sleep(.05)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            for worker in workers:
                worker.stop.set()
            for thread in threads:
                await asyncio.to_thread(thread.join, 15)

    app = FastAPI(lifespan=lifespan)

    @app.get('/ready')
    def ready():
        return {'project': project, 'agents': peers}

    uvicorn.run(app, host='127.0.0.1', port=8200, log_level='error')
