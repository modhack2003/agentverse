"""Small synchronous SDK, usable by any agent runtime."""

import httpx


class Client:
    def __init__(self, server: str, token: str):
        self.http = httpx.Client(base_url=server.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                 timeout=30, follow_redirects=False)

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

    def say(self, project_id, content, recipient_id=None, task_id=None):
        return self.post(f"/api/projects/{project_id}/messages", {
            "content": content, "recipient_id": recipient_id, "task_id": task_id})
