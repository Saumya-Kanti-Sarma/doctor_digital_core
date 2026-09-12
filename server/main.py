"""
Doctor Digital — FastAPI server
================================
Run (elevated / Administrator terminal):

    cd server
    uvicorn main:app --host 127.0.0.1 --port 8000 --reload

All destructive endpoints (sanitize-drive, sanitize-drive-path) run in
background threads and return a job_id immediately.  Poll /jobs/{job_id}
for progress and the final result.

Recovery (recover-drive) also runs in the background and streams its
progress log entries via the job polling endpoint.
"""

import json
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from doctor_digital import detect_dir
from doctor_digital import read_dir as read_dir_api
from doctor_digital import usb_sanitizer
from doctor_digital import usb_recovery
from doctor_digital.usb_sanitizer import job_store, JobStatus

app = FastAPI(
    title="Doctor Digital",
    description="USB sanitization and recovery API",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"message": "Doctor Digital API is running."}


# ---------------------------------------------------------------------------
# Disk enumeration
# ---------------------------------------------------------------------------

@app.get("/all-dir", summary="List all connected USB disks")
def get_dir():
    """
    Returns every USB disk currently visible to Windows.

    Each entry includes Disk#, Model, Serial, Size (GB), Status, and
    the Drives list (e.g. ["D:\\\\"]).
    """
    all_dir = detect_dir()
    return all_dir


# ---------------------------------------------------------------------------
# Directory tree
# ---------------------------------------------------------------------------

@app.get("/read-dir", summary="Recursive directory tree")
def get_read_dir(path: str = Query(..., description="Absolute path to read, e.g. D:\\\\")):
    """
    Walk *path* recursively and return the full folder/file tree as JSON.

    Each node contains: name, path, type (dir|file), size (bytes), children.
    """
    try:
        tree = read_dir_api(path)
        return tree
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Full-disk sanitization  (background job + SSE stream)
# ---------------------------------------------------------------------------

class SanitizeDriveRequest(BaseModel):
    disk: dict
    """A disk dict as returned by /all-dir."""

    confirm_disk_number: str
    """Must equal the Disk# of the target disk as a string."""

    confirm_serial_suffix: str
    """Last 4 characters of the disk's serial number."""

    confirm_phrase: str
    """Must be exactly: WIPE THIS DRIVE"""

    passes: int = 2
    """1 = zero wipe only.  2 = zero + random fill + re-zero (default)."""

    drive_letter: str = "Z"
    """Temporary drive letter used during the random-fill pass."""

    operator: Optional[str] = None
    """Optional name recorded in the audit log."""


@app.post(
    "/sanitize-drive",
    summary="Full sector-level USB disk wipe (background job)",
    status_code=202,
)
def sanitize_drive(req: SanitizeDriveRequest):
    """
    Kick off a complete disk sanitization in the background.

    Returns a **job_id** immediately.  Poll ``GET /jobs/{job_id}`` for
    live progress log entries and the final result.

    The operation is **irreversible** — all data on the disk will be
    destroyed.  Confirmation fields must match the target disk exactly.
    """
    job = job_store.create(kind="sanitize_drive")

    def _run(job):
        return usb_sanitizer.complete_sanitize(
            disk=req.disk,
            confirm_disk_number=req.confirm_disk_number,
            confirm_serial_suffix=req.confirm_serial_suffix,
            confirm_phrase=req.confirm_phrase,
            passes=req.passes,
            drive_letter=req.drive_letter,
            operator=req.operator,
            on_progress=lambda msg, data: job.add_log(msg, data),
        )

    job_store.run_in_background(job, _run)

    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "status_url": f"/jobs/{job.job_id}",
        "stream_url": f"/jobs/{job.job_id}/stream",
    }


# ---------------------------------------------------------------------------
# Directory-level sanitization  (background job)
# ---------------------------------------------------------------------------

class SanitizePathRequest(BaseModel):
    path: str
    """Absolute path to the directory to sanitize, e.g. D:\\SuspectFolder"""

    passes: int = 2
    """Number of overwrite passes (default 2)."""

    operator: Optional[str] = None
    """Optional name recorded in logs."""


@app.post(
    "/sanitize-drive-path",
    summary="Securely wipe a single directory on a USB drive (background job)",
    status_code=202,
)
def sanitize_drive_path(req: SanitizePathRequest):
    """
    Securely overwrite and delete every file inside the given *path*.

    The target must be on a removable USB drive and must **not** be the
    root of that drive — both conditions are enforced server-side.

    Returns a **job_id**; poll ``GET /jobs/{job_id}`` for progress.
    """
    job = job_store.create(kind="sanitize_dir")

    def _run(job):
        ok = usb_sanitizer.sanitize_dir(
            path=req.path,
            passes=req.passes,
            on_progress=lambda msg, data: job.add_log(msg, data),
        )
        return {"success": ok, "path": req.path}

    job_store.run_in_background(job, _run)

    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "status_url": f"/jobs/{job.job_id}",
        "stream_url": f"/jobs/{job.job_id}/stream",
    }


# ---------------------------------------------------------------------------
# Recovery  (background job)
# ---------------------------------------------------------------------------

class RecoverDriveRequest(BaseModel):
    disk: dict
    """A disk dict returned by /all-dir, OR {"_number": <int>} for a disk number."""

    files: list[str]
    """File types to recover. Supported: "jpeg", "jpg", "png", "text", "txt"."""

    output_dir: str = "recovered_files"
    """Directory where recovered files will be saved."""


@app.post(
    "/recover-drive",
    summary="Carve deleted files from a USB disk (background job)",
    status_code=202,
)
def recover_drive(req: RecoverDriveRequest):
    """
    Scan raw sectors of the target USB disk and carve back deleted files.

    Supported file types: ``jpeg``, ``jpg``, ``png``, ``text``, ``txt``.

    Returns a **job_id** immediately.  Poll ``GET /jobs/{job_id}`` for
    scan progress (GB read) and the final ``recovered`` count per type.

    **Note:** must be run from an elevated (Administrator) process.
    """
    job = job_store.create(kind="recover_drive")

    def _run(job):
        job.add_log(f"Starting recovery scan — types: {req.files}, output: {req.output_dir}")
        result = usb_recovery.recover(
            path=req.disk,
            files=req.files,
            output_dir=req.output_dir,
        )
        job.add_log("Recovery scan complete.", result)
        return result

    job_store.run_in_background(job, _run)

    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "status_url": f"/jobs/{job.job_id}",
        "stream_url": f"/jobs/{job.job_id}/stream",
    }


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}", summary="Poll a background job for status and logs")
def get_job(job_id: str):
    """
    Return the current status, full progress log, and result (if complete)
    for the given *job_id*.

    Possible ``status`` values: ``pending``, ``running``, ``succeeded``, ``failed``.
    """
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job.to_dict()


@app.get(
    "/jobs/{job_id}/stream",
    summary="Server-Sent Events stream of live progress for a job",
    response_class=StreamingResponse,
)
def stream_job(job_id: str):
    """
    Subscribe to a live **Server-Sent Events** stream for the given job.

    Each event is a JSON object matching a log entry:

        data: {"timestamp": "...", "message": "...", "data": {...}}

    The stream closes automatically when the job reaches a terminal state
    (``succeeded`` or ``failed``).
    """
    import time

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    def _event_generator():
        sent = 0
        while True:
            snapshot = job.to_dict()
            log_entries = snapshot["log"]

            # Send any new log lines
            for entry in log_entries[sent:]:
                yield f"data: {json.dumps(entry)}\n\n"
            sent = len(log_entries)

            status = snapshot["status"]
            if status in (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value):
                # Flush final result event and close
                yield f"data: {json.dumps({'status': status, 'result': snapshot['result'], 'error': snapshot['error']})}\n\n"
                break

            time.sleep(0.5)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
