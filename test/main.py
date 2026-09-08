from doctor_digital import *  # usb_sanitizer, usb_recovery

all_dir = detect_dir()  # returns a list of dicts with keys:
                        # Disk#, Model, Serial, Size (GB), Status

print(all_dir)
# usb_sanitizer.complete_sanitize(all_dir[1])   # complete data sanitization of disk 1
# usb_sanitizer.sanitize_dir("/path/of/dir/in/disk")

# usb_recovery.recover(
#     path=all_dir[0],
#     files=["text", "jpeg", "png"]
# )
