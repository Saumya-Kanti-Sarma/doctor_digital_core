"""
doctor_digital
==============
USB sanitization and recovery toolkit.

Usage
-----
    from doctor_digital import *

    all_dir = detect_dir()

    usb_sanitizer.complete_sanitize(all_dir[1])
    usb_sanitizer.sanitize_dir("/path/of/dir/in/disk")

    usb_recovery.recover(path=all_dir[0], files=["text", "jpeg", "png"])

    tree = read_dir("E:\\")   # recursive folder structure of a drive
"""

from doctor_digital.detect import detect_dir
from doctor_digital.read_dir import read_dir
from doctor_digital import usb_sanitizer
from doctor_digital import usb_recovery

__all__ = ["detect_dir", "read_dir", "usb_sanitizer", "usb_recovery"]
