"""
doctor_digital.detect
=====================
Enumerates removable USB disks visible to Windows.

Returns
-------
list of dict, each with keys:
    Disk#       int         Windows disk number
    Model       str         Friendly name / model string
    Serial      str         Serial number
    Size (GB)   float       Size rounded to 2 decimal places
    Status      str         Operational status (e.g. "Online")
    Drives      list[str]   Drive letters assigned to this disk (e.g. ["D:\\", "E:\\"])

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


def _get_disk_drive_letters() -> dict[int, list[str]]:
    """
    Return a mapping of disk number -> list of drive letters.

    Uses Get-Partition + Get-Volume to resolve physical disk numbers
    to their assigned drive letters (e.g. {1: ["D:\\", "E:\\"]}).
    """
    ps_cmd = (
        "Get-Partition | Where-Object { $_.DriveLetter } | "
        "Select-Object DiskNumber, DriveLetter | ConvertTo-Json"
    )
    raw = _run_powershell(ps_cmd)

    if not raw:
        return {}

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    mapping: dict[int, list[str]] = {}
    for entry in data:
        disk_num = entry.get("DiskNumber")
        letter = entry.get("DriveLetter")
        if disk_num is None or not letter:
            continue
        drive = f"{letter}:\\"
        mapping.setdefault(disk_num, []).append(drive)

    return mapping


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
        print(all_dir[0]["Drives"])   # e.g. ["D:\\"]
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

    drive_letter_map = _get_disk_drive_letters()

    disks = []
    for d in data:
        size_bytes = d.get("Size", 0) or 0
        size_gb = round(size_bytes / (1024 ** 3), 2)
        disk_num = d.get("Number")
        disk = {
            # Public, human-readable keys
            "Disk#": disk_num,
            "Model": (d.get("FriendlyName") or "Unknown").strip(),
            "Serial": (d.get("SerialNumber") or "Unknown").strip(),
            "Size (GB)": size_gb,
            "Status": (d.get("OperationalStatus") or "Unknown"),
            "Drives": drive_letter_map.get(disk_num, []),
            # Private keys used internally by sanitizer / recovery
            "_number": disk_num,
            "_size_bytes": size_bytes,
        }
        disks.append(disk)

    disks.sort(key=lambda x: x["Disk#"] or 0)
    return disks
