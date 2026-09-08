from doctor_digital import * # usb_sanitizer, usb_recovery

all_dir = detect_dir() # it will return an array of object that will have an dictionary with the follwoing keys Disk# Model                         Serial                  Size (GB)   Status

usb_sanitizer.complete_sanitize(alldir[1]) # complete data sanitization of disk 1
usb_sanitizer.sanitize_dir("/path/of/dir/in/disk")

usb_recovery.recover(
  path= all_dir[0],
  files = ["text","jpeg","png"]
)

