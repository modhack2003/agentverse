"""AgentVerse jobs-protocol bridge with acknowledged remote cancellation."""

import json
import os
import re
import signal
import sys
import time
from pathlib import Path

import httpx

TERMINAL = {"completed", "failed", "cancelled"}


def read_state(path):
    try:
        result = json.loads(Path(path).read_text()) if path else {}
        return result if isinstance(result, dict) else {}
    except (ValueError, OSError):
        return {}


def write_state(path, data):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(data, output)
    os.replace(temporary, target)


def client(config):
    headers = dict(config.get("headers", {}))
    if config.get("token_env"):
        token = os.getenv(config["token_env"])
        if not token:
            raise ValueError("API adapter authentication environment variable is missing.")
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=config["url"].rstrip("/") + "/", headers=headers, timeout=2, follow_redirects=False)


def reconcile(path):
    state = read_state(path)
    if not state:
        return False
    if state.get("confirmed") is True:
        return True
    if not isinstance(state.get("connector"), dict):
        return False
    try:
        with client(state["connector"]) as http:
            if state.get("job_id"):
                http.delete(f"jobs/{state['job_id']}")
                response = http.get(f"jobs/{state['job_id']}")
            else:
                # Cancellation by request ID must tombstone a late/lost POST before reporting it safe.
                http.delete("jobs", params={"request_id": state["request_id"]})
                response = http.get("jobs", params={"request_id": state["request_id"]})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                return False
            if result.get("state") in TERMINAL and (state.get("job_id") or result.get("confirmed") is True):
                write_state(path, {**state, "confirmed": True})
                return True
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError):
        return False
    return False


def run(prompt_file):
    config = json.loads(os.environ["AGENTVERSE_HTTP_CONFIG"])
    state_path = os.getenv("AGENTVERSE_ADAPTER_STATE", "")
    if not state_path:
        raise ValueError("The jobs bridge requires a durable AGENTVERSE_ADAPTER_STATE journal; launch it through a node.")
    cancelled = False
    def stop(*_):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    state = {"confirmed": False, "connector": config, "job_id": None}
    # The caller provides an idempotency key so a lost start response can be recovered without duplicate jobs.
    request_id = os.getenv("AGENTVERSE_RUN_ID", "") + ":" + Path(prompt_file).parent.name
    state["request_id"] = request_id
    write_state(state_path, state)
    failure = None
    try:
        with client(config) as http:
            payload = {"protocol_version": 1, "request_id": request_id, "prompt": Path(prompt_file).read_text(),
                       "model": os.getenv("AGENTVERSE_MODEL", ""),
                       "settings": json.loads(os.getenv("AGENTVERSE_SETTINGS", "{}")), "workspace": str(Path.cwd())}
            response = http.post("jobs", json=payload, headers={"Idempotency-Key": request_id})
            response.raise_for_status()
            job_id = response.json()["job_id"]
            if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", job_id):
                raise ValueError("The API returned an invalid job ID.")
            state["job_id"] = job_id
            write_state(state_path, state)
            while not cancelled:
                response = http.get(f"jobs/{job_id}")
                response.raise_for_status()
                result = response.json()
                if result.get("state") in TERMINAL:
                    write_state(state_path, {**state, "confirmed": True})
                    if result["state"] != "completed":
                        raise RuntimeError("The API job ended without completing its task.")
                    if not isinstance(result.get("result"), dict):
                        raise ValueError("The completed API job must return a worker-contract result object.")
                    print("```agentverse\n" + json.dumps(result["result"]) + "\n```", flush=True)
                    return
                time.sleep(0.15)
    except BaseException as exc:
        if read_state(state_path).get("confirmed"):
            raise
        failure = None if cancelled else exc
        if state["job_id"]:
            cancelled = True
        else:
            # A start response may have been lost; the server must retain the idempotency lookup.
            try:
                with client(config) as http:
                    lookup = http.get("jobs", params={"request_id": request_id})
                    lookup.raise_for_status()
                    data = lookup.json()
                    recovered = data.get("job_id") if isinstance(data, dict) else None
                    if isinstance(recovered, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", recovered):
                        state["job_id"] = recovered
                        write_state(state_path, state)
            except (httpx.HTTPError, ValueError, KeyError):
                pass
        cancelled = True
    if cancelled:
        deadline = time.monotonic() + 3.5
        while time.monotonic() < deadline:
            if reconcile(state_path):
                if failure:
                    raise failure
                return
            time.sleep(0.1)
        raise RuntimeError("Remote cancellation is unconfirmed; this worker's claims must stay held.")


if __name__ == "__main__":
    run(sys.argv[1])
