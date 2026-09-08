"""
doctor_digital.usb_sanitizer
=============================
Two public functions:

    complete_sanitize(disk)
        Full sector-level wipe of an entire USB disk.
        `disk` is a dict returned by detect_dir().

    sanitize_dir(path)
        Secure overwrite + deletion of every file inside a
        specific directory on a removable drive.
"""

import ctypes
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

AUDIT_DIR = os.path.join(os.path.expanduser("~"), "usb_sanitizer_logs")

# ------------------------------------------------------------------ helpers

def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _require_windows_admin():
    if sys.platform != "win32":
        raise OSError("usb_sanitizer requires Windows.")
    if not _is_admin():
        raise PermissionError(
            "Must be run from an elevated (Administrator) terminal.\n"
            "Right-click your terminal and choose 'Run as administrator'."
        )


def _run_powershell(command: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and result.stderr.strip():
        raise RuntimeError(f"PowerShell error: {result.stderr.strip()}")
    return result.stdout.strip()


def _run_diskpart(commands: list) -> str:
    script_text = "\n".join(commands) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(script_text)
        script_path = f.name
    try:
        result = subprocess.run(
            ["diskpart", "/s", script_path],
            capture_output=True,
            text=True,
        )
        return result.stdout
    finally:
        os.unlink(script_path)


# ------------------------------------------------------------------ confirmation

def _confirm_disk(disk: dict) -> bool:
    print("\n" + "=" * 70)
    print("DESTRUCTIVE ACTION CONFIRMATION")
    print("=" * 70)
    print(f"  Disk#   : {disk.get('Disk#')}")
    print(f"  Model   : {disk.get('Model')}")
    print(f"  Serial  : {disk.get('Serial')}")
    print(f"  Size    : {disk.get('Size (GB)')} GB")
    print("\nALL DATA ON THIS DISK WILL BE PERMANENTLY DESTROYED.")
    print("This cannot be undone.\n")

    serial = disk.get("Serial", "")
    suffix = serial[-4:] if len(serial) >= 4 else serial
    disk_num = str(disk.get("Disk#", ""))

    if input(f"Type the disk NUMBER ({disk_num}): ").strip() != disk_num:
        print("Disk number mismatch. Aborting.")
        return False

    if input(f"Type the LAST 4 CHARS of the serial ({suffix}): ").strip().upper() != suffix.upper():
        print("Serial mismatch. Aborting.")
        return False

    if input("Type exactly WIPE THIS DRIVE to proceed: ").strip() != "WIPE THIS DRIVE":
        print("Confirmation phrase mismatch. Aborting.")
        return False

    return True


# ------------------------------------------------------------------ wipe steps

def _diskpart_clean_all(disk_number: int) -> dict:
    start = time.time()
    output = _run_diskpart([f"select disk {disk_number}", "clean all"])
    elapsed = time.time() - start
    success = "DiskPart succeeded" in output or "successfully" in output.lower()
    return {"step": "clean_all", "success": success,
            "elapsed_sec": round(elapsed, 1), "raw_output": output}


def _create_volume_fill_random(disk_number: int, drive_letter: str = "Z") -> dict:
    start = time.time()
    _run_diskpart([
        f"select disk {disk_number}",
        "create partition primary",
        "format fs=ntfs quick",
        f"assign letter={drive_letter}",
    ])
    time.sleep(2)

    target = f"{drive_letter}:\\__sanitize_fill__.tmp"
    bytes_written = 0
    chunk = 64 * 1024 * 1024  # 64 MB

    try:
        with open(target, "wb") as f:
            while True:
                try:
                    f.write(os.urandom(chunk))
                    bytes_written += chunk
                except OSError:
                    break
    except OSError:
        pass

    try:
        os.remove(target)
    except OSError:
        pass

    return {
        "step": "random_fill_pass",
        "success": bytes_written > 0,
        "bytes_written": bytes_written,
        "elapsed_sec": round(time.time() - start, 1),
    }


def _recreate_volume(disk_number: int, drive_letter: str = "Z", fs: str = "exfat") -> dict:
    start = time.time()
    output = _run_diskpart([
        f"select disk {disk_number}",
        "create partition primary",
        f"format fs={fs} quick",
        f"assign letter={drive_letter}",
    ])
    return {
        "step": "recreate_volume",
        "success": "successfully" in output.lower(),
        "elapsed_sec": round(time.time() - start, 1),
        "fs": fs,
    }


def _verify_wipe(disk_number: int, sample_count: int = 8, sample_size: int = 4096) -> dict:
    path = rf"\\.\PhysicalDrive{disk_number}"
    results = []
    try:
        with open(path, "rb", buffering=0) as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            for i in range(sample_count):
                offset = int((size - sample_size) * (i / max(sample_count - 1, 1)))
                offset -= offset % 512
                f.seek(offset)
                data = f.read(sample_size)
                results.append({
                    "offset": offset,
                    "zeroed": all(b == 0 for b in data),
                    "partition_signature_found": data[510:512] == b"\x55\xAA" if len(data) >= 512 else False,
                })
    except (PermissionError, OSError) as e:
        return {"verified": False, "error": str(e), "samples": []}

    clean = sum(1 for r in results if r["zeroed"] and not r["partition_signature_found"])
    return {
        "verified": True,
        "sample_count": len(results),
        "clean_sample_count": clean,
        "pass_rate": round(clean / len(results), 3) if results else 0,
        "samples": results,
    }


def _confidence_score(clean_result, random_result, verification) -> dict:
    score = 0
    breakdown = {}

    if clean_result.get("success"):
        score += 40
        breakdown["zero_wipe_pass"] = 40
    else:
        breakdown["zero_wipe_pass"] = 0

    if random_result and random_result.get("success"):
        score += 20
        breakdown["random_fill_pass"] = 20
    else:
        breakdown["random_fill_pass"] = 0

    if verification.get("verified"):
        v_pts = round(verification.get("pass_rate", 0) * 30)
        score += v_pts
        breakdown["verification"] = v_pts
    else:
        breakdown["verification"] = 0

    breakdown["defense_in_depth_bonus"] = 0
    score = min(score, 90)
    breakdown["cap_note"] = "max 90/100 without confirmed ATA Secure Erase"

    return {"score": score, "breakdown": breakdown, "max_possible": 90}


def _write_audit_log(disk: dict, steps: list, verification: dict, score: dict) -> str:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_id = str(uuid.uuid4())

    record = {
        "log_id": log_id,
        "timestamp": ts,
        "operator": os.environ.get("USERNAME", "unknown"),
        "hostname": os.environ.get("COMPUTERNAME", "unknown"),
        "target_disk": disk,
        "steps": steps,
        "verification": verification,
        "confidence_score": score,
        "limitations_disclosed": (
            "Software wiping over a USB bridge cannot guarantee erasure of "
            "wear-leveling-remapped physical NAND cells. For regulatory/"
            "classified requirements follow NIST SP 800-88 Purge or Destroy."
        ),
    }

    json_path = os.path.join(AUDIT_DIR, f"wipe_audit_{ts}_{log_id[:8]}.json")
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2)

    with open(json_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    with open(json_path + ".sha256", "w") as f:
        f.write(f"{file_hash}  {os.path.basename(json_path)}\n")

    return json_path


# ------------------------------------------------------------------ public API

def complete_sanitize(disk: dict, passes: int = 2, drive_letter: str = "Z") -> dict:
    """
    Perform a full sector-level sanitization of a USB disk.

    Parameters
    ----------
    disk : dict
        A disk dict returned by ``detect_dir()``.
    passes : int
        1 = zero wipe only.
        2 = zero wipe + random fill + re-zero (default, recommended).
    drive_letter : str
        Temporary drive letter used during the random-fill pass (default "Z").

    Returns
    -------
    dict with keys:
        success         bool
        confidence_score int   (0-90)
        audit_log_path  str
    """
    _require_windows_admin()

    disk_number = disk.get("_number") or disk.get("Disk#")
    if disk_number is None:
        raise ValueError("disk dict must contain 'Disk#' or '_number'.")

    if not _confirm_disk(disk):
        print("Aborted by user.")
        return {"success": False, "confidence_score": 0, "audit_log_path": None}

    steps = []

    print("\n[1/4] Zero-wiping entire disk (diskpart clean all)…")
    clean = _diskpart_clean_all(disk_number)
    steps.append(clean)
    print(f"      done in {clean['elapsed_sec']}s — success={clean['success']}")

    random_result = {}
    if passes >= 2:
        print(f"\n[2/4] Random-data fill pass on letter {drive_letter}:…")
        random_result = _create_volume_fill_random(disk_number, drive_letter)
        steps.append(random_result)
        print(f"      {round(random_result['bytes_written']/(1024**3), 2)} GB written — re-zeroing…")
        final_clean = _diskpart_clean_all(disk_number)
        steps.append(final_clean)
    else:
        print("\n[2/4] Skipping random-fill pass (passes=1).")

    print("\n[3/4] Verifying wipe by sampling raw sectors…")
    verification = _verify_wipe(disk_number)
    print(f"      clean samples: {verification.get('clean_sample_count')}/{verification.get('sample_count')}")

    print("\n[4/4] Recreating usable volume on wiped disk…")
    final_vol = _recreate_volume(disk_number, drive_letter)
    steps.append(final_vol)
    print(f"      done in {final_vol['elapsed_sec']}s — success={final_vol['success']}")

    score = _confidence_score(clean, random_result, verification)
    log_path = _write_audit_log(disk, steps, verification, score)

    print("\n" + "=" * 70)
    print(f"SANITIZATION CONFIDENCE SCORE: {score['score']} / 100")
    print(f"Audit log: {log_path}")
    print("=" * 70)

    return {
        "success": clean["success"],
        "confidence_score": score["score"],
        "audit_log_path": log_path,
    }


def sanitize_dir(path: str, passes: int = 2) -> bool:
    """
    Securely overwrite and delete every file inside `path`.

    The target directory must be on a removable (USB) drive and must
    not be the root of that drive.

    Parameters
    ----------
    path : str
        Absolute path to the directory to sanitize.
    passes : int
        Number of overwrite passes (default 2: random then zeros).

    Returns
    -------
    bool — True if all files were sanitized successfully, False otherwise.
    """
    _require_windows_admin()

    # Re-use the logic from dir_sanitizer
    from doctor_digital._dir_sanitizer import sanitize_directory
    return sanitize_directory(path, passes=passes)
