"""A slow coding CLI with a child process, used to verify actual supervisor cancellation."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

context = json.loads(Path(sys.argv[1]).read_text().split("PROJECT CONTEXT\n", 1)[1])
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])


def stopped(*_):
    child.wait(timeout=5)
    sys.exit(0)


signal.signal(signal.SIGTERM, stopped)
Path(os.environ["AGENTCOMMONS_TEST_TRACE"]).write_text(json.dumps({
    "pid": os.getpid(), "child_pid": child.pid, "argv_model": sys.argv[2],
    "env_model": os.getenv("AGENTCOMMONS_MODEL"), "context_model": context["selected_model"],
    "admin_token": os.getenv("AGENTCOMMONS_ADMIN_TOKEN"), "node_token": os.getenv("AGENTCOMMONS_NODE_TOKEN"),
}))
time.sleep(300)
