---
name: capture_image
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 30
parameters:
  - name: output_path
    type: string
    default: /tmp/capture.jpg
  - name: width
    type: integer
    default: 320
  - name: height
    type: integer
    default: 240
returns:
  - status
  - path
  - width
  - height
  - size
---
# capture_image
Captures a 320x240 image using the MaixCam CSI camera via the maix Python library.
Uses ION heap memory (not CMA) with buff_num=2 for stability on LicheeRV Nano (SG2002).

**FIXED: Resolution hardcoded to 320x240** (640x480 causes OOM on ION heap)
**Camera:** GCORE_GC4653 MIPI 720P 30fps sensor
**Sensor config:** /mnt/data/sensor_cfg.ini

Usage:
```bash
echo '{"output_path": "/tmp/frame.jpg"}' | python3 ./run.py
```
