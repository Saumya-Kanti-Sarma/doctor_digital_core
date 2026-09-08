"""
doctor_digital._dir_sanitizer
==============================
Internal module — secure directory sanitization logic.
Use usb_sanitizer.sanitize_dir() as the public entry point.
"""

import ctypes
import os
import random
import string
import sys
from pathlib import Path

DRIVE_REMOVABLE = 2


def _get_drive_type(path) -> int:
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(root)


def _is_removable(path) -> bool:
    try:
        return _get_drive_type(path) == DRIVE_REMOVABLE
    except Exception:
        return False


def _is_root(path) -> bool:
    p = Path(path).resolve()
    return p.parent == Path(p.anchor)


def _is_safe_target(path) -> bool:
    p = Path(path).resolve()

    if not p.exists():
        print(f"ERROR: Directory does not exist: {p}")
        return False

    if not p.is_dir():
        print(f"ERROR: Target is not a directory: {p}")
        return False

    if not _is_removable(p):
        print("\nSAFETY BLOCK")
        print("-" * 60)
        print(f"Target: {p}")
        print("This directory is NOT on a removable USB drive. Refusing.")
        return False

    if _is_root(p):
        print("\nSAFETY BLOCK")
        print("-" * 60)
        print("Target is the ROOT of the USB drive. Refusing.")
        return False

    return True


def _confirm_target(path) -> bool:
    p = Path(path).resolve()
    print("\n" + "=" * 70)
    print("!!! DIRECTORY SANITIZATION !!!")
    print("=" * 70)
    print(f"Target : {p}")
    print(f"Drive  : {p.drive}")
    print("\nWARNING: EVERY FILE INSIDE THIS DIRECTORY WILL BE DESTROYED.")
    print("This cannot be undone.")

    typed = input("\nType the FULL DIRECTORY PATH to confirm: ").strip().strip('"')
    try:
        typed = str(Path(typed).resolve())
    except Exception:
        return False

    if typed.lower() != str(p).lower():
        print("Path mismatch. Aborting.")
        return False

    if input('Type exactly "SANITIZE DIRECTORY" to proceed: ').strip() != "SANITIZE DIRECTORY":
        print("Confirmation phrase mismatch. Aborting.")
        return False

    return True


def _random_name(length: int = 24) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def _overwrite_file(path, passes: int = 2) -> dict:
    p = Path(path)
    try:
        size = p.stat().st_size
        if size == 0:
            return {"success": True, "size": 0, "passes": 0}

        chunk = 1024 * 1024  # 1 MB

        with open(p, "r+b", buffering=0) as f:
            for pass_num in range(passes):
                f.seek(0)
                remaining = size
                while remaining > 0:
                    amount = min(chunk, remaining)
                    data = os.urandom(amount) if pass_num == 0 else b"\x00" * amount
                    f.write(data)
                    remaining -= amount
                f.flush()
                os.fsync(f.fileno())

        return {"success": True, "size": size, "passes": passes}

    except (PermissionError, OSError) as e:
        return {"success": False, "size": 0, "passes": passes, "error": str(e)}


def _sanitize_file(path, passes: int = 2) -> dict:
    p = Path(path)
    print(f"  Sanitizing: {p}")

    result = _overwrite_file(p, passes)
    if not result["success"]:
        print(f"  ERROR: {result.get('error')}")
        return {"path": str(p), "success": False, "error": result.get("error")}

    try:
        new_path = p.with_name("." + _random_name() + ".tmp")
        p.rename(new_path)
    except OSError as e:
        print(f"  Rename failed: {e}")
        return {"path": str(p), "success": False, "error": str(e)}

    try:
        new_path.unlink()
    except OSError as e:
        print(f"  Delete failed: {e}")
        return {"path": str(p), "success": False, "error": str(e)}

    print("  OK")
    return {"path": str(p), "success": True,
            "size": result["size"], "passes": result["passes"]}


def sanitize_directory(directory: str, passes: int = 2) -> bool:
    """
    Securely overwrite and delete every file inside `directory`.

    Returns True if all files succeeded, False if any failed.
    """
    if sys.platform != "win32":
        raise OSError("sanitize_directory() is only supported on Windows.")

    directory = Path(directory).resolve()

    if not _is_safe_target(directory):
        return False

    if not _confirm_target(directory):
        print("\nSanitization cancelled.")
        return False

    print("\nScanning directory…")
    files = [Path(root) / f for root, _, fnames in os.walk(directory) for f in fnames]
    print(f"Files found: {len(files)}")

    results = [_sanitize_file(fp, passes=passes) for fp in files]

    # Remove empty directories (deepest first)
    print("\nRemoving directory structure…")
    for root, dirs, _ in os.walk(directory, topdown=False):
        for d in dirs:
            try:
                (Path(root) / d).rmdir()
            except OSError:
                pass
    try:
        directory.rmdir()
    except OSError as e:
        print(f"WARNING: Could not remove root directory: {e}")

    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    print("\n" + "=" * 70)
    print("DIRECTORY SANITIZATION COMPLETE")
    print("=" * 70)
    print(f"Files found     : {len(files)}")
    print(f"Files sanitized : {successful}")
    print(f"Files failed    : {failed}")
    print(f"Overwrite passes: {passes}")
    print("\nResult: " + ("SUCCESS" if failed == 0 else "PARTIAL FAILURE"))
    print("\nNOTE: USB flash wear-leveling means software overwriting cannot")
    print("guarantee every physical NAND cell was erased.")
    print("=" * 70)

    return failed == 0
