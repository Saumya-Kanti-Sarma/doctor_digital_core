import os
import re
import argparse

SECTOR_SIZE = 512
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB

PNG_START = b"\x89PNG\r\n\x1a\n"
PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"

JPEG_START = b"\xff\xd8\xff"
JPEG_END = b"\xff\xd9"


def carve_png(data, base_offset, output_dir, counter):
    pos = 0

    while True:
        start = data.find(PNG_START, pos)

        if start == -1:
            break

        end = data.find(PNG_END, start + len(PNG_START))

        if end == -1:
            break

        end += len(PNG_END)

        filename = os.path.join(
            output_dir,
            f"recovered_png_{counter[0]:04d}.png"
        )

        with open(filename, "wb") as f:
            f.write(data[start:end])

        print(
            f"[PNG] {filename} "
            f"(offset 0x{base_offset + start:X})"
        )

        counter[0] += 1
        pos = end


def carve_jpeg(data, base_offset, output_dir, counter):
    pos = 0

    while True:
        start = data.find(JPEG_START, pos)

        if start == -1:
            break

        end = data.find(JPEG_END, start + len(JPEG_START))

        if end == -1:
            break

        end += len(JPEG_END)

        filename = os.path.join(
            output_dir,
            f"recovered_jpeg_{counter[0]:04d}.jpg"
        )

        with open(filename, "wb") as f:
            f.write(data[start:end])

        print(
            f"[JPEG] {filename} "
            f"(offset 0x{base_offset + start:X})"
        )

        counter[0] += 1
        pos = end


def recover_drive(drive_number, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    physical_drive = rf"\\.\PhysicalDrive{drive_number}"

    print(f"Opening: {physical_drive}")

    png_counter = [1]
    jpeg_counter = [1]

    total_read = 0

    with open(physical_drive, "rb", buffering=0) as drive:

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


            carve_png(
                data,
                total_read,
                output_dir,
                png_counter
            )

            carve_jpeg(
                data,
                total_read,
                output_dir,
                jpeg_counter
            )

            total_read += len(data)

            print(
                f"\rScanned: {total_read / (1024**3):.2f} GB",
                end="",
                flush=True
            )

    print("\n")
    print("Recovery scan complete.")
    print(f"PNG files recovered : {png_counter[0] - 1}")
    print(f"JPEG files recovered: {jpeg_counter[0] - 1}")
    print(f"Output directory    : {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Simple raw PNG/JPEG file carver"
    )

    parser.add_argument(
        "--disk",
        type=int,
        required=True,
        help="Physical disk number"
    )

    parser.add_argument(
        "--output",
        default="recovered_files",
        help="Output directory"
    )

    args = parser.parse_args()

    if os.name != "nt":
        print("This program currently supports Windows only.")
        return

    recover_drive(
        args.disk,
        args.output
    )


if __name__ == "__main__":
    main()