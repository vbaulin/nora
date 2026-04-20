# 🚀 Installation Guide - nora (Nano-OS Agent)

This guide covers the deployment of the **nora** orchestrator to the LicheeRV Nano (SG2002).

## 1. Quick Start (Cross-Compilation)
On your development machine (Linux/macOS), run:

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main.go
```

Then transfer the binary and the `skills/` and `tasks/` directories to the board:

```bash
scp nora root@<board_ip>:/root/
scp -r skills tasks root@<board_ip>:/root/
```

## 2. Hardware Prerequisites (The "Stability" Patch)

### 2.1 CMA Memory Reservation
The most common cause of camera/NPU failure is a missing memory carveout.
1. Check if CMA is enabled: `cat /proc/meminfo | grep Cma`
2. If `CmaTotal` is 0, edit `/boot/extlinux/extlinux.conf` (or your board's boot config) and append `cma=64M` to the kernel arguments.
3. **Reboot** the board.

### 2.2 Library Dependencies
Ensure the board has the required Cvitek/Sophgo libraries in its search path. 
Add these to your `~/.bashrc`:
```bash
export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv
```

## 3. Running the Agent
Once deployed, simply run the binary:

```bash
cd /root
./nora
```

### Optional Flags
- `--sub-agent`: Runs in task-execution mode (used by the orchestrator internally).
- `--task <file>`: Specifies a single task file to execute.

## 4. Multimedia Calibration
- **Camera**: If capture fails, ensure `/mnt/data/sensor_cfg.ini` is present (it defines the MIPI lane configuration).
- **Audio**: Nora uses `amixer` and `arecord`. Ensure the ALSA utilities are installed (`apt install alsa-utils`).

---
See [INSTALL_BOARD.md](./INSTALL_BOARD.md) for deeper technical details on SDK patching and CGO builds.
