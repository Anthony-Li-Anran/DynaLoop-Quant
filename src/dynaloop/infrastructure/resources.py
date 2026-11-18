"""Read-only, on-demand information about host CPU and physical memory."""

import ctypes
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """System resource facts captured at one time.

    Memory values are system-level physical memory sizes in bytes, not
    process memory limits or usage. Unavailable measurements are ``None``.
    ``cpu_available_count`` is the number of logical CPUs allowed by the
    process affinity, when the platform exposes that information; it does not
    account for fractional CPU quotas.
    Accelerator discovery is not implemented and is always ``None``.
    """

    captured_at: datetime
    cpu_logical_count: int | None
    cpu_available_count: int | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    accelerators: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.captured_at, datetime) or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be a timezone-aware datetime.")
        object.__setattr__(self, "captured_at", self.captured_at.astimezone(timezone.utc))

        for field_name in (
            "cpu_logical_count",
            "cpu_available_count",
            "memory_total_bytes",
            "memory_available_bytes",
        ):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field_name} must be a non-negative integer or None.")


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _read_sysconf(name: str) -> int | None:
    if name not in os.sysconf_names:
        return None
    try:
        value = os.sysconf(name)
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def _get_linux_memory() -> tuple[int | None, int | None]:
    page_size = _read_sysconf("SC_PAGE_SIZE")
    if page_size is None:
        return None, None

    total_pages = _read_sysconf("SC_PHYS_PAGES")
    available_pages = _read_sysconf("SC_AVPHYS_PAGES")
    total_bytes = total_pages * page_size if total_pages is not None else None
    available_bytes = available_pages * page_size if available_pages is not None else None
    return total_bytes, available_bytes


def _get_windows_memory() -> tuple[int | None, int | None]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_memory_status = kernel32.GlobalMemoryStatusEx
    get_memory_status.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
    get_memory_status.restype = ctypes.c_int

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not get_memory_status(ctypes.byref(status)):
        return None, None
    return status.ullTotalPhys, status.ullAvailPhys


def _get_windows_available_cpu_count() -> int | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_affinity_mask = kernel32.GetProcessAffinityMask
    get_process_affinity_mask.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    get_process_affinity_mask.restype = ctypes.c_int

    process_mask = ctypes.c_size_t()
    system_mask = ctypes.c_size_t()
    if not get_process_affinity_mask(
        get_current_process(),
        ctypes.byref(process_mask),
        ctypes.byref(system_mask),
    ):
        return None
    return process_mask.value.bit_count()


def _get_available_cpu_count(system: str) -> int | None:
    if system == "Windows":
        return _get_windows_available_cpu_count()

    get_affinity = getattr(os, "sched_getaffinity", None)
    if get_affinity is None:
        return None
    try:
        return len(get_affinity(0))
    except (OSError, NotImplementedError):
        return None


def _get_memory(system: str) -> tuple[int | None, int | None]:
    if system == "Linux":
        return _get_linux_memory()
    if system == "Windows":
        return _get_windows_memory()
    return None, None


def get_resource_snapshot() -> ResourceSnapshot:
    """Query CPU and system physical memory immediately, without caching."""
    system = platform.system()
    cpu_logical_count = os.cpu_count()
    cpu_available_count = _get_available_cpu_count(system)
    memory_total_bytes, memory_available_bytes = _get_memory(system)

    return ResourceSnapshot(
        captured_at=datetime.now(timezone.utc),
        cpu_logical_count=cpu_logical_count,
        cpu_available_count=cpu_available_count,
        memory_total_bytes=memory_total_bytes,
        memory_available_bytes=memory_available_bytes,
    )
