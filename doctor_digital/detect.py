"""
doctor_digital.detect
=====================
Enumerates removable USB disks visible to Windows.

Returns
-------
list of dict, each with keys:
    Disk#       int     Windows disk number
    Model       str     Friendly name / model string
    Serial      str     Serial number
    Size (GB)   float   Size rounded to 2 decimal places
    Status      str     Operational status (e.g. "Online")

    Internal keys (used by sanitizer / recovery):
    _number     int     Same as Disk#
    _size_bytes int     Raw size in bytes
"""

import json
import subprocess
import sys


def _run_powershell(command: str) -> str:
    """Run a PowerShell command and return stdout as text."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and result.stderr.strip():
        raise RuntimeError(f"PowerShell error: {result.stderr.strip()}")
    return result.stdout.strip()


def detect_dir() -> list:
    """
    Enumerate all USB-connected removable disks.

    Returns a list of dicts representing each disk found.
    The list is ordered by disk number ascending.

    Example
    -------
        all_dir = detect_dir()
        print(all_dir[0]["Model"])
        print(all_dir[0]["Size (GB)"])
    """
    if sys.platform != "win32":
        raise OSError("detect_dir() is only supported on Windows.")

    ps_cmd = (
        "Get-Disk | Where-Object { $_.BusType -eq 'USB' } | "
        "Select-Object Number, FriendlyName, SerialNumber, Size, "
        "BusType, OperationalStatus | ConvertTo-Json"
    )

    raw = _run_powershell(ps_cmd)

    if not raw:
        return []

    data = json.loads(raw)

    # PowerShell returns a single dict when there is only one disk
    if isinstance(data, dict):
        data = [data]

    disks = []
    for d in data:
        size_bytes = d.get("Size", 0) or 0
        size_gb = round(size_bytes / (1024 ** 3), 2)
        disk = {
            # Public, human-readable keys (match the comment in test/main.py)
            "Disk#": d.get("Number"),
            "Model": (d.get("FriendlyName") or "Unknown").strip(),
            "Serial": (d.get("SerialNumber") or "Unknown").strip(),
            "Size (GB)": size_gb,
            "Status": (d.get("OperationalStatus") or "Unknown"),
            # Private keys used internally by sanitizer / recovery
            "_number": d.get("Number"),
            "_size_bytes": size_bytes,
        }
        disks.append(disk)

    disks.sort(key=lambda x: x["Disk#"] or 0)
    return disks
