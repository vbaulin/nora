# 🌌 nora — Universal Hardware Orchestrator for LicheeRV Nano

**nora** (Nano-OS Research Agent) is a powerful, Go-native hardware orchestration engine designed for the **LicheeRV Nano** (SG2002) nanoboard equipped with Neuro Processing Unit (NPU) and running picoClaw for AI agent framework. It transforms low-level hardware interactions into a high-level, deterministic "Brain-Body" interface for AI Agents.  

## 🚀 The Vision: "Brain-Body" Split

Traditional hardware agents often suffer from latency and complexity when the LLM has to manage raw driver calls. **nora** solves this by establishing a clear boundary:

*   **Brain (LLM Gateway)**: Reason, plan, and decide.
*   **Body (nora Agent)**: High-performance hardware execution and "Perception Atom" generation.

Instead of raw JSON detections, **nora** provides the Brain with processed **Perception Atoms**—rich metadata containing centroids, area, perimeter, light intensity, and color decomposition.

## ✨ Key Features

*   **Universal Vision Bridge**: Auto-discovers and wraps SDK binaries (YOLO, Detection, Segmentation) into a unified JSON API.
*   **Perception Atom Engine**: Native Go image analysis for real-time blob tracking and environmental sensing.
*   **Self-Improving Agenda**: Executes a `program.yaml` research agenda to catalog board capabilities (I2C, GPIO, SPI, NPU) autonomously.
*   **Hardened Execution**: Integrated security policy that blocks dangerous commands (sudo, reboot, direct disk access) while allowing complex hardware probes.
*   **Resource-Aware**: Optimized for the 256MB RAM environment, with child-process memory limits and SD-card wear protection.

## 🛠️ Perception Atom API

Every vision task returns a list of `atoms`. Example:

```json
{
  "atoms": [
    {
      "id": 1,
      "class": "grapes",
      "confidence": 0.95,
      "centroid": {"x": 0.45, "y": 0.62},
      "area": 0.12,
      "intensity": 142.5,
      "color": {
        "rgb": {"r": 120, "g": 90, "b": 150},
        "hsv": {"h": 270, "s": 0.4, "v": 0.59}
      },
      "displacement": {"dx": 0.05, "dy": -0.02}
    }
  ]
}
```

## 📦 Installation

See [INSTALL_BOARD.md](./INSTALL_BOARD.md) for detailed instructions on deploying to the LicheeRV Nano.

```bash
# Quick Build for RISC-V
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main_v2.go
```

## 📜 Research Agenda

nora follows a `program.yaml` that defines its current goals and hypotheses. It uses an **Experiment Journal** to track which hardware capabilities are confirmed and which are refuted.

---
*Built with ❤️ for the RISC-V ecosystem.*
