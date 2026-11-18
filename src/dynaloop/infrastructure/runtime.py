"""Read-only information about the current DynaLoop runtime."""

import platform
import sys
from dataclasses import dataclass
from importlib import metadata

_DISTRIBUTION_NAME = "dynaloop-quant"


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """Snapshot of the current Python, operating system, and project version."""

    python_version: str
    python_executable: str | None
    os_name: str | None
    platform: str | None
    project_version: str | None


def get_runtime_info() -> RuntimeInfo:
    """Return read-only runtime facts; unavailable optional values are ``None``."""
    try:
        project_version = metadata.version(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        project_version = None

    return RuntimeInfo(
        python_version=platform.python_version(),
        python_executable=sys.executable or None,
        os_name=platform.system() or None,
        platform=platform.platform() or None,
        project_version=project_version,
    )
