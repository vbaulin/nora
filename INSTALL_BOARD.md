# 🛠️ Installation on LicheeRV Nano

This guide describes how to deploy **nora** to your LicheeRV Nano board.

## 1. Prerequisites

*   A LicheeRV Nano board (SG2002).
*   Correct library environment. The orchestrator requires several SDK libraries to be present on the board.

## 2. Prepare the Environment

Download and extract the required library patches once on the board:

```bash
# On the board
cd /root
unzip required_libs.zip
```

**IMPORTANT**: Ensure your `LD_LIBRARY_PATH` includes these patched libraries. Add this to your `/etc/profile` or `.bashrc`:

```bash
export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv
```

## 3. Deploy the Binary

Cross-compile the binary on your host machine and transfer it via `scp`:

```bash
# On your host machine
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main_v2.go
scp nora root@<board_ip>:/root/nora
```

## 4. Initialize Hardware

Before running vision tasks, you must initialize the CSI camera sensor. This is usually done via a one-time probe or by running the `sensor_test` utility:

```bash
# On the board
chmod +x /root/nora
/root/nora --init-sensor  # If implemented, or use your manual init script
```

## 5. Usage

Run the agent in orchestrator mode:

```bash
/root/nora
```

The agent will begin scanning `tasks/*.yaml` and executing its research agenda.
