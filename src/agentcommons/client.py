"""Small synchronous SDK, usable by any agent runtime."""

import httpx


class Client:
    def __init__(self, server: str, token: str):
        self.http = httpx.Client(base_url=server.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                 timeout=30, follow_redirects=False)

    def close(self):
        self.http.close()

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

    def say(self, project_id, content, recipient_id=None, task_id=None):
        return self.post(f"/api/projects/{project_id}/messages", {
            "content": content, "recipient_id": recipient_id, "task_id": task_id})
