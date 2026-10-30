"""Select native pixel rendering before Windows or Tk creates any app window."""
from __future__ import annotations

import ctypes
import sys


def enable_windows_dpi_awareness() -> str:
    """Avoid Windows bitmap stretching; preserve an already configured process.

    Tk 8.6 uses a system DPI for its interpreter. System awareness matches that
    model without claiming per-monitor font/layout support. This changes only
    the calling process and must run before the dependency bootstrap's Tk UI.
    """
    if sys.platform != "win32":
        return "not_windows"
    try:
        result = ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    else:
        if result == 0:
            return "system"
        if result & 0xFFFFFFFF == 0x80070005:  # Already fixed by a manifest/API.
            return "already_configured"
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system_legacy"
    except (AttributeError, OSError):
        pass
    return "unavailable"
