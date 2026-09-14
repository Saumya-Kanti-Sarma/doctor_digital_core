# Doctor Digital — Engineering Report
## USB Sanitization & Recovery Toolkit

---

## 1. System Overview

**Doctor Digital** is a Windows-only Python toolkit (`doctor_digital` package) for forensic-grade USB disk management. It covers four distinct capabilities:

| Module | Responsibility |
|---|---|
| `detect.py` | Enumerate attached USB disks via PowerShell |
| `read_dir.py` | Recursively map a drive's directory tree |
| `usb_sanitizer.py` | Sector-level disk wipe + directory-level secure delete; also exposes a FastAPI HTTP interface |
| `_dir_sanitizer.py` | Internal engine for per-file secure overwrite and deletion |
| `usb_recovery.py` | Raw sector carving to recover deleted files |

All destructive operations require Windows Administrator privileges (enforced at runtime via `ctypes.windll.shell32.IsUserAnAdmin()`).

---

## 2. USB Detection (`detect.py`)

### Mechanism
Uses two PowerShell calls via `subprocess`:

1. **`Get-Disk`** filtered by `BusType -eq 'USB'` — retrieves disk number, model, serial number, size, and operational status.
2. **`Get-Partition | Get-Volume`** — resolves physical disk numbers to assigned drive letters (e.g. `D:\`, `E:\`).

### Output Schema
Each detected disk is returned as a dict with both human-readable keys (`Disk#`, `Model`, `Serial`, `Size (GB)`, `Status`, `Drives`) and internal keys (`_number`, `_size_bytes`) consumed by the sanitizer and recovery modules.

### Constraints
- Windows-only; raises `OSError` on any other platform.
- A single connected USB disk is handled correctly (PowerShell returns a bare dict, not an array — the code normalizes this).

---

## 3. Directory Tree Reader (`read_dir.py`)

A recursive walker using `pathlib.Path`. Each node in the returned tree carries:

```
name, path, type ("dir"|"file"), size (bytes or None), children (list or None), error (str or None)
```

Directories are sorted with subdirectories first, then files (alphabetical). `PermissionError` is caught per-node and recorded in the `error` field rather than aborting the walk. This makes it safe to run against system volumes where some paths are protected.

---

## 4. File Sanitization

Sanitization is split into two scopes: **full disk** (sector-level) and **directory** (file-level).

### 4.1 Full Disk Sanitization — `complete_sanitize()` in `usb_sanitizer.py`

#### Pre-flight Checks
Before any destructive action:
- Elevated process check (`_require_windows_admin()`).
- **Triple confirmation** (`_validate_confirmation()`):
  - Caller must supply the exact disk number as a string.
  - Caller must supply the last 4 characters of the disk's serial number.
  - Caller must supply the exact phrase `"WIPE THIS DRIVE"`.
  - Any mismatch raises `ConfirmationError` (HTTP 422 in the API), and nothing is touched.

#### Wipe Pipeline (4 steps)

**Step 1 — Zero Wipe (`diskpart clean all`)**
Runs `diskpart` with `select disk N` + `clean all`. This overwrites the entire disk surface with zeros via the OS storage driver, including the partition table and all sectors.

**Step 2 — Random Data Fill (pass `>= 2` only)**
- Creates a primary NTFS partition using `diskpart`.
- Opens a temporary file on that partition and writes `os.urandom(64 MB)` chunks in a loop until an `OSError` (disk full) is raised — effectively filling every allocatable byte with cryptographically random data.
- Removes the temp file.
- Runs `diskpart clean all` again to zero-wipe the random data, leaving the disk in a clean state.

**Step 3 — Wipe Verification (`_verify_wipe()`)**
Opens the physical drive (`\\.\PhysicalDriveN`) in raw binary mode, seeks to 8 evenly-spaced offsets across the full disk size, and reads 4 KB at each location. Each sample is checked for:
- All-zero bytes (`zeroed`).
- Absence of the MBR partition signature (`0x55AA` at bytes 510–511).

Reports a `pass_rate` (ratio of clean samples to total samples) and a `clean_sample_count`.

**Step 4 — Volume Recreation (`_recreate_volume()`)**
Re-creates a primary partition formatted as **exFAT** (cross-platform compatible) via `diskpart`, making the drive immediately usable.

#### Confidence Score (`_confidence_score()`)

| Component | Max Points |
|---|---|
| Zero wipe pass succeeded | 40 |
| Random fill pass succeeded | 20 |
| Verification pass rate (×30) | 0–30 |
| **Total cap** | **90** |

The cap at 90/100 is intentional and documented: software wiping over a USB bridge cannot access wear-leveling-remapped NAND cells. Achieving 100/100 requires confirmed ATA Secure Erase (not available over USB).

---

### 4.2 Directory Sanitization — `sanitize_dir()` / `_dir_sanitizer.py`

#### Safety Guards (enforced even in the non-interactive API path)
1. **Drive type check** — uses `kernel32.GetDriveTypeW()` to confirm the target is on a removable drive (`DRIVE_REMOVABLE = 2`). Refuses if it's a fixed or network drive.
2. **Root check** — refuses if the target path is the root of the drive (e.g. `D:\`), preventing accidental full-drive deletion through the directory path.
3. **Existence / type check** — target must exist and be a directory.

#### Per-File Secure Overwrite (`_overwrite_file()`)
For each file discovered via `os.walk()`:

| Pass | Data Written |
|---|---|
| Pass 1 | `os.urandom()` — cryptographically random bytes, 1 MB at a time |
| Pass 2 | `\x00` bytes — zero fill |

Each pass calls `f.flush()` + `os.fsync(f.fileno())` to force data to the physical medium before the next pass begins.

Zero-size files are skipped (nothing to overwrite).

#### Post-Overwrite Steps (`_sanitize_file()`)
1. Overwrite the file content (above).
2. Rename the file to a random 24-character alphanumeric name with a `.tmp` extension (obfuscates the original filename in directory metadata).
3. Delete the renamed file with `Path.unlink()`.

#### Directory Cleanup
After all files are processed, `os.walk(topdown=False)` removes empty subdirectories from deepest to shallowest, then attempts to remove the root target directory itself.

#### Interactive vs. Non-Interactive
- `sanitize_directory()` — CLI entry point; uses `input()` to require the user to type the full path and then the phrase `"SANITIZE DIRECTORY"`.
- `sanitize_directory_no_confirm()` — API entry point; all safety guards still apply, but no `input()` calls (the FastAPI layer owns confirmation).

---

## 5. File Recovery (`usb_recovery.py`)

### Approach: File Carving
Reads the physical drive (`\\.\PhysicalDriveN`) in **4 MB raw chunks**, scanning each chunk for known file signatures, independent of the filesystem. This works even when the partition table or FAT/MFT has been wiped.

### Supported File Types

| Type | Start Signature | End Signature |
|---|---|---|
| JPEG/JPG | `\xFF\xD8\xFF` | `\xFF\xD9` |
| PNG | `\x89PNG\r\n\x1a\n` | `IEND` chunk trailer (12 bytes) |
| TEXT/TXT | Heuristic (no magic bytes) | Heuristic |

### Text Carving Heuristic
Because plain text has no magic bytes, the carver scans for runs of **≥ 64 consecutive printable ASCII bytes** (0x20–0x7E, plus tab/LF/CR). Each qualifying run is written as a `.txt` file. The minimum run length prevents single-word fragments from generating noise.

### Output
Recovered files are written to the `recovered_files/` directory (configurable) with sequential names: `recovered_jpeg_0001.jpg`, `recovered_png_0002.png`, etc. Each recovered file's sector offset is printed to stdout in hex.

### Return Value
```python
{
    "recovered": {"JPEG": 3, "PNG": 1, "TEXT": 12},
    "output_dir": "recovered_files"
}
```

---

## 6. Audit Logging

Audit logs are written exclusively by `complete_sanitize()` (full disk wipes). Directory sanitization does not currently produce a separate audit record.

### Location
```
%USERPROFILE%\usb_sanitizer_logs\
```
Defined by `AUDIT_DIR = os.path.join(os.path.expanduser("~"), "usb_sanitizer_logs")`.

### Log File Naming
```
wipe_audit_<YYYYMMDD_HHMMSS>_<first-8-chars-of-UUID>.json
```
Example: `wipe_audit_20260913_143022_a1b2c3d4.json`

### Log Record Schema
```json
{
  "log_id": "<UUID>",
  "timestamp": "YYYYMMDD_HHMMSS",
  "operator": "<OS username or caller-supplied name>",
  "hostname": "<COMPUTERNAME env var>",
  "target_disk": { ... disk dict ... },
  "steps": [
    { "step": "clean_all", "success": true, "elapsed_sec": 142.3, "raw_output": "..." },
    { "step": "random_fill_pass", "success": true, "bytes_written": 63350xxxxxx, "elapsed_sec": 310.1 },
    { "step": "recreate_volume", "success": true, "elapsed_sec": 4.2, "fs": "exfat" }
  ],
  "verification": {
    "verified": true,
    "sample_count": 8,
    "clean_sample_count": 8,
    "pass_rate": 1.0,
    "samples": [ { "offset": 0, "zeroed": true, "partition_signature_found": false }, ... ]
  },
  "confidence_score": {
    "score": 90,
    "breakdown": { "zero_wipe_pass": 40, "random_fill_pass": 20, "verification": 30 },
    "max_possible": 90
  },
  "limitations_disclosed": "Software wiping over a USB bridge cannot guarantee erasure of wear-leveling-remapped physical NAND cells. For regulatory/classified requirements follow NIST SP 800-88 Purge or Destroy."
}
```

### Integrity Hash
Immediately after writing the JSON, the code computes a **SHA-256** hash of the file's raw bytes and writes it to a companion file:
```
wipe_audit_<timestamp>_<id>.json.sha256
```
This allows offline verification that the log was not tampered with after the wipe.

### Operator Identity
The `operator` field is populated in order of preference:
1. Caller-supplied `operator` argument (API or library use).
2. `USERNAME` environment variable (Windows current user).
3. Falls back to `"unknown"`.

---

## 7. FastAPI HTTP Interface (`usb_sanitizer.py`)

The file is dual-purpose — it can be imported as a library or run as an API server:

```bash
uvicorn usb_sanitizer:app --host 127.0.0.1 --port 8000
```

Key design decisions:
- **Async job pattern** — wipes run in background threads via `JobStore` + `threading.Thread(daemon=True)`. The caller receives a `job_id` immediately and polls `GET /jobs/{job_id}` for progress.
- **In-memory job store** — jobs are lost on server restart. The code includes a note to swap this for a persistent store (DB/Redis) for production.
- **Thread-safe logging** — `Job.add_log()` and `Job.set_status()` use `threading.Lock()`.
- **Security warning** — the code explicitly warns that the API must be placed behind authentication and restricted to localhost or a trusted network before any production use.

---

## 8. Known Limitations & Disclosure

| Limitation | Detail |
|---|---|
| **NAND wear leveling** | USB flash drives remap worn cells internally. Software writes go through the bridge controller; remapped physical cells may retain old data and are inaccessible to the OS. |
| **Confidence cap at 90** | Reflects the above — 100/100 requires ATA Secure Erase confirmation, which is not available over USB. |
| **Recovery carver chunk boundary** | Signatures split across a 4 MB chunk boundary will not be detected. |
| **Text carver precision** | The heuristic produces many small fragments and cannot distinguish file boundaries. |
| **No multi-process API** | The in-memory `JobStore` does not survive restarts or work across multiple `uvicorn` workers. |
| **Directory sanitize has no audit log** | Only `complete_sanitize()` writes a structured audit record. |
| **Platform** | The entire toolkit is Windows-only due to PowerShell, `diskpart`, and `ctypes.windll` dependencies. |

---

## 9. Data Flow Summary

```
detect_dir()
    └─> PowerShell Get-Disk + Get-Partition
        └─> Returns list of disk dicts

complete_sanitize(disk, confirmations)
    ├─> _validate_confirmation()         # guard
    ├─> diskpart clean all               # step 1: zero wipe
    ├─> create partition + urandom fill  # step 2: random pass
    ├─> diskpart clean all               # step 2b: re-zero
    ├─> _verify_wipe()                   # step 3: sector sampling
    ├─> diskpart create + format exfat   # step 4: recreate volume
    ├─> _confidence_score()
    └─> _write_audit_log()  ──> wipe_audit_*.json + .sha256

sanitize_dir(path)
    └─> _dir_sanitizer.sanitize_directory_no_confirm()
        ├─> _is_safe_target()           # removable + not-root guard
        ├─> os.walk() → _sanitize_file() per file
        │       ├─> urandom overwrite (pass 1)
        │       ├─> zero overwrite (pass 2)
        │       ├─> fsync
        │       ├─> rename to random .tmp
        │       └─> unlink
        └─> rmdir (deepest first)

recover(disk, ["jpeg","png","text"])
    └─> open \\.\PhysicalDriveN raw
        └─> read 4 MB chunks
            ├─> _carve_binary()  # JPEG / PNG by signature
            └─> _carve_text()    # printable ASCII heuristic
                └─> write recovered_<type>_NNNN.<ext>
```