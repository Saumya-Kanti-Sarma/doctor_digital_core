#!/usr/bin/env python3

import os
import sys
import ctypes
import hashlib
import random
import string
from pathlib import Path


# ============================================================
# Windows USB / safety helpers
# ============================================================

DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6


def get_drive_type(path):
    """
    Return the Windows drive type.

    2 = removable drive
    3 = fixed/internal drive
    """

    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"

    return ctypes.windll.kernel32.GetDriveTypeW(root)


def is_removable_drive(path):
    """
    Check whether the target is located on a Windows
    removable drive.
    """

    try:
        return get_drive_type(path) == DRIVE_REMOVABLE
    except Exception:
        return False


def is_root_directory(path):
    """
    Prevent someone from accidentally specifying:
        D:\\
        E:\\
        etc.
    """

    path = Path(path).resolve()

    return path.parent == Path(path.anchor)


def is_safe_target(path):
    """
    Strong safety gate.

    The target MUST:
      - exist
      - be a directory
      - be on a removable drive
      - NOT be the root of the drive
    """

    path = Path(path).resolve()

    if not path.exists():
        print(f"ERROR: Directory does not exist:\n{path}")
        return False

    if not path.is_dir():
        print(f"ERROR: Target is not a directory:\n{path}")
        return False

    # Never allow C:, internal HDD/SSD, etc.
    if not is_removable_drive(path):
        print("\nSAFETY BLOCK")
        print("-" * 60)
        print(f"Target: {path}")
        print("This directory is NOT located on a removable USB drive.")
        print("Refusing to sanitize.")
        return False

    # Never allow the entire USB root.
    if is_root_directory(path):
        print("\nSAFETY BLOCK")
        print("-" * 60)
        print("The target is the ROOT of the USB drive.")
        print("Directory sanitizer refuses to operate on an entire drive.")
        return False

    return True


# ============================================================
# Confirmation
# ============================================================

def confirm_target(path):

    path = Path(path).resolve()

    print("\n" + "=" * 70)
    print("!!! DIRECTORY SANITIZATION !!!")
    print("=" * 70)

    print(f"Target directory : {path}")
    print(f"Drive            : {path.drive}")

    print("\nWARNING:")
    print("EVERY FILE INSIDE THIS DIRECTORY WILL BE DESTROYED.")
    print("This operation cannot be undone.")

    print("\nThe sanitizer will:")
    print("  1. Overwrite files")
    print("  2. Flush the data to disk")
    print("  3. Rename files")
    print("  4. Delete the files")
    print("  5. Remove the directory tree")

    print("\n" + "=" * 70)

    typed_path = input(
        "\nType the FULL DIRECTORY PATH to confirm: "
    ).strip().strip('"')

    try:
        typed_path = str(Path(typed_path).resolve())
    except Exception:
        return False

    if typed_path.lower() != str(path).lower():

        print("\nPath mismatch. Aborting.")
        return False

    phrase = input(
        'Type exactly "SANITIZE DIRECTORY" to proceed: '
    ).strip()

    if phrase != "SANITIZE DIRECTORY":

        print("\nConfirmation phrase mismatch. Aborting.")
        return False

    return True


# ============================================================
# Random filename
# ============================================================

def random_name(length=24):

    characters = string.ascii_letters + string.digits

    return "".join(
        random.choice(characters)
        for _ in range(length)
    )


# ============================================================
# File overwrite
# ============================================================

def overwrite_file(path, passes=2):

    """
    Overwrite a file before deleting it.

    Pass 1:
        cryptographically random data

    Pass 2:
        zeros

    NOTE:
    Flash drives use wear leveling, so this cannot guarantee
    physical NAND-cell destruction.
    """

    path = Path(path)

    try:

        size = path.stat().st_size

        if size == 0:
            return {
                "success": True,
                "size": 0,
                "passes": 0
            }

        chunk_size = 1024 * 1024  # 1 MB

        with open(path, "r+b", buffering=0) as f:

            for current_pass in range(passes):

                f.seek(0)

                remaining = size

                while remaining > 0:

                    amount = min(chunk_size, remaining)

                    if current_pass == 0:
                        data = os.urandom(amount)
                    else:
                        data = b"\x00" * amount

                    f.write(data)

                    remaining -= amount

                # Force Python/OS buffers to flush.
                f.flush()
                os.fsync(f.fileno())

        return {
            "success": True,
            "size": size,
            "passes": passes
        }

    except (PermissionError, OSError) as e:

        return {
            "success": False,
            "size": 0,
            "passes": passes,
            "error": str(e)
        }


# ============================================================
# File sanitization
# ============================================================

def sanitize_file(path, passes=2):

    path = Path(path)

    print(f"\nSanitizing:")
    print(f"  {path}")

    result = overwrite_file(path, passes)

    if not result["success"]:

        print(f"  ERROR: {result['error']}")

        return {
            "path": str(path),
            "success": False,
            "error": result["error"]
        }

    # Rename before deletion.
    #
    # This removes the original filename from the filesystem
    # namespace before the file is deleted.
    try:

        new_path = path.with_name(
            "." + random_name() + ".tmp"
        )

        path.rename(new_path)

    except OSError as e:

        print(f"  Rename failed: {e}")

        return {
            "path": str(path),
            "success": False,
            "error": str(e)
        }

    # Delete the overwritten file.
    try:

        new_path.unlink()

    except OSError as e:

        print(f"  Delete failed: {e}")

        return {
            "path": str(path),
            "success": False,
            "error": str(e)
        }

    print("  OK")

    return {
        "path": str(path),
        "success": True,
        "size": result["size"],
        "passes": result["passes"]
    }


# ============================================================
# Directory sanitization
# ============================================================

def sanitize_directory(directory, passes=2):

    directory = Path(directory).resolve()

    # --------------------------------------------------------
    # SAFETY CHECK
    # --------------------------------------------------------

    if not is_safe_target(directory):
        return False

    # --------------------------------------------------------
    # CONFIRMATION
    # --------------------------------------------------------

    if not confirm_target(directory):

        print("\nSanitization cancelled.")
        return False

    print("\nScanning directory...")

    files = []

    for root, dirs, filenames in os.walk(directory):

        for filename in filenames:

            file_path = Path(root) / filename

            files.append(file_path)

    print(f"\nFiles found: {len(files)}")

    if not files:

        print("Directory contains no files.")

    # --------------------------------------------------------
    # SANITIZE FILES
    # --------------------------------------------------------

    results = []

    for file_path in files:

        result = sanitize_file(
            file_path,
            passes=passes
        )

        results.append(result)

    # --------------------------------------------------------
    # REMOVE EMPTY DIRECTORIES
    # --------------------------------------------------------

    print("\nRemoving directory structure...")

    directories = []

    for root, dirs, filenames in os.walk(
        directory,
        topdown=False
    ):

        for dirname in dirs:

            directories.append(
                Path(root) / dirname
            )

    # Delete deepest directories first.
    for folder in directories:

        try:
            folder.rmdir()

        except OSError:
            pass

    # Finally remove requested directory.
    try:

        directory.rmdir()

    except OSError as e:

        print(f"\nWARNING: Could not remove directory:")
        print(f"  {e}")

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    successful = sum(
        1 for result in results
        if result["success"]
    )

    failed = len(results) - successful

    print("\n" + "=" * 70)
    print("DIRECTORY SANITIZATION COMPLETE")
    print("=" * 70)

    print(f"Files found     : {len(files)}")
    print(f"Files sanitized : {successful}")
    print(f"Files failed    : {failed}")
    print(f"Overwrite passes: {passes}")

    if failed == 0:

        print("\nResult: SUCCESS")

    else:

        print("\nResult: PARTIAL FAILURE")
        print("Some files could not be sanitized.")

    print("\nIMPORTANT:")
    print("USB flash storage uses wear-leveling.")
    print("Software overwriting cannot guarantee that every")
    print("physical NAND cell containing old data was erased.")

    print("=" * 70)

    return failed == 0


# ============================================================
# Command line interface
# ============================================================

def main():

    if os.name != "nt":

        print("ERROR: This sanitizer is Windows-only.")
        sys.exit(1)

    if len(sys.argv) < 2:

        print("\nUsage:")
        print(
            '  python dir_sanitization.py "D:\\Private"'
        )
        print(
            '  python dir_sanitization.py "D:\\Private" --passes 2'
        )

        sys.exit(1)

    directory = sys.argv[1]

    passes = 2

    if "--passes" in sys.argv:

        index = sys.argv.index("--passes")

        try:
            passes = int(sys.argv[index + 1])

        except (IndexError, ValueError):

            print("ERROR: --passes must be an integer.")
            sys.exit(1)

    if passes < 1:

        print("ERROR: passes must be >= 1.")
        sys.exit(1)

    success = sanitize_directory(
        directory,
        passes=passes
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()