# run_tdl_detection Skill

NPU-accelerated object detection using the CVI TDL SDK on LicheeRV Nano (SG2002).

## Hardware
- **NPU**: SG2002 TPU (CV181x architecture)
- **ION Memory**: 22 MB carveout
- **Camera**: OpenCV capture (software fallback) / MMF CSI (when available)

## Working Modes

| Mode | Executable | Model | Status |
|---|---|---|---|
| `fd` | `test_img_fd` | `scrfd_768_432_int8_1x.cvimodel` | ✅ **Working** |
| `hand_cls` | `test_img_hand_cls` | scrfd model | ⚠️ Partial |

## Usage

```json
{
  "mode": "fd",
  "image_path": "/tmp/capture.jpg",
  "model_path": "/root/cvitek-tdl-sdk-sg200x/cvimodel/scrfd_768_432_int8_1x.cvimodel"
}
```

Or for capture+analyze pipeline:
```json
{
  "mode": "fd",
  "capture": true
}
```

## Known Limitations
- YOLO object detection executables (sample_yolo, eval_yolov8, test_img_od) fail due to **ION OOM** - they try to allocate VPSS buffers at 1920×1080 which exceeds the 22MB ION carveout
- Some executables (eval_yolov8, test_img_fdfr) hit `std::logic_error` due to argument handling
- **Solution**: Need custom compilation with smaller VPSS resolution or use CVI_TDL_LoadBinImage (no VPSS)

## Dependencies
Located at `/root/cvitek-tdl-sdk-sg200x/`:
- `bin/` - Pre-compiled TDL executables
- `lib/` - Shared libraries (libcvi_tdl.so, etc.)
- `cvimodel/` - Model files (.cvimodel)
- LD_LIBRARY_PATH must include middleware/v2/lib and OpenCV paths