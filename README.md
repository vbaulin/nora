# 🌌 Nano-os-agent — The Universal Hardware Orchestrator for AI Agents
![Nano-os-agent](images/Nano-os-agent.jpg)

**Nora** (Nano-OS-Agent) is a high-fidelity, Go-native hardware orchestration engine designed for the **LicheeRV Nano** (SG2002). It transforms the non-deterministic world of low-level drivers and precompiled SDKs into a deterministic, high-level "Brain-Body" interface for AI Agents.
---


![LicheeRV Nano Hardware Interface](images/LicheeRV%20Nano.jpg)

> [!TIP]
> **Autonomous Hardware Intelligence**: Nono-os-agent converts LicheeRV Nano microcontrollers into fully autonomous agents. Equipped with learned skills, they independently capture high-fidelity imagery, record audio/video, and interact with complex sensor arrays—operating with total autonomy from edge to execution.

## 🚀 The Brain/Body Coordination
One of the most significant improvements in **nano-os-agent** is its ability to bridge the gap between AI reasoning and physical execution. 

*   **Brain (pico Claw)**: Operates in a stochastic world of LLM goals, reasoning, and planning. It decides **WHAT** needs to be done (e.g., "Track the movement of these grapes").
*   **Body (nano-os-agent)**: Operates in the deterministic world of precompiled SDKs and low-level drivers. It decides **HOW** to execute the goal on the hardware without the LLM needing to understand the nuances of the RISC-V C906 or SG2002 SoC.

```text
╔══════════════════════════════════════════════════════════════╗
║  picoClaw Engine (Go) — orchestrates, never touches hardware ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  capture_image ──► vision_capture skill ──► C binary         ║
║  (mode=both)       │  (OpenCV Mobile,    (cap.open(0),      ║
║                     │   MMF/TDL SDK)       cap.release())     ║
║                     │                                       ║
║                     ├──► vision_npu skill ──► C binary       ║
║                     │   (CVI TDL SDK,      (YOLOv8 on NPU,   ║
║                     │    INT8 1TOPS)        → objects[])     ║
║                     │                                       ║
║                     ├──► audio_interaction ──► arecord       ║
║                     │   (ALSA, 48kHz,      (ADC Capture Vol) ║
║                     │    S16_LE)                              ║
║                     │                                       ║
║                     └──► llm_gateway skill ──► shell script  ║
║                          (reads config,       (curl to API, ║
║                           resize+base64        → response)   ║
║                           in Go engine)                     ║
║                                                              ║
║  vision_stream ──► shell script ──► C binary (background)   ║
║  (start/stop/     (PID mgmt)      (MJPEGWriter,             ║
║   status)                          cap.release on SIGINT)    ║
║                                                              ║
║  camera_init ──► shell script ──► sensor_test                ║
║                   (check /proc   (one-time after boot)       ║
║                    /cvitek/vi)                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

### The Improvement: Stochastic goals → Deterministic Drivers
By abstracting driver complexities into **Perception Atoms**, `nano-os-agent` eliminates the friction that typically breaks AI hardware agents. Instead of the LLM guessing how to init a sensor or handle memory buffers, it simply consumes high-fidelity metadata.

---

## 🛠️ Typical Coordination Flow
This diagram illustrates how a user request flows from a high-level intent to deterministic hardware execution:

```text
USER: "What do you see?"
  │
  ▼
PICOCLAW (the brain)
  ├── Receives message from Telegram
  ├── Decides: user wants camera
  ├── Calls MCP tool: capture_image(mode=npu)
  │     │
  │     ▼
  │   nano-os-agent (the body/agent)
  │     ├── Calls vision_capture skill → CSI camera → JPEG
  │     ├── Calls vision_npu skill → YOLO on NPU → objects[]
  │     └── Returns {image_path, objects: [{class: "person", score: 0.87}]}
  │
  ├── Receives result
  ├── Sends image to gemma2-multimodal vision pipeline
  ├── Gets description: "A person is standing near a table"
  ├── Responds to user on Telegram
  └── "I see a person (87% confidence) near a table. Want me to start tracking?"

USER: "Yes, track them and alert me"
  │
  ▼
PICOCLAW
  ├── Creates sub-agent with cron task
  ├── Calls MCP tool: start_stream(port=7777)
  │     ▼
  │   nano-os-agent
  │     └── Starts MJPEG stream on :7777
  │
  └── Every 30s: calls capture_image → run_yolo → if person: notify user
```

---

## ✨ Key Features

*   **Continuous Hardware Monitoring**: Nora actively monitors critical hardware metrics in real-time, including CPU temperature, RAM availability, and camera sensor status.
*   **Research Agenda Execution**: The agent autonomously processes a `research_agenda` to validate your board's specific capabilities (I2C, GPIO, SPI, NPU), marking each hypothesis as confirmed or refuted based on physical evidence.
*   **Perception Atom Engine**: Native Go image analysis for real-time blob tracking and environmental sensing.
*   **Autonomous Evolution (Optional)**: When enabled, the agent can use LLM reasoning to self-improve, autonomously generating new tasks and creating new `SKILL.md` definitions to overcome hardware bottlenecks or learn new capabilities.
*   **Universal Vision Bridge**: Auto-discovers and wraps SDK binaries (YOLO, Detection, Segmentation) into a unified JSON API.
*   **Hardened Execution**: Integrated security policy that blocks dangerous commands (sudo, reboot, direct disk access) while allowing complex hardware probes.
*   **Resource-Aware**: Optimized for the 256MB RAM environment, with child-process memory limits and SD-card wear protection.
*   **Experiment Journal**: Uses a local journal to track which hardware capabilities are confirmed and which are refuted based on atomic metrics.

---

## 📜 The Task Protocol: YAML-Structured Autonomy

At the core of the **pico Claw** ↔ **nano-os-agent** coordination is a modular, YAML-based task protocol. Instead of vague commands, the Brain provides a structured **Research Agenda** via `program.yaml`.

*   **The Handshake**: `program.yaml` acts as the primary task definition. It contains the goals, hypotheses, and specific metrics that the Brain wants **nano-os-agent** to validate.
*   **Modular Architecture**: Every hardware probe, vision task, and experiment is defined in this structured language. This allows for a completely deterministic execution path once the stochastic decision is made by the LLM.
*   **Metric-Driven Results**: `nano-os-agent` parses the YAML, executes the native low-level drivers, and snapshots the metrics before/after the task to return a definitive "Keep" or "Discard" verdict to the Brain.

---

## 🍇 Tracking Grapes: The Cluster Logic
When **pico Claw** asks to track grapes, **nano-os-agent** implements a conversion logic that enhances tracking reliability:

1.  **Detection**: The NPU detects "Grapes" (individual points).
2.  **Conversion**: `nano-os-agent` groups these into "Clusters" (Tracking Atoms) by calculating centroids and area.
3.  **Back-Propagation**: Updates the Brain with the cluster's motion vector (`displacement`).
4.  **Action**: If the "Cluster" moves out of the bounds, **pico Claw** re-plans the camera angle.

---

## Subagent Architecture
pico-claw can spawn and control subagents in three ways:

1. **Subtask Spawning** (task YAML declares subtasks)

```yaml
task:
  id: camera_survey
  name: Survey area with camera
  priority: 1
  status: pending
  subtasks:
    - id: scan_left
      name: Scan left area
      file: tasks/scan_left.yaml      # becomes a new task in queue
    - id: scan_right
      name: Scan right area
      file: tasks/scan_right.yaml
  steps:
    - id: init
      action: call_skill
      parameters: {skill_name: camera_init}
When the parent task completes, scan_left.yaml and scan_right.yaml are copied into tasks/ and become independent tasks the engine picks up.

2. **LLM-Generated Tasks** (agent creates its own subagents)

When idle, pico-claw asks the LLM: "What should I do next?" The LLM generates a complete task YAML with steps, and the engine validates it (security check!) and adds it to the queue. This is how the harware agent becomes autonomous — it writes its own TODO list.

3. **Background Processes** (long-running subagents)

task:
  id: persistent_vision
  name: Run stream + periodic NPU detection
  priority: 1
  steps:
    # Start MJPEG stream (runs in background)
    - id: start_stream
      action: call_skill
      parameters:
        skill_name: vision_stream
        action: start
        port: 7777

    # Periodically capture + detect
    - id: periodic_detect
      action: shell_cmd
      parameters:
        cmd: >
          while true; do
            /root/.picoclaw/workspace/skills/vision_capture/bin/capture /tmp/periodic.jpg 320 320;
            /root/.picoclaw/workspace/skills/vision_npu/bin/yolo_detect /tmp/periodic.jpg /root/models/yolov8n_coco_320.cvimodel 80 0.5 > /tmp/npu_result.json;
            sleep 5;
          done
      timeout: 3600

    # Stop stream when done
    - id: stop_stream
      action: call_skill
      parameters:
        skill_name: vision_stream
        action: stop


---

### What Each One Does (No Overlap)

| Capability | picoClaw | nano-os-agent (main.go)|
| Chat with user via Telegram | ✅ | ❌
| LLM provider management | ✅ | ❌ 
| Smart model routing | ✅ | ❌
| Memory/context | ✅ | ❌
| MCP protocol | ✅ client | ✅ server
| CSI camera capture | ❌ | ✅
| NPU YOLO detection | ❌ | ✅
| MJPEG streaming | ❌ | ✅
| I2C scan / GPIO control | ❌ | ✅
| Task queue + retry | ❌ (different concept) | ✅
| Security (command blocking) | ✅ .security.yml | ✅ 6-layer check
| Autonomous hardware loop | ❌ | ✅
| Visual Truth state | ❌ | ✅
| Android support | ✅ | ❌
| WebUI | ✅ | ❌


### How They Talk: MCP Protocol
picoClaw already supports MCP (Model Context Protocol). Our nano-os-agent should expose its hardware tools as an MCP server. When picoClaw needs to capture an image or run YOLO, it calls our MCP tools.

### What nano-os-agent exposes to picoClaw:
MCP Tools:
  capture_image    → Capture frame from CSI camera (4-phase fallback)
  capture_audio    → Record audio from onboard mic (ALSA)
  capture_video    → Record short video clips (FFMPEG/320x240)
  run_yolo         → Run YOLOv8 detection on NPU (1 TOPS)
  analyze_image    → Advanced perception atom analysis
  scan_i2c         → Scan I2C bus for hardware
  probe_cvitek     → Deep hardware diagnostic probe
  adc_read         → Read high-precision SARADC values
  pwm_control      → Control hardware PWM channels
  time_sync        → Synchronize system clock (NTP or manual)
  get_visual_truth → Return current Visual Truth state

### Concrete Example
User on Telegram: "*What do you see?*"

```text
User → Telegram → picoClaw
  picoClaw thinks: "User wants to know what the camera sees"
  picoClaw calls MCP tool: capture_image()
    nano-os-agent: captures frame via MMF SDK
    nano-os-agent: returns {image_path: "/tmp/capture.jpg", objects: ["person", "chair"]}
  picoClaw calls MCP tool: run_yolo(image_path="/tmp/capture.jpg")
    nano-os-agent: runs YOLO on NPU
    nano-os-agent: returns {objects: [{class:"person", score:0.87, x1:42, y1:234, ...}]}
  picoClaw responds: "I can see a person (87% confidence) sitting at a table."
User ← Telegram ← picoClaw
```

---

## 📦 Build & Installation

### Build for RISC-V (SG2002)

To compile **nano-os-agent** for the LicheeRV Nano, use the Go cross-compilation flags. 

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main.go
```

### Installation
For detailed deployment instructions, library patches, and memory configuration, see [INSTALL.md](./INSTALL.md).

---

## 🛡️ Multimedia Stability (v6.8.0)
The latest version introduces a **Stability-First** multimedia stack designed to overcome the memory constraints of the SG2002 SoC (specifically the 22MB ION carveout).

### 1. Waterfall Capture Fallback
The `capture_image` action now uses a 4-phase waterfall logic to ensure success:
1.  **Standard V4L2**: Uses system drivers.
2.  **FFMPEG**: Robust fallback for kernel-level buffer issues.
3.  **Sensor Test**: Official SDK diagnostic utility.
4.  **Maix-Python Skill**: Specialized Python-based capture using optimized buffer counts (`buff_num=2`).

### 2. Specialized Skills
*   **`capture_audio`**: Native ALSA interaction via `arecord` with auto-volume leveling.
*   **`capture_video`**: Memory-efficient MP4 recording at 320x240 to prevent OOM.

---
*Built with ❤️ for the RISC-V ecosystem.*
