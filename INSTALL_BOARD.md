# 🛠️ Installation on LicheeRV Nano

This guide describes how to deploy **nano-os-agent** to your LicheeRV Nano board.

## 1. Prerequisites

*   A LicheeRV Nano board (SG2002).
*   Correct library environment. The orchestrator requires several libraries to be present on the board.

## 2. Prepare the Environment

Download and extract the required library patches from [drive](https://drive.google.com/file/d/1nhWBeKPAJ9O-7zXrXu0uMwNdArOiBBLm/view?usp=drive_link) as explained in [this manual](https://habr.com/ru/articles/880230/) once on the board to root/:

```bash
# On the board
cd /root
unzip required_libs.zip
```

**IMPORTANT**: Ensure your `LD_LIBRARY_PATH` includes these patched libraries. Add this to your `/etc/profile` or `.bashrc`:

```bash
export LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch/tpu_sdk_libs:/root/libs_patch:/root/libs_patch/opencv
```

Forked version of OpenCV-mobile can be found [here]
(https://drive.google.com/file/d/1dW5j6Z-oTjgFVn3bI_piCI6ORJamrKq9/view).
Add this folder to root/

**Note on /mnt/data**: Some board images store proprietary sensor configurations (e.g., `sensor_cfg.ini`) and factory binaries in `/mnt/data/`. The **nano-os-agent** is designed to automatically detect and utilize these assets if present.

This ensures the correct and compatible versions of libraries (OpenCV Mobile, TDL SDK and others) are available for the nano-os-agent.

## 3. Essential: Configure CMA Memory

The LicheeRV Nano (SG2002) requires reserved **Contiguous Memory Allocator (CMA)** space for the CSI camera and NPU to function. If `CmaTotal` is 0, vision tasks will fail with `vb_ioctl_init NG`.

1.  Check your current CMA: `cat /proc/meminfo | grep Cma`
2.  If it is 0, add `cma=64M` (or `cma=128M`) to your kernel boot arguments.
3.  On most images, edit `/boot/extlinux/extlinux.conf`:
    ```text
    append root=/dev/mmcblk0p2 ... cma=64M
    ```
4.  Reboot the board.

## 4. Deploy the Binary

Cross-compile the binary on your host machine and transfer it via `scp`:

```bash
# On your host machine
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-os-agent main.go
scp nano-os-agent root@<board_ip>:/root/nano-os-agent
```

Because we are using CGO_ENABLED=0, the Go compiler statically links the yaml.v3 library directly into the nano-os-agent binary. The board does not need to have Go or any YAML libraries installed

## 4. Initialize Hardware

Before running vision tasks, you must initialize the CSI camera sensor. This is usually done via a one-time probe or by running the `sensor_test` utility:

```bash
# On the board
chmod +x /root/nano-os-agent
/root/nano-os-agent --init-sensor  # If implemented
```

## 6. Usage

Run the agent in orchestrator mode:

```bash
/root/nano-os-agent
```

The agent will begin scanning `tasks/*.yaml` and executing its research agenda.
