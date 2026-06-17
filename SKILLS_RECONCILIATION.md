# Skills Reconciliation

Compared on 2026-05-23:

- current active skills: `skills/`
- board copy: `skills-old/`

## Summary

Merged old-only research skills into `skills/` on 2026-05-23, while keeping
the newer active runtime skills.

Most skills that exist in both directories are identical. The important
difference is that `skills-old/` contains several research-era skills that are
useful as evidence, while `skills/` contains newer orchestration, monitoring,
promotion, and Goidanich coordination skills that should not be lost.

The resulting policy is:

1. Keep `skills/` as the active runtime directory.
2. Treat `skills-old/` as a board-research archive.
3. Selectively promote old-only skills after validating their frontmatter,
   paths, executable bits, and current nano-os-agent assumptions.

## Identical Common Skills

The shared skill directories are effectively identical, except `.DS_Store`.
This includes the hardware-critical camera/audio/basic system skills:

- `camera_init`
- `capture_image`
- `capture_video`
- `capture_audio`
- `capture_audio_maix`
- `vision_state_sync`
- `vision_npu`
- `fast_capture`
- `npu-pipeline`
- `npu_info`
- `npu_inspect`
- `tpu_detect`
- `gpio_control`
- `pwm_control`
- `adc_read`
- `hardware_diagnostic`
- `dmesg_watch`
- `system_info`
- `time_sync`

So the copied board skills confirm the current camera path rather than replace
it. The known SG2002 capture approach remains:

- `capture_image`: Maix camera at 320x240 with `buff_num=2`.
- `camera_init`: board-specific sensor initialization wrapper.
- `vision_state_sync`: high-level camera + inference synchronization.

## Present Only In `skills/`

These are newer active-runtime additions and should be preserved:

- `audio_event_detect`
- `monitor_summary`
- `observe_scene`
- `promote_skill`
- `run_yolo`
- `sensor_fusion_snapshot`
- `validate_skill`
- `vineyard_disease_risk`

Why they matter:

- `observe_scene` and `monitor_summary` are the long-running monitoring bridge.
- `validate_skill` and `promote_skill` are the safety gate for learned skills.
- `vineyard_disease_risk` is the Goidanich/federated-learning bridge.
- current `run_yolo` is the canonical Maix Python YOLO path. It supports
  YOLOv8/YOLOv11-style `.cvimodel` files through `model_path` and
  `model_family`, with native CVI/TDL-style binaries only as optional fallback.

## Merged From `skills-old/`

These board-research artifacts were copied into active `skills/`:

- `audio_share_via_picoclaw`
- `continuous_learning_cycle`
- `run_opencv_detection`
- `run_tdl_detection`

Compatibility fixes made during merge:

- added YAML frontmatter to `run_opencv_detection`;
- added YAML frontmatter to `run_tdl_detection`;
- added YAML frontmatter to `continuous_learning_cycle`;
- added `SKILL.md` to `audio_share_via_picoclaw`;
- normalized executable/read permissions;
- changed `run_tdl_detection` to search both current `vision_npu` and legacy
  `vision-npu` paths instead of relying only on hardcoded board paths;
- changed `run_opencv_detection` so deterministic test/fallback mode does not
  require NumPy at import time.

These old disabled directories remain only in `skills-old/`:

- `run_yolo.disabled`
- `run_yolo_cvi.disabled`

Assessment:

- `audio_share_via_picoclaw` is a tiny fallback stub. Useful as a note, not a
  core active skill.
- `continuous_learning_cycle` captures the right idea, but it predates the new
  task `repeat`, `observe_scene`, `monitor_summary`, `validate_skill`, and
  `promote_skill` flow. It should be rewritten as a task/skill chain before
  activation.
- `run_opencv_detection` is a useful CPU fallback design. It is now loadable and
  deterministic `mode=test` runs without importing NumPy at module import time.
- `run_tdl_detection` documents valuable CVI TDL findings, especially that
  SCRFD face detection worked while YOLO paths hit ION/VPSS/OOM limits. But its
  implementation still needs an actual `vision_npu/run_tdl_inference.py` or
  `pipeline_analyze.py` engine on the board. Without that engine it now returns
  a structured error instead of failing silently.
- `run_yolo.disabled` and `run_yolo_cvi.disabled` are explicitly disabled.
  They are research history, not active runtime candidates.

## Recommended Next Steps

Preserve `skills-old/run_tdl_detection/SKILL.md` because it contains important
hardware lessons:

- face detection with `test_img_fd` and
  `scrfd_768_432_int8_1x.cvimodel` was working;
- several old native YOLO sample binaries failed due to ION/VPSS allocation
  pressure;
- Maix Python YOLO is now fixed and should be preferred for YOLOv8/YOLOv11;
- a custom small-resolution TDL path or `CVI_TDL_LoadBinImage` route may be the
  a useful future native fallback, not the primary YOLO route.

Further promote old research into production after these fixes:

1. Add or restore the actual `vision_npu/run_tdl_inference.py` engine if it
   exists on the board.
2. Make old TDL/SCRFD detection a separate skill such as `tdl_face_detect`,
   not a replacement for `run_yolo`.
3. Validate with `validate_skill`, then run a task, then promote.

## Why Not Switch Wholesale

Switching wholesale to `skills-old/` would lose newer active capabilities:

- long-term monitoring summaries;
- environment event fusion;
- learned-skill validation and promotion;
- Goidanich/vineyard federated-learning integration;
- the current hardware-boundary-aware Maix Python `run_yolo` wrapper.

It would also make old-only research skills look active even though at least two
need repair before nano-os-agent can reliably load or run them.

## Decision

`skills-old/` is more relevant as hardware research evidence.

`skills/` is more relevant as the current runtime.

The selective merge is complete. Keep using `skills/`.
