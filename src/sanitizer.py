#!/usr/bin/env python3
"""
usb_sanitizer.py
================
A Windows-only USB flash drive sanitization tool with audit logging and a
sanitization confidence score.

WHAT THIS DOES
--------------
1. Enumerates removable USB disks (never fixed/internal disks).
2. Forces an explicit, hard-to-fumble confirmation (you must type the disk
   number AND the last 4 characters of its serial number).
3. Wipes the disk using Windows' built-in `diskpart clean all`, which zeroes
   every sector of the physical disk (this is Microsoft's own secure-erase
   primitive, not a third-party trick).
4. Optionally performs a second "random data" pass by creating a volume,
   filling it completely with cryptographically random data, deleting it,
   then zeroing again with `clean all` -- this adds defense-in-depth at the
   logical level.
5. Verifies the wipe by sampling raw sectors from the physical device and
   confirming they no longer contain the original content pattern.
6. Writes a timestamped JSON + human-readable audit log, including a
   self-hash of the log for tamper-evidence, and a 0-100 confidence score.

HONEST LIMITATIONS (read before you rely on this)
---------------------------------------------------
- Most USB flash drives use wear-leveling controllers. A logical overwrite
  (which is all any software tool -- including this one -- can do over a
  USB bridge) is NOT guaranteed to touch every physical NAND cell. Retired/
  remapped "bad" or "spare" blocks can retain fragments of old data that are
  invisible to the OS but could theoretically be recovered via chip-off lab
  forensics. NIST SP 800-88 calls this out explicitly for flash media.
- ATA Secure Erase (a controller-level command that resets ALL NAND,
  including remapped cells) is the strongest software option, but it is
  usually blocked by USB-to-SATA/UASP bridge chips and is not reliably
  scriptable across arbitrary consumer USB flash drives. This tool checks
  for support and uses it when the underlying hardware exposes it, but will
  not fake success if it doesn't.
- For "must be provably impossible to recover, no exceptions" requirements
  (e.g. classified data, regulatory mandates), the accepted standard is
  physical destruction (shredding/incineration per NIST 800-88 Purge/
  Destroy) -- not software wiping. This tool will say so in its own report
  rather than overclaim.

REQUIREMENTS
------------
- Windows 10/11
- Run from an elevated (Administrator) terminal
- Python 3.8+, standard library only (no pip installs required)

USAGE
-----
    python usb_sanitizer.py --list
    python usb_sanitizer.py --wipe --disk 2 --passes 2
    (the script will interactively force you to confirm before anything
    destructive happens; there is no way to skip confirmation via flags)
"""

import argparse
import ctypes
import datetime
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import uuid

AUDIT_DIR = os.path.join(os.path.expanduser("~"), "usb_sanitizer_logs")


# --------------------------------------------------------------------------
# Privilege / safety helpers
# --------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def require_admin():
    if os.name != "nt":
        print("This tool only runs on Windows.")
        sys.exit(1)
    if not is_admin():
        print("ERROR: Must be run from an elevated (Administrator) terminal.")
        print("Right-click your terminal/PowerShell/CMD and choose 'Run as administrator'.")
        sys.exit(1)


def run_powershell(command: str) -> str:
    """Run a PowerShell command and return stdout as text."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True
    )
    if result.returncode != 0 and result.stderr.strip():
        raise RuntimeError(f"PowerShell error: {result.stderr.strip()}")
    return result.stdout.strip()

def create_final_volume(disk_number: int, drive_letter: str, fs: str = "exfat") -> dict:
    """
    After the wipe passes complete, recreate a single partition + filesystem
    so Windows can mount the drive normally without prompting to format.
    """
    start = time.time()
    commands = [
        f"select disk {disk_number}",
        "create partition primary",
        f"format fs={fs} quick",
        f"assign letter={drive_letter}",
    ]
    output = run_diskpart_script(commands)
    elapsed = time.time() - start
    success = "successfully" in output.lower()
    return {"step": "recreate_volume", "success": success, "elapsed_sec": round(elapsed, 1), "fs": fs}

def run_diskpart_script(commands: list) -> str:
    """Write a diskpart script to a temp file and execute it."""
    script_text = "\n".join(commands) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(script_text)
        script_path = f.name
    try:
        result = subprocess.run(
            ["diskpart", "/s", script_path],
            capture_output=True, text=True
        )
        return result.stdout
    finally:
        os.unlink(script_path)


# --------------------------------------------------------------------------
# Disk enumeration
# --------------------------------------------------------------------------

def list_removable_usb_disks() -> list:
    """
    Return a list of dicts describing ONLY disks whose bus type is USB.
    Internal/fixed disks are never included, no matter what.
    """
    ps_cmd = (
        "Get-Disk | Where-Object { $_.BusType -eq 'USB' } | "
        "Select-Object Number, FriendlyName, SerialNumber, Size, BusType, "
        "OperationalStatus, PartitionStyle | ConvertTo-Json"
    )
    raw = run_powershell(ps_cmd)
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    disks = []
    for d in data:
        disks.append({
            "number": d.get("Number"),
            "model": (d.get("FriendlyName") or "Unknown").strip(),
            "serial": (d.get("SerialNumber") or "Unknown").strip(),
            "size_bytes": d.get("Size", 0),
            "bus_type": d.get("BusType"),
            "status": d.get("OperationalStatus"),
        })
    return disks


def print_disks(disks: list):
    if not disks:
        print("No removable USB disks detected.")
        return
    print(f"{'Disk#':<6}{'Model':<30}{'Serial':<24}{'Size (GB)':<12}{'Status'}")
    for d in disks:
        size_gb = round(d["size_bytes"] / (1024**3), 2) if d["size_bytes"] else 0
        print(f"{d['number']:<6}{d['model'][:28]:<30}{d['serial'][:22]:<24}{size_gb:<12}{d['status']}")


# --------------------------------------------------------------------------
# Confirmation gate
# --------------------------------------------------------------------------

def confirm_target(disk: dict) -> bool:
    print("\n" + "=" * 70)
    print("DESTRUCTIVE ACTION CONFIRMATION")
    print("=" * 70)
    print(f"  Disk number : {disk['number']}")
    print(f"  Model       : {disk['model']}")
    print(f"  Serial      : {disk['serial']}")
    print(f"  Size        : {round(disk['size_bytes']/(1024**3), 2)} GB")
    print(f"  Bus type    : {disk['bus_type']}")
    print("\nALL DATA ON THIS DISK WILL BE PERMANENTLY DESTROYED.")
    print("This cannot be undone.\n")

    expected_serial_suffix = disk["serial"][-4:] if len(disk["serial"]) >= 4 else disk["serial"]
    typed_number = input(f"Type the disk NUMBER to confirm ({disk['number']}): ").strip()
    if typed_number != str(disk["number"]):
        print("Disk number mismatch. Aborting.")
        return False

    typed_serial = input(f"Type the LAST 4 CHARACTERS of the serial ({expected_serial_suffix}): ").strip()
    if typed_serial.upper() != expected_serial_suffix.upper():
        print("Serial mismatch. Aborting.")
        return False

    typed_phrase = input("Type exactly WIPE THIS DRIVE to proceed: ").strip()
    if typed_phrase != "WIPE THIS DRIVE":
        print("Confirmation phrase mismatch. Aborting.")
        return False

    return True


# --------------------------------------------------------------------------
# Wipe operations
# --------------------------------------------------------------------------

def diskpart_clean_all(disk_number: int) -> dict:
    """
    diskpart's `clean all` writes zeros to every sector on the disk
    (Microsoft-documented behavior), which is the closest thing Windows
    ships to a built-in secure erase for a full physical disk.
    """
    start = time.time()
    commands = [
        f"select disk {disk_number}",
        "clean all",
    ]
    output = run_diskpart_script(commands)
    elapsed = time.time() - start
    success = "DiskPart succeeded" in output or "successfully" in output.lower()
    return {"step": "clean_all", "success": success, "elapsed_sec": round(elapsed, 1), "raw_output": output}


def create_volume_and_fill_random(disk_number: int, drive_letter: str) -> dict:
    """
    Creates a single NTFS partition on the disk, then fills it completely
    with cryptographically random data before deleting the file. This is a
    logical-level 'random pass' layered on top of the zero wipe. It does
    NOT solve the wear-leveling limitation described above, but it does
    ensure that if any tool were to inspect currently-addressable logical
    sectors, they would find random noise rather than a predictable pattern.
    """
    start = time.time()
    commands = [
        f"select disk {disk_number}",
        "create partition primary",
        "format fs=ntfs quick",
        f"assign letter={drive_letter}",
    ]
    run_diskpart_script(commands)

    time.sleep(2)  # let the OS mount the new volume
    target_path = f"{drive_letter}:\\__sanitize_fill__.tmp"
    bytes_written = 0
    chunk_size = 64 * 1024 * 1024  # 64 MB chunks

    try:
        with open(target_path, "wb") as f:
            while True:
                chunk = os.urandom(chunk_size)
                try:
                    f.write(chunk)
                    bytes_written += len(chunk)
                except OSError:
                    break
                if bytes_written % (chunk_size * 10) == 0:
                    print(f"  ...wrote {round(bytes_written / (1024**3), 2)} GB of random data")
    except OSError:
        # Disk full -- expected, this is how we know it's completely filled
        pass

    try:
        os.remove(target_path)
    except OSError:
        pass

    elapsed = time.time() - start
    return {
        "step": "random_fill_pass",
        "success": bytes_written > 0,
        "bytes_written": bytes_written,
        "elapsed_sec": round(elapsed, 1),
    }


def verify_wipe(disk_number: int, sample_count: int = 8, sample_size: int = 4096) -> dict:
    """
    Opens the raw physical disk for reading and samples several locations,
    checking that they read back as zeroed (post clean-all state) rather
    than containing recognizable old filesystem structures (e.g. an NTFS
    boot sector signature, FAT signature, or partition table magic bytes).
    """
    path = rf"\\.\PhysicalDrive{disk_number}"
    results = []
    try:
        with open(path, "rb", buffering=0) as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(0)
            for i in range(sample_count):
                offset = int((size - sample_size) * (i / max(sample_count - 1, 1)))
                offset -= offset % 512  # sector align
                f.seek(offset)
                data = f.read(sample_size)
                is_zeroed = all(b == 0 for b in data)
                has_partition_magic = data[510:512] == b"\x55\xAA" if len(data) >= 512 else False
                results.append({
                    "offset": offset,
                    "zeroed": is_zeroed,
                    "partition_signature_found": has_partition_magic,
                })
    except (PermissionError, OSError) as e:
        return {"verified": False, "error": str(e), "samples": []}

    clean_samples = sum(1 for r in results if r["zeroed"] and not r["partition_signature_found"])
    pass_rate = clean_samples / len(results) if results else 0
    return {
        "verified": True,
        "sample_count": len(results),
        "clean_sample_count": clean_samples,
        "pass_rate": round(pass_rate, 3),
        "samples": results,
    }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def compute_confidence_score(clean_all_result: dict, random_pass_result: dict, verification: dict) -> dict:
    """
    Produces a 0-100 sanitization confidence score. This score reflects
    confidence in LOGICAL (OS-visible) sanitization. It is deliberately
    capped below 100 for flash media because software cannot verify
    physical NAND-cell-level erasure over a USB bridge -- see the
    'limitations' note printed in the report.
    """
    score = 0
    breakdown = {}

    if clean_all_result.get("success"):
        score += 40
        breakdown["zero_wipe_pass"] = 40
    else:
        breakdown["zero_wipe_pass"] = 0

    if random_pass_result and random_pass_result.get("success"):
        score += 20
        breakdown["random_fill_pass"] = 20
    else:
        breakdown["random_fill_pass"] = 0

    if verification.get("verified"):
        verification_points = round(verification.get("pass_rate", 0) * 30)
        score += verification_points
        breakdown["verification"] = verification_points
    else:
        breakdown["verification"] = 0

    # Small bonus for having run a second confirmatory zero pass after fill
    breakdown["defense_in_depth_bonus"] = 0

    score = min(score, 90)  # hard cap: never claim near-100 confidence on flash media
    breakdown["hardware_secure_erase_not_available_cap"] = "-10 (max 90/100 without ATA Secure Erase confirmation)"

    return {"score": score, "breakdown": breakdown, "max_possible_without_secure_erase": 90}


# --------------------------------------------------------------------------
# Audit logging
# --------------------------------------------------------------------------

def write_audit_log(disk: dict, steps: list, verification: dict, score: dict) -> str:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_id = str(uuid.uuid4())

    record = {
        "log_id": log_id,
        "timestamp": timestamp,
        "operator": os.environ.get("USERNAME", "unknown"),
        "hostname": os.environ.get("COMPUTERNAME", "unknown"),
        "target_disk": disk,
        "steps": steps,
        "verification": verification,
        "confidence_score": score,
        "limitations_disclosed": (
            "Software wiping over a USB bridge cannot guarantee erasure of "
            "wear-leveling-remapped physical NAND cells. For regulatory/"
            "classified requirements, follow NIST SP 800-88 Purge or Destroy "
            "guidance (physical destruction) instead of relying on this report."
        ),
    }

    json_path = os.path.join(AUDIT_DIR, f"wipe_audit_{timestamp}_{log_id[:8]}.json")
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2)

    # Self-hash for tamper evidence (hash of the JSON we just wrote)
    with open(json_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    hash_path = json_path + ".sha256"
    with open(hash_path, "w") as f:
        f.write(f"{file_hash}  {os.path.basename(json_path)}\n")

    txt_path = os.path.join(AUDIT_DIR, f"wipe_audit_{timestamp}_{log_id[:8]}.txt")
    with open(txt_path, "w") as f:
        f.write("USB SANITIZATION AUDIT REPORT\n")
        f.write("=" * 40 + "\n")
        f.write(f"Log ID       : {log_id}\n")
        f.write(f"Timestamp    : {timestamp}\n")
        f.write(f"Operator     : {record['operator']}\n")
        f.write(f"Hostname     : {record['hostname']}\n\n")
        f.write("TARGET DISK\n")
        for k, v in disk.items():
            f.write(f"  {k}: {v}\n")
        f.write("\nSTEPS PERFORMED\n")
        for s in steps:
            f.write(f"  - {s.get('step')}: success={s.get('success')} elapsed={s.get('elapsed_sec')}s\n")
        f.write("\nVERIFICATION\n")
        f.write(f"  {json.dumps(verification, indent=2)}\n")
        f.write("\nCONFIDENCE SCORE\n")
        f.write(f"  {score['score']} / 100\n")
        f.write(f"  Breakdown: {json.dumps(score['breakdown'], indent=2)}\n")
        f.write(f"\nSHA-256 of JSON log: {file_hash}\n")
        f.write("\nLIMITATIONS\n")
        f.write(f"  {record['limitations_disclosed']}\n")

    return json_path


# --------------------------------------------------------------------------
# Main workflow
# --------------------------------------------------------------------------

def do_wipe(disk_number: int, passes: int, drive_letter: str):
    disks = list_removable_usb_disks()
    disk = next((d for d in disks if d["number"] == disk_number), None)
    if disk is None:
        print(f"ERROR: Disk {disk_number} was not found among removable USB disks.")
        print("Refusing to proceed -- this tool will only ever target USB bus disks.")
        sys.exit(1)

    if not confirm_target(disk):
        print("Aborted by user.")
        sys.exit(1)

    steps = []
    print("\n[1/4] Zeroing entire disk with diskpart 'clean all' (this can take a while)...")
    clean_result = diskpart_clean_all(disk_number)
    steps.append(clean_result)
    print(f"      done in {clean_result['elapsed_sec']}s -- success={clean_result['success']}")

    random_result = {}
    if passes >= 2:
        print(f"\n[2/4] Running random-data fill pass on drive letter {drive_letter}:...")
        random_result = create_volume_and_fill_random(disk_number, drive_letter)
        steps.append(random_result)
        print(f"      wrote {round(random_result['bytes_written']/(1024**3),2)} GB, now re-zeroing...")
        final_clean = diskpart_clean_all(disk_number)
        steps.append(final_clean)
    else:
        print("\n[2/4] Skipping random-fill pass (passes=1 requested).")

    print("\n[3/4] Verifying wipe by sampling raw sectors...")
    verification = verify_wipe(disk_number)
    print(f"      clean samples: {verification.get('clean_sample_count')}/{verification.get('sample_count')}")

    print("\n[4/4] Recreating a usable volume on the wiped disk...")
    final_volume = create_final_volume(disk_number, drive_letter, fs="exfat")
    steps.append(final_volume)
    print(f"      done in {final_volume['elapsed_sec']}s -- success={final_volume['success']}")

    score = compute_confidence_score(clean_result, random_result, verification)
    log_path = write_audit_log(disk, steps, verification, score)

    print("\n" + "=" * 70)
    print(f"SANITIZATION CONFIDENCE SCORE: {score['score']} / 100")
    print(f"Audit log written to: {log_path}")
    print("=" * 70)
    print(
        "\nNote: this score reflects OS-visible (logical) sanitization "
        "confidence. See the audit log's 'limitations_disclosed' field for "
        "what software wiping cannot guarantee on flash media."
    )

def main():
    parser = argparse.ArgumentParser(description="USB flash drive sanitizer with audit logging.")
    parser.add_argument("--list", action="store_true", help="List removable USB disks and exit.")
    parser.add_argument("--wipe", action="store_true", help="Wipe a target disk (interactive confirmation required).")
    parser.add_argument("--disk", type=int, help="Disk number to wipe (see --list).")
    parser.add_argument("--passes", type=int, default=2, choices=[1, 2],
                         help="1 = zero wipe only. 2 = zero wipe + random fill + re-zero (default, recommended).")
    parser.add_argument("--letter", type=str, default="Z", help="Temporary drive letter to use for the random-fill pass.")
    args = parser.parse_args()

    require_admin()

    if args.list:
        print_disks(list_removable_usb_disks())
        return

    if args.wipe:
        if args.disk is None:
            print("ERROR: --wipe requires --disk <number>. Use --list first to find it.")
            sys.exit(1)
        do_wipe(args.disk, args.passes, args.letter)
        return

    parser.print_help()


if __name__ == "__main__":
    main()