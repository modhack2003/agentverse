"""Shared cleanup for subprocesses started in isolated POSIX sessions."""

import os
import signal
import subprocess
import time


def terminate_process(process, grace=5):
    """Reap the leader and escalate the entire group, even if the leader exits."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        if process.poll() is None:
            process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # A successful wait only proves the leader exited, not its descendants.
        time.sleep(0.2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
