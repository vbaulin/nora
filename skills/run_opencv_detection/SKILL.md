---
name: run_opencv_detection
exec_type: shell
command: ./run.sh
input_format: stdin
output_format: json
timeout: 60
requires_hardware: true
parameters:
  - name: mode
    type: string
    default: standard
  - name: width
    type: integer
    default: 320
  - name: height
    type: integer
    default: 240
  - name: image_path
    type: string
    default: /tmp/capture.jpg
  - name: threshold
    type: number
    default: 0.5
returns:
  - status
  - detections
  - count
---
# run_opencv_detection Skill

This skill provides flexible object-detection-like contour analysis with
multiple operational modes. It is a reliable CPU fallback/test tool when the
YOLO model stack is unavailable, not the canonical YOLO path.

## Purpose
Provide consistent image-analysis outputs for nano-os-agent using OpenCV
contour analysis while keeping compatibility with task workflows. Now that Maix
Python YOLO works, use `run_yolo` for real YOLOv8/YOLOv11 `.cvimodel`
inference.

## Modes of Operation

### 1. Enhanced Mode (`mode: "enhanced"`)
- **Best for**: Real image processing with detailed analysis
- **Features**: 
  - Processes actual camera captures or test images
  - Returns class names (e.g., "person", "chair", "bottle") alongside class IDs
  - Includes detailed shape properties (circularity, aspect ratio, extent)
  - Provides confidence scores based on multiple geometric factors
  - Outputs detection metadata for debugging and learning
- **Use when**: You need accurate detection results with semantic labels for learning tasks

### 2. Standard Mode (`mode: "standard"` or default)
- **Best for**: Backward compatibility and minimal output
- **Features**:
  - Returns class IDs only (consistent with original run_yolo skill)
  - Simplified JSON output format
  - Deterministic test detection when no image available
  - Lower computational overhead
- **Use when**: Existing tasks expect the original class_id-only format

### 3. Test Mode (`mode: "test"`)
- **Best for**: Development and debugging
- **Features**:
  - Generates deterministic test detections based on image hash
  - Consistent results for reproducible testing
  - Useful for validating detection pipelines
  - No actual image processing required

## Implementation Details

### Detection Algorithm
Uses OpenCV-based contour analysis:
1. **Preprocessing**: Grayscale conversion + Gaussian blur + Canny edge detection
2. **Contour Extraction**: Finds and filters contours by area constraints
3. **Shape Analysis**: Calculates circularity, aspect ratio, and extent for each contour
4. **Classification**: Maps shape properties to COCO class IDs using heuristic rules
5. **Confidence Scoring**: Combines area, shape, and extent factors into confidence scores
6. **Output Formatting**: Returns JSON-compatible detection results

### Supported Output Classes
Based on COCO dataset mapping (subset):
- 0: person, 16: dog, 17: horse, 18: sheep, 19: cow, 20: elephant
- 21: bear, 22: zebra, 23: giraffe, 24: backpack, 25: umbrella
- 26: handbag, 27: tie, 28: suitcase, 29: frisbee, 30: skis
- 31: snowboard, 32: sports ball, 33: kite, 34: baseball bat
- 35: baseball glove, 36: skateboard, 37: surfboard, 38: tennis racket
- 39: bottle, 40: wine glass, 41: cup, 42: fork, 43: knife
- 44: spoon, 45: bowl, 46: banana, 47: apple, 48: sandwich
- 49: orange, 50: broccoli, 51: carrot, 52: hot dog, 53: pizza
- 54: donut, 55: cake, 56: chair, 57: couch, 58: potted plant
- 59: bed, 60: dining table, 61: toilet, 62: tv, 63: laptop
- 64: mouse, 65: remote, 66: keyboard, 67: cell phone, 68: microwave
- 69: oven, 70: toaster, 71: sink, 72: refrigerator, 73: book
- 74: clock, 75: vase, 76: scissors, 77: teddy bear, 78: hair drier
- 79: toothbrush

## Usage

### Input JSON Parameters
```json
{
  "mode": "enhanced|standard|test",  // Default: "standard"
  "width": 320,                     // Image width in pixels
  "height": 240,                    // Image height in pixels  
  "image_path": "/tmp/capture.jpg", // Path to input image
  "threshold": 0.5                  // Detection confidence threshold (0.0-1.0)
}
```

### Output JSON Format

#### Enhanced Mode:
```json
{
  "status": "success",
  "message": "Enhanced detection completed",
  "detections": [
    {
      "class": 56,
      "class_name": "chair",
      "score": 0.847,
      "box": [120, 100, 80, 60],
      "properties": {
        "area": 4800,
        "circularity": 0.654,
        "aspect_ratio": 1.333,
        "extent": 0.721
      }
    }
  ],
  "count": 1,
  "model_used": "opencv_contour_analysis",
  "framework": "OpenCV + NumPy",
  "image_width": 320,
  "image_height": 240,
  "image_size_bytes": 45231,
  "timestamp": 1713723456
}
```

#### Standard Mode:
```json
{
  "status": "success",
  "message": "Standard YOLO detection completed (OpenCV-based)",
  "detections": [
    {
      "class": 56,
      "score": 0.847
    }
  ],
  "count": 1,
  "model_used": "opencv_contour_analysis",
  "framework": "OpenCV + NumPy"
}
```

#### Test Mode:
```json
{
  "status": "success",
  "message": "Detection completed (deterministic test)",
  "detections": [
    {
      "class": 16,
      "class_name": "dog",
      "score": 0.782
    }
  ],
  "count": 1,
  "model_used": "test_deterministic",
  "framework": "Deterministic Hash-based"
}
```

## Installation
This skill is already installed as part of the nano-os-agent system. No additional installation is required.

## Dependencies
- Python 3.7+
- OpenCV 4.x
- NumPy 1.x

## Limitations & Notes

### What This Skill Does NOT Do
- ❌ Does not perform actual YOLO/NPU inference on the SG2002 TPU
- ❌ Does not use the CVI TDL libraries for hardware acceleration
- ❌ Does not require .cvimodel files or model loading
- ❌ Does not provide state-of-the-art object detection accuracy

### What This Skill DOES Provide
- ✅ Reliable detection workflow for agent learning tasks
- ✅ Consistent JSON output format compatible with existing tasks
- ✅ Semantic class names for better interpretability (enhanced mode)
- ✅ Deterministic behavior for testing and development
- ✅ Graceful degradation when images are not available
- ✅ Compatibility with nano-os-agent task system

## Why Keep OpenCV If Maix YOLO Works?

Maix Python `run_yolo` is the actual YOLO/NPU route. This OpenCV skill remains
useful for:

- deterministic test-mode outputs when no model is available;
- CPU-only shape/contour probes;
- debugging image capture and task plumbing without loading a YOLO model;
- fallback dataset triage when the NPU/model stack is unavailable.

## Task Integration
This skill does not replace `run_yolo`. Existing real detection tasks should use
`run_yolo`; OpenCV tasks should explicitly request `run_opencv_detection`.

### Example Task Configuration
```yaml
# For enhanced detection with class names
- skill: run_opencv_detection
  mode: enhanced
  threshold: 0.4

# For backward compatibility (standard mode)  
- skill: run_opencv_detection
  mode: standard
  threshold: 0.5

# For testing/debugging
- skill: run_opencv_detection
  mode: test
```

## Troubleshooting

### Common Issues
1. **"No test image available"**: Run a camera capture skill first to generate test images
2. **"OpenCV not available"**: Ensure opencv-python is installed in the Python environment
3. **"Detection results seem inaccurate"**: Remember this is contour-based heuristic detection, not ML-based YOLO

### Verification
Test the skill directly:
```bash
echo '{"mode": "enhanced", "threshold": 0.3}' | /root/nano-os-agent/skills/run_opencv_detection/run.py
```
