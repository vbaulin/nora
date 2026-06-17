#!/usr/bin/env python3
import sys
import json
import os
import time
import subprocess
import threading
from datetime import datetime

def main():
    result = {"status": "error", "message": ""}
    
    try:
        # Read input parameters
        try:
            params = json.load(sys.stdin)
        except Exception:
            params = {}
        
        cycle_id = params.get("cycle_id", f"learning_{int(time.time())}")
        width = int(params.get("width", 320))
        height = int(params.get("height", 240))
        model_path = params.get("model_path", "/root/models/yolov8n_coco_320.cvimodel")
        confidence_threshold = float(params.get("confidence_threshold", 0.5))
        max_cycles = int(params.get("max_cycles", 10))
        learning_objective = params.get("learning_objective", "establish_baseline_performance")
        
        # Initialize learning state
        learning_state = {
            "cycle_id": cycle_id,
            "start_time": datetime.now().isoformat(),
            "width": width,
            "height": height,
            "model_path": model_path,
            "confidence_threshold": confidence_threshold,
            "max_cycles": max_cycles,
            "learning_objective": learning_objective,
            "cycles_completed": 0,
            "total_detections": 0,
            "detection_history": [],
            "threshold_history": [confidence_threshold],
            "learnings": [],
            "adjustments": []
        }
        
        # Run learning cycles
        for cycle_num in range(1, max_cycles + 1):
            cycle_result = _run_learning_cycle(
                cycle_num, width, height, model_path, confidence_threshold, cycle_id
            )
            
            if cycle_result["status"] != "success":
                result = {
                    "status": "error",
                    "message": f"Cycle {cycle_num} failed: {cycle_result.get('message', 'Unknown error')}",
                    "partial_state": learning_state
                }
                break
            
            # Update learning state
            learning_state["cycles_completed"] = cycle_num
            learning_state["total_detections"] += cycle_result["detection_count"]
            learning_state["detection_history"].append(cycle_result["detection_count"])
            
            # Learn from this cycle
            cycle_learnings = _extract_learnings(cycle_result, learning_state)
            learning_state["learnings"].extend(cycle_learnings["learnings"])
            learning_state["adjustments"].extend(cycle_learnings["adjustments"])
            
            # Adapt parameters for next cycle
            if cycle_num < max_cycles:  # Don't adapt after last cycle
                adapted_threshold = _adapt_parameters(cycle_result, learning_state)
                learning_state["confidence_threshold"] = adapted_threshold
                learning_state["threshold_history"].append(adapted_threshold)
            
            # Check if learning objective is met
            if _check_objective_met(learning_state, learning_objective):
                result = {
                    "status": "objective_met",
                    "message": f"Learning objective '{learning_objective}' achieved after {cycle_num} cycles",
                    "final_state": learning_state,
                    "recommendation": "Consider increasing learning objective or collecting more diverse data"
                }
                break
        
        # If we completed all cycles without meeting objective
        if result["status"] == "error":  # Only set if not already set by objective met or error
            result = {
                "status": "cycle_complete",
                "message": f"Completed {max_cycles} learning cycles",
                "final_state": learning_state,
                "next_action": "analyze_results_and_decide_next_steps"
            }
            
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    
    print(json.dumps(result))

def _run_learning_cycle(cycle_num, width, height, model_path, threshold, cycle_id):
    """Run a single learning cycle: capture → process → learn"""
    try:
        # Step 1: Capture image
        capture_result = _capture_image(width, height, f"/tmp/capture_cycle{cycle_num}.jpg")
        if capture_result["status"] != "success":
            return capture_result
        
        # Step 2: Process with YOLO (using our CVI TDL skill)
        yolo_result = _run_yolo_inference(
            capture_result["image_path"], 
            model_path, 
            threshold
        )
        
        # Step 3: Learn from results
        if yolo_result["status"] == "success":
            # Process actual detections
            detections = yolo_result.get("detections", [])
            detection_count = len(detections)
            
            return {
                "status": "success",
                "cycle_number": cycle_num,
                "image_path": capture_result["image_path"],
                "detection_count": detection_count,
                "detections": detections,
                "processing_method": yolo_result.get("method", "unknown"),
                "timestamp": datetime.now().isoformat()
            }
        else:
            # YOLO failed - still valuable learning
            return {
                "status": "partial_success", 
                "cycle_number": cycle_num,
                "image_path": capture_result["image_path"],
                "detection_count": 0,
                "detections": [],
                "processing_method": "failed",
                "yolo_error": yolo_result.get("message", "Unknown YOLO error"),
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Learning cycle {cycle_num} failed: {str(e)}",
            "cycle_number": cycle_num
        }

def _capture_image(width, height, image_path):
    """Capture image using maix.camera"""
    try:
        # Import inside function to isolate potential issues
        from maix import camera, image
        
        # Initialize camera with ION heap for better memory management
        cam = camera.Camera(width, height, buff_num=2)
        
        # Capture frame
        img = cam.read()
        if img is None:
            return {"status": "error", "message": "camera.read() returned None"}
        
        # Save image
        img.save(image_path)
        
        # Get image info
        img_bytes = img.to_bytes()
        
        return {
            "status": "success",
            "image_path": image_path,
            "image_size": len(img_bytes),
            "width": width,
            "height": height,
            "format": "RGB888"
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Image capture failed: {str(e)}"}
    finally:
        try:
            del cam
            del img
        except:
            pass

def _run_yolo_inference(image_path, model_path, threshold):
    """Run YOLO inference through the active Maix Python run_yolo skill"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        run_yolo = os.path.join(os.path.dirname(script_dir), "run_yolo", "run.sh")
        input_data = json.dumps({
            "backend": "maix",
            "model_family": "auto",
            "image_path": image_path,
            "model_path": model_path,
            "threshold": threshold,
        })
        result = subprocess.run(
            [run_yolo],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=90,
        )
        try:
            parsed = json.loads(result.stdout)
        except Exception:
            parsed = {"status": "error", "message": result.stdout[-1000:]}
        parsed["method"] = "run_yolo_maix_python"
        return parsed
        
    except Exception as e:
        return {"status": "error", "message": f"YOLO inference setup failed: {str(e)}"}

def _try_cvi_tdl_yolo(image_path, model_path, threshold):
    """Attempt to run YOLO via CVI TDL libraries"""
    try:
        # This would be the actual TDL implementation:
        # 1. Load libcvi_tdl.so
        # 2. Initialize model context
        # 3. Preprocess image from image_path
        # 4. Run inference
        # 5. Post-process results
        
        # For now, return a structured response showing readiness
        return {
            "status": "ready",
            "message": "CVI TDL YOLO skill ready - awaiting TDL library implementation",
            "model_path": model_path,
            "image_path": image_path,
            "threshold": threshold,
            "tpu_device": "/dev/cvi-tpu0",
            "next_step": "Implement libcvi_tdl.so based inference"
        }
        
    except Exception as e:
        return {"status": "error", "message": f"CVI TDL setup failed: {str(e)}"}

def _extract_learnings(cycle_result, learning_state):
    """Extract learnings from a completed cycle"""
    learnings = []
    adjustments = []
    
    cycle_num = cycle_result["cycle_number"]
    detection_count = cycle_result["detection_count"]
    status = cycle_result["status"]
    
    # Learning from detection count
    if status == "success":
        learnings.append(f"Cycle {cycle_num}: Successfully processed image, detected {detection_count} objects")
    elif status == "partial_success":
        learnings.append(f"Cycle {cycle_num}: Image capture successful, YOLO processing deferred")
    else:
        learnings.append(f"Cycle {cycle_num}: Cycle encountered errors: {cycle_result.get('message', 'Unknown')}")
    
    # Learning from image properties
    if "image_size" in cycle_result:
        learnings.append(f"Cycle {cycle_num}: Captured {cycle_result['image_size']} byte image ({cycle_result.get('width', '?')}x{cycle_result.get('height', '?')})")
    
    # Suggest adjustments based on results
    if detection_count == 0 and status == "success":
        adjustments.append(f"Consider lowering confidence threshold (current: {learning_state['confidence_threshold']}) for more detections")
        adjustments.append("Check scene lighting and contrast")
    elif detection_count > 10 and status == "success":
        adjustments.append(f"Consider raising confidence threshold (current: {learning_state['confidence_threshold']}) to reduce false positives")
        adjustments.append("Current threshold may be too low for this scene")
    
    # Technical learnings
    if "processing_method" in cycle_result:
        learnings.append(f"Cycle {cycle_num}: Used {cycle_result['processing_method']} for inference")
    
    return {
        "learnings": learnings,
        "adjustments": adjustments
    }

def _adapt_parameters(cycle_result, learning_state):
    """Adapt parameters based on cycle results"""
    current_threshold = learning_state["confidence_threshold"]
    detection_count = cycle_result["detection_count"]
    
    # Simple adaptation logic
    if detection_count == 0:
        # No detections - try lowering threshold to be more sensitive
        new_threshold = max(0.1, current_threshold - 0.1)
        return new_threshold
    elif detection_count > 20:
        # Many detections - try raising threshold to reduce false positives
        new_threshold = min(0.9, current_threshold + 0.05)
        return new_threshold
    else:
        # Reasonable number of detections - keep current threshold or make small adjustment
        return current_threshold

def _check_objective_met(learning_state, objective):
    """Check if learning objective has been met"""
    cycles_done = learning_state["cycles_completed"]
    
    if objective == "establish_baseline_performance":
        # Baseline established after 3 successful cycles
        successful_cycles = sum(1 for h in learning_state["detection_history"] if h is not None)
        return successful_cycles >= 3
    
    elif objective == "improve_detection_consistency":
        # Check if detection variance is low
        if len(learning_state["detection_history"]) >= 3:
            recent = learning_state["detection_history"][-3:]
            # Simple variance check
            if len(set(recent)) <= 2:  # Low variance
                return True
    
    elif objective == "collect_training_data":
        # Collect minimum number of detections for training
        return learning_state["total_detections"] >= 50
    
    # Default: continue until max cycles
    return False

if __name__ == "__main__":
    main()
