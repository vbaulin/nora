# 🌌 nora — The Universal Hardware Orchestrator for AI Agents

**nora** (Nano-OS Research Agent) is a high-fidelity, Go-native hardware orchestration engine designed for the **LicheeRV Nano** (SG2002). It transforms the non-deterministic world of low-level drivers and precompiled SDKs into a deterministic, high-level "Brain-Body" interface for AI Agents.

---

## 🚀 The Brain/Body Coordination
One of the most significant improvements in **nora** is its ability to bridge the gap between AI reasoning and physical execution. 

*   **Brain (pico Claw)**: Operates in a stochastic world of LLM goals, reasoning, and planning. It decides **WHAT** needs to be done (e.g., "Track the movement of these grapes").
*   **Body (nora Agent)**: Operates in the deterministic world of precompiled SDKs and low-level drivers. It decides **HOW** to execute the goal on the hardware without the LLM needing to understand the nuances of the RISC-V C906 or SG2002 SoC.

### The Improvement: Stochastic goals → Deterministic Drivers
By abstracting driver complexities into **Perception Atoms**, `nora` eliminates the friction that typically breaks AI hardware agents. Instead of the LLM guessing how to init a sensor or handle memory buffers, it simply consumes high-fidelity metadata.

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
  │   nora (the body/agent)
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
  │   nora
  │     └── Starts MJPEG stream on :7777
  │
  └── Every 30s: calls capture_image → run_yolo → if person: notify user
```

---

## ✨ Key Features

*   **Universal Vision Bridge**: Auto-discovers and wraps SDK binaries (YOLO, Detection, Segmentation) into a unified JSON API.
*   **Perception Atom Engine**: Native Go image analysis for real-time blob tracking and environmental sensing.
*   **Self-Improving Agenda**: Executes a `program.yaml` research agenda (provided by **pico Claw**) to catalog board capabilities (I2C, GPIO, SPI, NPU) autonomously.
*   **Hardened Execution**: Integrated security policy that blocks dangerous commands (sudo, reboot, direct disk access) while allowing complex hardware probes.
*   **Resource-Aware**: Optimized for the 256MB RAM environment, with child-process memory limits and SD-card wear protection.
*   **Experiment Journal**: Uses a local journal to track which hardware capabilities are confirmed and which are refuted based on atomic metrics.

---

## 📜 The Task Protocol: YAML-Structured Autonomy

At the core of the **pico Claw** ↔ **nora** coordination is a modular, YAML-based task protocol. Instead of vague commands, the Brain provides a structured **Research Agenda** via `program.yaml`.

*   **The Handshake**: `program.yaml` acts as the primary task definition. It contains the goals, hypotheses, and specific metrics that the Brain wants **nora** to validate.
*   **Modular Architecture**: Every hardware probe, vision task, and experiment is defined in this structured language. This allows for a completely deterministic execution path once the stochastic decision is made by the LLM.
*   **Metric-Driven Results**: `nora` parses the YAML, executes the native low-level drivers, and snapshots the metrics before/after the task to return a definitive "Keep" or "Discard" verdict to the Brain.

---

## 🍇 Tracking Grapes: The Cluster Logic
When **pico Claw** asks to track grapes, **nora** implements a conversion logic that enhances tracking reliability:

1.  **Detection**: The NPU detects "Grapes" (individual points).
2.  **Conversion**: `nora` groups these into "Clusters" (Tracking Atoms) by calculating centroids and area.
3.  **Back-Propagation**: Updates the Brain with the cluster's motion vector (`displacement`).
4.  **Action**: If the "Cluster" moves out of the bounds, **pico Claw** re-plans the camera angle.

---

## 📦 Build & Installation

### Build for RISC-V (SG2002)

To compile **nora** for the LicheeRV Nano from any host (MacOS or Linux), use the Go cross-compilation flags. 

**Standard Cross-Compile:**
```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main_v2.go
```

**With Cross-Compiler (if CGO is required):**
If you need to link against native C libraries, use the `musl` cross-compiler:
```bash
CC=riscv64-unknown-linux-musl-gcc \
CXX=riscv64-unknown-linux-musl-g++ \
GOOS=linux GOARCH=riscv64 CGO_ENABLED=1 \
go build -o nora main_v2.go
```

### Installation
See [INSTALL_BOARD.md](./INSTALL_BOARD.md) for detailed instructions on patching the board SDKs and deploying the binary.

---
*Built with ❤️ for the RISC-V ecosystem.*
