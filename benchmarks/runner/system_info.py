"""Stable machine metadata captured with every benchmark result."""
import os
import platform


def collect():
    memory = 0
    try:
        memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        pass
    return {"os": platform.system(), "kernel": platform.release(),
            "architecture": platform.machine(), "cpu": platform.processor(),
            "cores": os.cpu_count() or 0, "memory_bytes": memory,
            "power_mode": os.environ.get("TECTDIST_POWER_MODE", "unknown")}
