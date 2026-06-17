# continuous_learning_cycle Skill

This skill orchestrates the continuous learning cycle for hardware capabilities (picture taking and YOLO analysis) on the LicheeRV Nano.

## Purpose
Automate the continuous learning loop: Capture image → Process with YOLO → Learn from results → Improve → Repeat

## Implementation
Coordinates between:
- Camera capture (maix.camera) 
- YOLO inference (CVI TDL or maix.nn fallback)
- Result logging and analysis
- Adaptive parameter adjustment
- nano-os-agent task generation

## Usage
Input JSON (optional):
```json
{
  "cycle_id": "learning_001",
  "width": 320,
  "height": 240,
  "model_path": "/root/models/yolov8n_coco_320.cvimodel",
  "confidence_threshold": 0.5,
  "max_cycles": 10,
  "learning_objective": "improve_detection_accuracy"
}
```

Output JSON:
```json
{
  "status": "cycle_complete",
  "cycle_id": "learning_001", 
  "cycle_number": 3,
  "total_cycles": 10,
  "learning_progress": {
    "detections_per_cycle": [2, 5, 3],
    "confidence_improvement": 0.15,
    "adjustments_made": ["threshold_lowered", "focus_adjusted"]
  },
  "next_action": "continue_learning" | "objective_met" | "manual_review_needed"
}
```

## Learning Cycle
1. **Capture**: Take picture using maix.camera (320x240 RGB888)
2. **Process**: Run YOLO inference (CVI TDL preferred, maix.nn fallback)
3. **Learn**: Analyze results, adjust parameters, log outcomes
4. **Adapt**: Modify capture settings, confidence thresholds based on learning
5. **Repeat**: Continue until objective met or max cycles reached

## Integration
- Works with nano-os-agent task system
- Generates tasks for vision analysis and diagnostic enhancement
- Logs to `/root/nano-os-agent/learning_log.md` and `/root/nano-os-agent/results.tsv`
- Compatible with existing picoClaw skills for coordination