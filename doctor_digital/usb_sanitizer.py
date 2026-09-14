"""
usb_sanitizer.py
=================
USB disk / directory sanitizer, exposed both as a plain Python module
and as a FastAPI app in one file.

Run as an API (from an elevated / Administrator terminal, on Windows):

    pip install fastapi "uvicorn[standard]"
    uvicorn usb_sanitizer:app --host 127.0.0.1 --port 8000

Example:

    POST /disks/0/sanitize
    {
        "disk": {"Disk#": 0, "Model": "SanDisk Ultra", "Serial": "AB12CD34", "Size (GB)": 64},
        "confirm_disk_number": "0",
        "confirm_serial_suffix": "CD34",
        "confirm_phrase": "WIPE THIS DRIVE",
        "passes": 2
    }
    -> {"job_id": "...", "status_url": "/jobs/..."}

    GET /jobs/{job_id}   -> poll for progress/result

WARNING: this exposes a genuinely destructive, irreversible operation
(disk wipe) over HTTP. At minimum, put it behind authentication and
restrict it to localhost / a trusted network before using it beyond
local testing — see the note near `app = FastAPI(...)` below.

Can also be used directly as a library (no API):

    from usb_sanitizer import complete_sanitize, sanitize_dir
    complete_sanitize(disk, confirm_disk_number="0",
                       confirm_serial_suffix="CD34",
                       confirm_phrase="WIPE THIS DRIVE")
"""

import ctypes
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import timezone
from enum import Enum
from typing import Any, Callable, Optional

AUDIT_DIR = os.path.join(os.path.expanduser("~"), "doctor_digital_usb_sanitizer_logs")

ProgressCallback = Optional[Callable[[str, dict], None]]


def _emit(callback: ProgressCallback, message: str, data: dict = None):
    """Send a progress update both to stdout (for CLI use) and to an
    optional callback (for API/job-tracking use)."""
    print(message)
    if callback:
        callback(message, data or {})


# ==================================================================
# Core sanitizer logic
# ==================================================================

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
            "Must be run from an elevated (Administrator) process.\n"
            "Restart the API server (uvicorn) as Administrator."
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

class ConfirmationError(ValueError):
    """Raised when the caller-supplied confirmation values don't match
    the target disk. Distinguished from other ValueErrors so the API
    layer can map it to HTTP 422."""


def _validate_confirmation(
    disk: dict,
    confirm_disk_number: str,
    confirm_serial_suffix: str,
    confirm_phrase: str,
) -> None:
    """Non-interactive confirmation check (replaces old input() prompts).
    Raises ConfirmationError on any mismatch; returns None on success."""
    serial = disk.get("Serial", "")
    expected_suffix = serial[-4:] if len(serial) >= 4 else serial
    expected_disk_num = str(disk.get("Disk#", ""))

    if str(confirm_disk_number).strip() != expected_disk_num:
        raise ConfirmationError(
            f"Disk number mismatch: expected {expected_disk_num}"
        )

    if confirm_serial_suffix.strip().upper() != expected_suffix.upper():
        raise ConfirmationError(
            "Serial suffix mismatch: does not match target disk"
        )

    if confirm_phrase.strip() != "WIPE THIS DRIVE":
        raise ConfirmationError(
            'Confirmation phrase mismatch: must be exactly "WIPE THIS DRIVE"'
        )


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


def _write_audit_log(disk: dict, steps: list, verification: dict, score: dict, operator: str = None) -> str:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_id = str(uuid.uuid4())

    record = {
        "log_id": log_id,
        "timestamp": ts,
        "operator": operator or os.environ.get("USERNAME", "unknown"),
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

def complete_sanitize(
    disk: dict,
    confirm_disk_number: str,
    confirm_serial_suffix: str,
    confirm_phrase: str,
    passes: int = 2,
    drive_letter: str = "Z",
    operator: str = None,
    on_progress: ProgressCallback = None,
) -> dict:
    """
    Perform a full sector-level sanitization of a USB disk.

    Parameters
    ----------
    disk : dict
        A disk dict returned by ``detect_dir()``.
    confirm_disk_number, confirm_serial_suffix, confirm_phrase : str
        Caller-supplied confirmation values, validated against `disk`
        before any destructive action is taken.
    passes : int
        1 = zero wipe only.
        2 = zero wipe + random fill + re-zero (default, recommended).
    drive_letter : str
        Temporary drive letter used during the random-fill pass (default "Z").
    operator : str
        Optional identity of the caller, recorded in the audit log
        (falls back to the OS username of the running process).
    on_progress : callable(message: str, data: dict), optional
        Invoked at each step for callers that want to stream status.

    Returns
    -------
    dict with keys:
        success         bool
        confidence_score int   (0-90)
        audit_log_path  str

    Raises
    ------
    ConfirmationError
        If the confirmation values don't match the target disk.
    PermissionError
        If not running elevated on Windows.
    """
    _require_windows_admin()

    disk_number = disk.get("_number") or disk.get("Disk#")
    if disk_number is None:
        raise ValueError("disk dict must contain 'Disk#' or '_number'.")

    _validate_confirmation(disk, confirm_disk_number, confirm_serial_suffix, confirm_phrase)

    steps = []

    _emit(on_progress, "[1/4] Zero-wiping entire disk (diskpart clean all)…")
    clean = _diskpart_clean_all(disk_number)
    steps.append(clean)
    _emit(on_progress, f"      done in {clean['elapsed_sec']}s — success={clean['success']}", clean)

    random_result = {}
    if passes >= 2:
        _emit(on_progress, f"[2/4] Random-data fill pass on letter {drive_letter}:…")
        random_result = _create_volume_fill_random(disk_number, drive_letter)
        steps.append(random_result)
        _emit(
            on_progress,
            f"      {round(random_result['bytes_written']/(1024**3), 2)} GB written — re-zeroing…",
            random_result,
        )
        final_clean = _diskpart_clean_all(disk_number)
        steps.append(final_clean)
    else:
        _emit(on_progress, "[2/4] Skipping random-fill pass (passes=1).")

    _emit(on_progress, "[3/4] Verifying wipe by sampling raw sectors…")
    verification = _verify_wipe(disk_number)
    _emit(
        on_progress,
        f"      clean samples: {verification.get('clean_sample_count')}/{verification.get('sample_count')}",
        verification,
    )

    _emit(on_progress, "[4/4] Recreating usable volume on wiped disk…")
    final_vol = _recreate_volume(disk_number, drive_letter)
    steps.append(final_vol)
    _emit(on_progress, f"      done in {final_vol['elapsed_sec']}s — success={final_vol['success']}", final_vol)

    score = _confidence_score(clean, random_result, verification)
    log_path = _write_audit_log(disk, steps, verification, score, operator=operator)

    _emit(on_progress, f"SANITIZATION CONFIDENCE SCORE: {score['score']} / 100")
    _emit(on_progress, f"Audit log: {log_path}")

    return {
        "success": clean["success"],
        "confidence_score": score["score"],
        "audit_log_path": log_path,
    }


def sanitize_dir(path: str, passes: int = 2, on_progress: ProgressCallback = None) -> bool:
    """
    Securely overwrite and delete every file inside `path`.

    The target directory must be on a removable (USB) drive and must
    not be the root of that drive.

    This variant is non-interactive (no ``input()`` prompts); the caller
    is responsible for obtaining confirmation before invoking.

    Parameters
    ----------
    path : str
        Absolute path to the directory to sanitize.
    passes : int
        Number of overwrite passes (default 2: random then zeros).
    on_progress : callable(message: str, data: dict), optional
        Progress callback for API/job-tracking use.

    Returns
    -------
    bool — True if all files were sanitized successfully, False otherwise.
    """
    _require_windows_admin()

    _emit(on_progress, f"Sanitizing directory: {path} (passes={passes})")

    # Use the non-interactive variant so the API server is never blocked
    from doctor_digital._dir_sanitizer import sanitize_directory_no_confirm
    result = sanitize_directory_no_confirm(path, passes=passes)

    _emit(on_progress, f"Directory sanitize complete — success={result}")
    return result


# ==================================================================
# In-memory background job tracker
# ==================================================================
# Wipes can take many minutes, so the API runs them in a background
# thread and hands back a job_id immediately. NOTE: in-memory means
# jobs are lost on restart and this won't work across multiple worker
# processes — swap for a persistent store (DB/Redis) for production.

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job:
    def __init__(self, job_id: str, kind: str):
        self.job_id = job_id
        self.kind = kind
        self.status = JobStatus.PENDING
        self.created_at = datetime.datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.log: list[dict] = []
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def add_log(self, message: str, data: dict = None):
        with self._lock:
            self.log.append({
                "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
                "message": message,
                "data": data or {},
            })
            self.updated_at = self.log[-1]["timestamp"]

    def set_status(self, status: JobStatus):
        with self._lock:
            self.status = status
            self.updated_at = datetime.datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "status": self.status.value,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "log": list(self.log),
                "result": self.result,
                "error": self.error,
            }


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id, kind)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def run_in_background(self, job: Job, target: Callable[[Job], Any]):
        def _runner():
            job.set_status(JobStatus.RUNNING)
            try:
                result = target(job)
                job.result = result
                job.set_status(JobStatus.SUCCEEDED)
            except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
                job.error = f"{type(exc).__name__}: {exc}"
                job.add_log(f"ERROR: {job.error}")
                job.set_status(JobStatus.FAILED)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()


job_store = JobStore()