"""Local onboarding and maintenance. Remote deployments keep these routes disabled."""

import json
import os
from pathlib import Path
import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import setting, VERSION
from .local import backup, diagnostics
from .models import ProjectCreate
from .passwords import hash_password
from .setup import read_setup, write_setup
from .store import Principal


class Welcome(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.@-]+$')
    password: str = Field(min_length=12, max_length=256)
    project_name: str = Field(default='', max_length=100)
    goal: str = Field(default='', max_length=20000)


def attach_local_routes(app, store, principal, local_home=None):
    home = Path(local_home or setting('LOCAL_HOME')).resolve() if local_home or setting('LOCAL_HOME') else None
    secret = setting('WELCOME_TOKEN')
    expires = time.monotonic() + 900
    welcome_lock = threading.Lock()
    if home:
        store.local_login = read_setup(home).get('login')

    def local_admin(p=Depends(principal)):
        store.admin_only(p)
        if not home:
            raise HTTPException(404, 'Local maintenance is disabled for this deployment. Use the server administrator CLI.')
        return p

    @app.get('/api/local/onboarding')
    def onboarding():
        return {'available': bool(home and secret and time.monotonic() < expires and not read_setup(home).get('onboarding_complete')),
                'password_login': bool(store.admin_credentials()), 'local': bool(home), 'version': VERSION}

    @app.post('/api/local/setup-link')
    def setup_link(p=Depends(local_admin)):
        nonlocal secret, expires
        with welcome_lock:
            if read_setup(home).get('onboarding_complete'):
                raise HTTPException(409, 'Setup is already complete.')
            secret = secrets.token_urlsafe(32)
            expires = time.monotonic() + 900
            return {'fragment': '#setup=' + secret}

    @app.post('/api/local/welcome')
    def welcome(data: Welcome, request: Request):
        nonlocal secret
        with welcome_lock:
            if (not home or not secret or time.monotonic() > expires
                    or not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + secret)):
                raise HTTPException(401, 'Setup link expired or invalid. Reopen AgentVerse to get a new setup link.')
            saved = read_setup(home)
            if saved.get('onboarding_complete'):
                raise HTTPException(409, 'Setup is already complete. Sign in with your saved credentials.')
            saved['login'] = {'username': data.username, 'password_hash': hash_password(data.password)}
            saved['onboarding_complete'] = True
            # Create the optional project first: validation failures cannot consume the setup link.
            project = store.create_project(Principal(), ProjectCreate(name=data.project_name, goal=data.goal or 'Connect my first agent and verify a bounded task.', auto_plan=False)) if data.project_name else None
            try:
                write_setup(home, saved)
            except OSError:
                if project:
                    # No task/agent data can be present on this newly created project yet.
                    with store.transaction():
                        store.db.execute('DELETE FROM projects WHERE id=?', (project['id'],))
                raise
            store.local_login = saved['login']
            secret = ''
            # Issue a revocable browser session without exposing the reusable administrator token.
            token = 'web_' + secrets.token_urlsafe(32)
            store.admin_sessions[token] = (time.time() + 86400, store.admin_credential_fingerprint())
            return {'token': token, 'project': project}

    @app.get('/api/local/status')
    def local_status(p=Depends(local_admin)):
        return {'running': True, 'configured': True, 'home': str(home), 'pid': os.getpid(),
                'version': VERSION, 'port': read_setup(home)['port']}

    @app.post('/api/local/stop')
    def local_stop(p=Depends(local_admin)):
        shutdown = getattr(app.state, 'shutdown', None)
        if not shutdown:
            raise HTTPException(409, 'This server is not managed by the local launcher. Stop it in its terminal or service manager.')
        threading.Timer(0.5, shutdown).start()
        return {'stopping': True}

    @app.get('/api/local/diagnostics')
    def local_diagnostics(p=Depends(local_admin)):
        return diagnostics(home)

    @app.get('/api/local/backup')
    def local_backup(p=Depends(local_admin)):
        path = backup(home)
        try:
            return Response(path.read_bytes(), media_type='application/zip',
                            headers={'Content-Disposition': f'attachment; filename="{path.name}"'})
        finally:
            path.unlink(missing_ok=True)

    @app.post('/api/local/node-config')
    def node_config(data: dict, p=Depends(principal)):
        store.admin_only(p)
        from .node import NodeConfig
        try:
            config = NodeConfig.model_validate(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {'config': json.loads(config.model_dump_json()), 'note': 'Save on the agent machine. This does not run any command or verify provider login.'}
