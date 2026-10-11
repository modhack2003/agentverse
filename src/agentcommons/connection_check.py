"""Bounded, read-only HTTP and MCP diagnostics without taking over a session."""

import httpx


def check(server, token, node=False, mcp=False):
    from urllib.parse import urlsplit
    parts = urlsplit(server)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('Use an HTTP(S) URL without embedded credentials.')
    checks = []
    with httpx.Client(base_url=server.rstrip('/'), headers={'Authorization': 'Bearer ' + token}, timeout=5) as client:
        for name, path in [('network/server', '/api/health'), ('authentication', '/api/nodes/me/check' if node else '/api/me')]:
            try:
                response = client.get(path)
                if response.status_code != 200:
                    checks.append({'check': name, 'ok': False, 'status': response.status_code,
                                   'next_step': 'Check the token type, expiry and server URL.' if name == 'authentication' else 'Check the workspace URL and reverse proxy.'})
                    return {'ok': False, 'checks': checks}
                payload = response.json()
                if name == 'network/server' and payload.get('product') != 'AgentVerse':
                    raise ValueError('The URL does not serve an AgentVerse workspace.')
                checks.append({'check': name, 'ok': True})
            except (httpx.HTTPError, ValueError):
                checks.append({'check': name, 'ok': False, 'next_step': 'Check server startup, DNS, TLS certificates, firewall and proxy settings.'})
                return {'ok': False, 'checks': checks}
        if mcp:
            if node:
                raise ValueError('Node supervisor tokens cannot authenticate to MCP. Use an agent token for MCP checks.')
            try:
                response = client.post('/mcp/', headers={'Accept': 'application/json, text/event-stream'}, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26',
                    'capabilities': {}, 'clientInfo': {'name': 'agentverse-doctor', 'version': '1'}}})
                result = response.json()
                valid = response.status_code == 200 and result.get('result', {}).get('serverInfo', {}).get('name') == 'AgentVerse'
                checks.append({'check': 'MCP handshake', 'ok': valid, 'next_step': 'Check /mcp/ routing, bearer headers and transport configuration.' if not valid else 'Configure the same endpoint in your native tool.'})
            except (httpx.HTTPError, ValueError):
                checks.append({'check': 'MCP handshake', 'ok': False, 'next_step': 'Check /mcp/ routing and transport configuration.'})
    return {'ok': all(row['ok'] for row in checks), 'checks': checks,
            'unverified': ['provider login', 'native tool MCP attachment', 'model execution', 'cancellation']}
