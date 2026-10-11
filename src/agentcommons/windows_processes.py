"""Windows process jobs. Assign suspended children before any user code can run."""

import ctypes
from ctypes import wintypes as W
import subprocess

K = ctypes.WinDLL("kernel32", use_last_error=True)


class BASIC(ctypes.Structure):
    _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64), ("LimitFlags", W.DWORD),
                ("Min", ctypes.c_size_t), ("Max", ctypes.c_size_t), ("Active", W.DWORD),
                ("Affinity", ctypes.c_size_t), ("Priority", W.DWORD), ("Scheduling", W.DWORD)]


class IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")]


class EXTENDED(ctypes.Structure):
    _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemory", ctypes.c_size_t),
                ("JobMemory", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]


class THREAD(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("Usage", W.DWORD), ("ThreadId", W.DWORD),
                ("ProcessId", W.DWORD), ("BasePriority", W.LONG), ("DeltaPriority", W.LONG), ("Flags", W.DWORD)]


for name, args, result in (
    ("CreateJobObjectW", [W.LPVOID, W.LPCWSTR], W.HANDLE),
    ("SetInformationJobObject", [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD], W.BOOL),
    ("AssignProcessToJobObject", [W.HANDLE, W.HANDLE], W.BOOL),
    ("CloseHandle", [W.HANDLE], W.BOOL),
    ("CreateToolhelp32Snapshot", [W.DWORD, W.DWORD], W.HANDLE),
    ("Thread32First", [W.HANDLE, ctypes.POINTER(THREAD)], W.BOOL),
    ("Thread32Next", [W.HANDLE, ctypes.POINTER(THREAD)], W.BOOL),
    ("OpenThread", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
    ("ResumeThread", [W.HANDLE], W.DWORD),
):
    function = getattr(K, name)
    function.argtypes, function.restype = args, result


def require(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


class Job:
    def __init__(self):
        self.handle = None
        self.handle = require(K.CreateJobObjectW(None, None))
        limits = EXTENDED()
        limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            require(K.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


def resume_process(pid):
    snapshot = K.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = THREAD()
        entry.dwSize = ctypes.sizeof(entry)
        found = False
        more = K.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.ProcessId == pid:
                thread = require(K.OpenThread(2, False, entry.ThreadId))  # THREAD_SUSPEND_RESUME
                try:
                    if K.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                    found = True
                finally:
                    K.CloseHandle(thread)
            more = K.Thread32Next(snapshot, ctypes.byref(entry))
        if not found:
            raise OSError("Could not resume the managed process; no initial thread found.")
    finally:
        K.CloseHandle(snapshot)


def start_job(argv, **kwargs):
    job = Job()
    process = None
    try:
        flags = kwargs.pop("creationflags", 0) | 0x4 | subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(argv, creationflags=flags, **kwargs)  # CREATE_SUSPENDED
        require(K.AssignProcessToJobObject(job.handle, int(process._handle)))
        process._agentverse_job = job
        resume_process(process.pid)
        return process
    except BaseException:
        if process is not None:
            process.kill()
            process.wait(timeout=5)
        job.close()
        raise
