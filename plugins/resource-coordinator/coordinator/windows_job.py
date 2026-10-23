"""Windows 10+ contained foreground jobs, without breakaway or kill-on-close.

CreateProcess receives JOB_LIST atomically: there is no unassigned running-child
window. No services, WMI launch, elevation, shell interpretation or termination.
The enclosing execution host's job/cancellation/limits are deliberately retained.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import platform
import subprocess

import psutil

if os.name == "nt":
    K = C.WinDLL("kernel32", use_last_error=True)

    class Startup(C.Structure):
        _fields_ = [("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR),
                    ("title", W.LPWSTR), ("x", W.DWORD), ("y", W.DWORD),
                    ("xs", W.DWORD), ("ys", W.DWORD), ("xc", W.DWORD),
                    ("yc", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
                    ("show", W.WORD), ("reserved2size", W.WORD), ("reserved2", C.c_void_p),
                    ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]

    class StartupEx(C.Structure):
        _fields_ = [("startup", Startup), ("attributes", C.c_void_p)]

    class ProcessInfo(C.Structure):
        _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]

    class Accounting(C.Structure):
        _fields_ = [("user", C.c_longlong), ("kernel", C.c_longlong),
                    ("period_user", C.c_longlong), ("period_kernel", C.c_longlong),
                    ("page_faults", W.DWORD), ("total", W.DWORD),
                    ("active", W.DWORD), ("terminated", W.DWORD)]

    def declare(name, args, result):
        fn = getattr(K, name)
        fn.argtypes, fn.restype = args, result
        return fn

    declare("CreateJobObjectW", [C.c_void_p, W.LPCWSTR], W.HANDLE)
    declare("OpenJobObjectW", [W.DWORD, W.BOOL, W.LPCWSTR], W.HANDLE)
    declare("CloseHandle", [W.HANDLE], W.BOOL)
    declare("QueryInformationJobObject", [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL)
    declare("InitializeProcThreadAttributeList", [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)], W.BOOL)
    declare("UpdateProcThreadAttribute", [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p], W.BOOL)
    declare("DeleteProcThreadAttributeList", [C.c_void_p], None)
    declare("CreateProcessW", [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL,
                              W.DWORD, C.c_void_p, W.LPCWSTR, C.c_void_p, C.POINTER(ProcessInfo)], W.BOOL)
    declare("GetCurrentProcess", [], W.HANDLE)
    declare("GetStdHandle", [W.DWORD], W.HANDLE)
    declare("DuplicateHandle", [W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD], W.BOOL)
    declare("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)
    declare("GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL)
    declare("OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
    declare("GetProcessTimes", [W.HANDLE, C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME)], W.BOOL)
    declare("IsProcessInJob", [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)], W.BOOL)
    declare("ProcessIdToSessionId", [W.DWORD, C.POINTER(W.DWORD)], W.BOOL)


def check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def scope():
    if os.name != "nt":
        raise OSError("Contained jobs require Windows 10+; use --tracking observed explicitly elsewhere")
    sid = W.DWORD()
    check(K.ProcessIdToSessionId(os.getpid(), C.byref(sid)))
    return {"machine": platform.node().casefold(), "session": sid.value, "boot": round(psutil.boot_time())}


class Process:
    def __init__(self, handle, pid):
        self.handle, self.pid = handle, pid

    def poll(self):
        result = K.WaitForSingleObject(self.handle, 0)
        if result == 258:
            return None
        if result != 0:
            raise OSError("Cannot verify process completion")
        code = W.DWORD()
        check(K.GetExitCodeProcess(self.handle, C.byref(code)))
        return code.value

    def identity(self):
        created, exited, kernel, user = (W.FILETIME() for _ in range(4))
        check(K.GetProcessTimes(self.handle, C.byref(created), C.byref(exited), C.byref(kernel), C.byref(user)))
        stamp = ((created.dwHighDateTime << 32) | created.dwLowDateTime) / 10_000_000 - 11644473600
        return {"pid": self.pid, "created": stamp, "executable": "contained-root"}

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None

    @classmethod
    def reopen(cls, item, job):
        if not item:
            return None
        handle = K.OpenProcess(0x1000 | 0x100000, False, item["pid"])
        if not handle:
            if C.get_last_error() == 87:  # PID no longer exists
                return None
            raise C.WinError(C.get_last_error())
        process = cls(handle, item["pid"])
        try:
            if abs(process.identity()["created"] - item["created"]) > .01:
                process.close()
                return None  # reused PID is not the root
            member = W.BOOL()
            check(K.IsProcessInJob(handle, job.handle, C.byref(member)))
            if not member.value:
                raise OSError("Recorded root is not in the recorded job")
            return process
        except BaseException:
            process.close()
            raise


class Job:
    def __init__(self, handle):
        self.handle = handle

    @classmethod
    def create(cls, name):
        scope()
        C.set_last_error(0)
        handle = K.CreateJobObjectW(None, name)
        check(handle)
        if C.get_last_error() == 183:
            K.CloseHandle(handle)
            raise OSError("Job name already exists; never reuse a process group")
        return cls(handle)

    @classmethod
    def open(cls, name, expected_scope):
        if scope() != expected_scope:
            raise OSError("Machine/session/boot differs; process group is unverifiable")
        handle = K.OpenJobObjectW(4, False, name)  # QUERY only, no termination right
        if not handle:
            if C.get_last_error() == 2:
                return None  # Name absence alone is NOT proof of process exit.
            raise C.WinError(C.get_last_error())
        return cls(handle)

    def active(self):
        result = Accounting()
        check(K.QueryInformationJobObject(self.handle, 1, C.byref(result), C.sizeof(result), None))
        return result.active

    def start(self, argv, cwd=None):
        # Preserve ordinary stdout/stderr without leaking the DB/job handles.
        handles, attributes = [], None
        initialized = False
        try:
            me = K.GetCurrentProcess()
            for standard in (-10, -11, -12):
                source = K.GetStdHandle(standard & 0xffffffff)
                duplicate = W.HANDLE()
                check(K.DuplicateHandle(me, source, me, C.byref(duplicate), 0, True, 2))
                handles.append(duplicate.value)
            size = C.c_size_t()
            K.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            check(K.InitializeProcThreadAttributeList(attributes, 2, 0, C.byref(size)))
            initialized = True
            jobs = (W.HANDLE * 1)(self.handle)
            inherited = (W.HANDLE * 3)(*handles)
            check(K.UpdateProcThreadAttribute(attributes, 0, 0x2000D, jobs, C.sizeof(jobs), None, None))
            check(K.UpdateProcThreadAttribute(attributes, 0, 0x20002, inherited, C.sizeof(inherited), None, None))
            startup = StartupEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100 | 1  # USESTDHANDLES, USESHOWWINDOW (hidden)
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
            startup.attributes = C.cast(attributes, C.c_void_p)
            info = ProcessInfo()
            command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            # No BREAKAWAY, alternate parent, elevation or detached supervisor.
            check(K.CreateProcessW(argv[0], command, None, None, True, 0x80000 | 0x08000000,
                                   None, cwd, C.byref(startup), C.byref(info)))
            K.CloseHandle(info.thread)
            return Process(info.process, info.pid)
        finally:
            if initialized:
                K.DeleteProcThreadAttributeList(attributes)
            for handle in handles:
                K.CloseHandle(handle)

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None
