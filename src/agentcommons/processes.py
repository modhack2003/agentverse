"""Isolated process trees: POSIX sessions and Windows kill-on-close jobs."""

from contextlib import contextmanager
import os
from pathlib import Path
import threading
import signal
import subprocess
import sys
import time


def module_command(module, *arguments):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal-module", module, *map(str, arguments)]
    return [sys.executable, "-m", module, *map(str, arguments)]


_loader_lock = threading.RLock()


def external_environment(values=None):
    env = dict(os.environ if values is None else values)
    if getattr(sys, "frozen", False):
        for name in ("LD_LIBRARY_PATH", "LIBPATH", "DYLD_LIBRARY_PATH"):
            original = env.get(name + "_ORIG")
            if original is None:
                env.pop(name, None)
            else:
                env[name] = original
        for key in list(env):
            if key.startswith("_PYI_"):
                env.pop(key)
    return env


@contextmanager
def external_loader():
    with _loader_lock:
        if os.name == "nt" and getattr(sys, "frozen", False):
            import ctypes
            function = ctypes.WinDLL("kernel32", use_last_error=True).SetDllDirectoryW
            function.argtypes, function.restype = [ctypes.c_wchar_p], ctypes.c_int
            function(None)
            try:
                yield
            finally:
                function(sys._MEIPASS)
        else:
            yield


def external_run(argv, **kwargs):
    kwargs["env"] = external_environment(kwargs.get("env"))
    with external_loader():
        return subprocess.run(argv, **kwargs)


def start_process(argv, **kwargs):
    if getattr(sys, "frozen", False) and Path(argv[0]).resolve() != Path(sys.executable).resolve():
        kwargs["env"] = external_environment(kwargs.get("env"))
        with external_loader():
            return _start_process(argv, **kwargs)
    return _start_process(argv, **kwargs)


def _start_process(argv, **kwargs):
    if os.name != "nt":
        return subprocess.Popen(argv, start_new_session=True, **kwargs)
    from .windows_processes import start_job
    return start_job(argv, **kwargs)


def terminate_process(process, grace=5):
    """Reap the leader and terminate descendants, including orphaned descendants."""
    if os.name == "nt":
        job = getattr(process, "_agentverse_job", None)
        if job is None:
            raise RuntimeError("Windows managed processes must be started using start_process().")
        # CTRL_BREAK gives Python workers a chance to release their task claim.
        if process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                process.wait(timeout=grace)
            except (OSError, subprocess.TimeoutExpired):
                pass
        job.close()  # KILL_ON_JOB_CLOSE also cleans up descendants after leader exit.
        process.wait(timeout=5)
        return
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
        time.sleep(0.2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
