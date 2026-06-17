# run_opencv_detection Skill

This skill provides flexible object detection using OpenCV-based contour analysis with multiple operational modes. It serves as a reliable fallback when actual NPU/TPU inference is not available due to missing build tools or SDK limitations.

## Purpose
Provide consistent object detection capabilities for the nano-os-agent system using OpenCV contour analysis, eliminating dependency on fragile maix.nn implementations while maintaining compatibility with existing task workflows.

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

## Why OpenCV Instead of Actual YOLO?

### Missing Build Tools for TDL SDK
To build and use the actual CVI TDL SDK for SG2002 NPU acceleration, the following are **missing**:

1. **RISC-V Cross-Compilation Toolchain**: Complete gcc/g++ toolchain for riscv64-linux-gnu
2. **Build Systems**: make, cmake, ninja (not installed in base system)
3. **Python Development Headers**: Python.h and development libraries for building Python extensions
4. **Required Dependencies**: Various libraries that the TDL SDK depends on for compilation
5. **Complete SDK Source**: While source exists, it requires proper toolchain to build

### Current Workaround
This OpenCV-based detection skill provides:
- Functional detection capabilities for agent learning and testing
- Compatibility with existing task expectations
- A stable foundation while proper TDL SDK toolchain is being established
- Clear delineation between actual NPU inference (when available) and fallback detection

## Task Integration
This skill replaces both `run_yolo` and `run_yolo_cvi` skills. Existing tasks should be updated to reference `run_opencv_detection` with appropriate mode parameters.

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