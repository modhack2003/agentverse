"""Small synchronous SDK, usable by any agent runtime."""

import httpx
import threading
import uuid
import time
from .errors import safe_error


class ChatCallbackInterrupted(RuntimeError):
    cancellation_unconfirmed = True


class Client:
    def __init__(self, server: str, token: str, timeout: float = 30):
        self.http = httpx.Client(base_url=server.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                 timeout=timeout, follow_redirects=False)

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, method, path, data=None):
        response = self.http.request(method, path, json=data)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"{response.status_code}: {detail}")
        return response.json()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, data=None):
        return self.request("POST", path, data)

    def snapshot(self, project_id):
        return self.get(f"/api/projects/{project_id}/snapshot")

    def connect(self, capabilities=None, limitations=None, tool_version=""):
        """Announce a HTTP peer session and return its identity, peers and protocol information."""
        return self.post("/api/agents/announce", {"connection": "http", "protocol_version": 1,
            "tool_version": tool_version, "capabilities": capabilities or [], "limitations": limitations or []})

    def teammates(self, project_id, capability=""):
        from urllib.parse import quote
        return self.get(f"/api/projects/{project_id}/teammates?capability={quote(capability)}")

    def request_help(self, project_id, question, capability="", task_id=None):
        return self.post(f"/api/projects/{project_id}/help", {"question": question, "capability": capability, "task_id": task_id})

    def say(self, project_id, content, recipient_id=None, task_id=None, channel="general", intent="auto", reply_to_id=None, request_id=None):
        return self.post(f"/api/projects/{project_id}/messages", {
            "content": content, "recipient_id": recipient_id, "task_id": task_id, "channel": channel,
            "intent": intent, "reply_to_id": reply_to_id, "client_request_id": request_id or uuid.uuid4().hex})

    def listen(self, responder, stop=None, interval=5, once=False, timeout=120, cancel=None):
        """Run a persistent, sequential chat listener around a real model callback.

        responder(turn) returns a reply string or {'reply': ..., 'task_request': ...}.
        It must honour its own model timeout/cancellation and must not perform code changes.
        Work requests are planned/executed separately by task-capable agents.
        """
        if not callable(responder) or not .05 <= interval <= 60 or not .05 <= timeout <= 120:
            raise ValueError('Provide a real reply callback and a polling interval between 0.05 and 60 seconds.')
        session_id = uuid.uuid4().hex
        stop = stop or threading.Event()
        self.chat_post('/api/agents/chat/register', {'session_id': session_id})
        state = {'status': 'idle'}

        def pulse():
            with Client(str(self.http.base_url), self.http.headers['Authorization'].removeprefix('Bearer '), timeout=5) as heartbeat:
                while not stop.is_set():
                    try:
                        heartbeat.post('/api/agents/chat/heartbeat', {'session_id': session_id, **state})
                    except (RuntimeError, httpx.HTTPError):
                        pass
                    stop.wait(25)

        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            while not stop.is_set():
                try:
                    turn = self.chat_post('/api/agents/chat/claim', {'session_id': session_id, 'request_id': uuid.uuid4().hex})
                except RuntimeError as exc:
                    if str(exc).startswith('409:'):
                        if once:
                            return
                        stop.wait(interval)
                        continue
                    raise
                if not turn:
                    if once:
                        return
                    stop.wait(interval)
                    continue
                state['status'] = 'working'
                ownership = {'session_id': session_id, 'claim_token': turn['claim_token']}
                try:
                    result = self.chat_callback(responder, turn, ownership, stop, timeout, cancel)
                    if stop.is_set():
                        raise RuntimeError('The listener stopped before this reply was published.')
                    if isinstance(result, str):
                        result = {'reply': result}
                    # A lost success response retries only publication, never the model callback.
                    for attempt in range(3):
                        try:
                            self.post(f"/api/agents/chat/{turn['message']['id']}/finish", {**ownership, 'result': result})
                            break
                        except httpx.HTTPError:
                            if attempt == 2:
                                raise
                except Exception as exc:
                    try:
                        self.post(f"/api/agents/chat/{turn['message']['id']}/fail", {
                            **ownership, 'error': f'Reply callback failed ({type(exc).__name__}): ' + safe_error(exc, [self.http.headers.get('Authorization', '').removeprefix('Bearer ')]),
                            'cancellation_confirmed': not getattr(exc, 'cancellation_unconfirmed', False)})
                    except (RuntimeError, httpx.HTTPError):
                        pass
                finally:
                    state['status'] = 'idle'
                if once:
                    return
        finally:
            stop.set()
            thread.join(timeout=6)
            try:
                self.post('/api/agents/chat/stop', {'session_id': session_id})
            except (RuntimeError, httpx.HTTPError):
                pass

    def chat_post(self, path, data):
        """Retry idempotent conversation operations with the same request/claim identity."""
        for attempt in range(3):
            try:
                return self.post(path, data)
            except httpx.HTTPError:
                if attempt == 2:
                    raise

    def chat_callback(self, responder, turn, ownership, stop, timeout, cancel):
        """A stuck callback cannot keep renewing an apparently healthy turn forever."""
        done, expired, result = threading.Event(), threading.Event(), {}

        def invoke():
            try:
                result['value'] = responder(turn)
            except BaseException as exc:
                result['error'] = exc
            finally:
                done.set()
                if expired.is_set() and not getattr(result.get('error'), 'cancellation_unconfirmed', False):
                    try:
                        self.post(f"/api/agents/chat/{turn['message']['id']}/fail", {**ownership,
                            'error': 'The timed-out callback has now ended. Retry to request a new reply.', 'cancellation_confirmed': True})
                    except (RuntimeError, httpx.HTTPError):
                        pass

        threading.Thread(target=invoke, daemon=True).start()
        deadline = time.monotonic() + timeout
        while not done.wait(.05):
            if stop.is_set() or time.monotonic() >= deadline:
                expired.set()
                if done.is_set():
                    break
                confirmed = False
                if cancel:
                    cancellation, acknowledged = {}, threading.Event()

                    def cancel_runtime():
                        try:
                            cancellation['confirmed'] = cancel(turn) is True
                        except Exception:
                            pass
                        finally:
                            acknowledged.set()

                    threading.Thread(target=cancel_runtime, daemon=True).start()
                    acknowledged.wait(5)
                    confirmed = cancellation.get('confirmed', False)
                if confirmed:
                    raise RuntimeError('The conversation callback timed out or stopped; its runtime confirmed cancellation.')
                raise ChatCallbackInterrupted('The conversation callback timed out or stopped, but cancellation is unconfirmed. Stop the previous runtime before retrying.')
        if 'error' in result:
            raise result['error']
        return result['value']
