"""Process identity checks. Never sends signals or terminates processes."""
import psutil


def identity(pid: int) -> dict:
    p = psutil.Process(pid)
    return {"pid": p.pid, "created": p.create_time(), "executable": p.exe()}


def state(item: dict) -> str:
    try:
        p = psutil.Process(item["pid"])
        if abs(p.create_time() - item["created"]) > 0.01:
            return "gone"  # PID was reused; it is not the recorded process.
        return "alive" if p.is_running() else "gone"
    except psutil.NoSuchProcess:
        return "gone"
    except (psutil.AccessDenied, OSError):
        return "unknown"
