"""
doctor_digital.usb_recovery
============================
Public function:

    recover(path, files, output_dir="recovered_files")
        Carve deleted files from a USB disk by scanning raw sectors.

Supported file types (pass as strings in the `files` list):
    "jpeg" / "jpg"
    "png"
    "text" / "txt"
"""

import os
import sys

# ------------------------------------------------------------------ signatures

_SIGNATURES = {
    "png": {
        "start": b"\x89PNG\r\n\x1a\n",
        "end": b"\x00\x00\x00\x00IEND\xaeB`\x82",
        "ext": ".png",
        "label": "PNG",
    },
    "jpeg": {
        "start": b"\xff\xd8\xff",
        "end": b"\xff\xd9",
        "ext": ".jpg",
        "label": "JPEG",
    },
    "jpg": {  # alias
        "start": b"\xff\xd8\xff",
        "end": b"\xff\xd9",
        "ext": ".jpg",
        "label": "JPEG",
    },
    "text": {
        # Plain UTF-8 / ASCII text: heuristic — no magic bytes, so we look
        # for runs of printable ASCII (>= 64 consecutive printable bytes).
        "start": None,
        "end": None,
        "ext": ".txt",
        "label": "TEXT",
    },
    "txt": {  # alias
        "start": None,
        "end": None,
        "ext": ".txt",
        "label": "TEXT",
    },
}

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB


# ------------------------------------------------------------------ carvers

def _carve_binary(data: bytes, sig: dict, base_offset: int,
                  output_dir: str, counter: list) -> None:
    """Generic start/end signature carver for binary formats."""
    start_mark = sig["start"]
    end_mark = sig["end"]
    ext = sig["ext"]
    label = sig["label"]
    pos = 0

    while True:
        start = data.find(start_mark, pos)
        if start == -1:
            break
        end = data.find(end_mark, start + len(start_mark))
        if end == -1:
            break
        end += len(end_mark)

        filename = os.path.join(
            output_dir,
            f"recovered_{label.lower()}_{counter[0]:04d}{ext}",
        )
        with open(filename, "wb") as f:
            f.write(data[start:end])

        print(f"[{label}] {filename}  (offset 0x{base_offset + start:X})")
        counter[0] += 1
        pos = end


def _carve_text(data: bytes, base_offset: int,
                output_dir: str, counter: list,
                min_run: int = 64) -> None:
    """
    Heuristic text carver.
    Looks for runs of at least `min_run` consecutive printable ASCII bytes.
    """
    pos = 0
    length = len(data)

    while pos < length:
        # Find start of printable run
        while pos < length and not (0x20 <= data[pos] <= 0x7E or data[pos] in (0x09, 0x0A, 0x0D)):
            pos += 1

        if pos >= length:
            break

        run_start = pos

        # Extend the run
        while pos < length and (0x20 <= data[pos] <= 0x7E or data[pos] in (0x09, 0x0A, 0x0D)):
            pos += 1

        run_end = pos

        if run_end - run_start >= min_run:
            filename = os.path.join(
                output_dir,
                f"recovered_text_{counter[0]:04d}.txt",
            )
            with open(filename, "wb") as f:
                f.write(data[run_start:run_end])

            print(f"[TEXT] {filename}  (offset 0x{base_offset + run_start:X}, "
                  f"{run_end - run_start} bytes)")
            counter[0] += 1


# ------------------------------------------------------------------ public API

def recover(path: dict | int | str, files: list,
            output_dir: str = "recovered_files") -> dict:
    """
    Carve deleted / lost files from a USB disk by reading raw sectors.

    Parameters
    ----------
    path : dict | int | str
        A disk dict returned by ``detect_dir()``, OR an integer disk number,
        OR a raw physical drive path string (e.g. ``"\\\\.\\PhysicalDrive2"``).
    files : list of str
        File types to look for. Supported values: "jpeg", "jpg", "png",
        "text", "txt".
    output_dir : str
        Directory where recovered files will be saved (default
        ``"recovered_files"``).

    Returns
    -------
    dict with keys:
        recovered   dict   { type_label: count, … }
        output_dir  str
    """
    if sys.platform != "win32":
        raise OSError("usb_recovery.recover() is only supported on Windows.")

    # Resolve disk path
    if isinstance(path, dict):
        disk_number = path.get("_number") or path.get("Disk#")
        if disk_number is None:
            raise ValueError("disk dict must contain 'Disk#' or '_number'.")
        physical_path = rf"\\.\PhysicalDrive{disk_number}"
    elif isinstance(path, int):
        physical_path = rf"\\.\PhysicalDrive{path}"
    else:
        physical_path = str(path)

    # Normalise requested types
    requested = []
    for ft in files:
        key = ft.lower()
        if key not in _SIGNATURES:
            print(f"[WARNING] Unknown file type '{ft}' — skipping.")
            continue
        if key not in requested:
            requested.append(key)

    if not requested:
        raise ValueError(f"No supported file types in: {files}. "
                         f"Supported: {list(_SIGNATURES.keys())}")

    os.makedirs(output_dir, exist_ok=True)

    # Per-type counters  { type_key: [int] }
    counters = {k: [1] for k in requested}

    print(f"Opening: {physical_path}")
    print(f"Scanning for: {', '.join(requested)}")
    print(f"Output dir  : {output_dir}\n")

    total_read = 0

    with open(physical_path, "rb", buffering=0) as drive:
        while True:
            try:
                data = drive.read(CHUNK_SIZE)
            except PermissionError:
                print("\nReached end of physical drive.")
                break
            except OSError as e:
                print(f"\nRead error at offset {total_read}: {e}")
                break

            if not data:
                break

            for key in requested:
                sig = _SIGNATURES[key]
                if sig["start"] is not None:
                    _carve_binary(data, sig, total_read, output_dir, counters[key])
                else:
                    _carve_text(data, total_read, output_dir, counters[key])

            total_read += len(data)
            print(f"\rScanned: {total_read / (1024 ** 3):.2f} GB", end="", flush=True)

    print("\n")
    print("Recovery scan complete.")

    recovered = {}
    for key in requested:
        label = _SIGNATURES[key]["label"]
        count = counters[key][0] - 1
        recovered[label] = count
        print(f"  {label} files recovered: {count}")

    print(f"  Output directory: {output_dir}")

    return {"recovered": recovered, "output_dir": output_dir}
