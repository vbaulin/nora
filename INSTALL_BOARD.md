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

## 5. Provision Vineyard Guard on an Existing SD Card

This step is required only when the board will run the Vineyard Guard
application. It configures a mounted Linux root filesystem; it does not format
the card or modify the boot partition.

1. Copy and edit the manifest:

   ```bash
   cp config/vineyard-board.example.json /tmp/my-board.json
   ```

2. Set a unique physical `board.id`. For every field, set a unique `field.id`,
   GPS coordinates, variety, and either planting year or vine age. Also record
   management, water regime, weather station when known, black-rot inoculum
   evidence, phenology, and sensor availability.

3. Validate and preview without writing:

   ```bash
   python3 scripts/provision_vineyard_sd.py \
     --manifest /tmp/my-board.json \
     --rootfs /Volumes/rootfs \
     --dry-run
   ```

4. Resolve the official SIGPAC recinto and write the configuration:

   ```bash
   python3 scripts/provision_vineyard_sd.py \
     --manifest /tmp/my-board.json \
     --rootfs /Volumes/rootfs \
     --fetch-sigpac \
     --require-sigpac
   ```

On Linux, replace `/Volumes/rootfs` with the rootfs mount point. On a running
board, use `--rootfs /`. If `agent_config.yaml` already exists, inspect it and
then add `--force`; the script creates a timestamped backup.

The following files are written:

```text
/root/.picoclaw/workspace/goidanich/agent_config.yaml
/root/.picoclaw/workspace/goidanich/board_manifest.json
/root/.picoclaw/board_inventory.json
```

Secrets are deliberately excluded. Copy the Goidanich `.env` and PicoClaw
`telegram.env` separately with mode `0600`. Use a Supabase publishable/anon key
on the board, never a service-role key.

See
[docs/vineyard-sd-card-provisioning.md](docs/vineyard-sd-card-provisioning.md)
for SIGPAC ambiguity handling, metadata definitions, and verification.

## 6. Initialize Hardware

Before running vision tasks, you must initialize the CSI camera sensor. This is usually done via a one-time probe or by running the `sensor_test` utility:

```bash
# On the board
chmod +x /root/nano-os-agent
/root/nano-os-agent --init-sensor  # If implemented
```

## 7. Usage

Run the agent in orchestrator mode:

```bash
/root/nano-os-agent
```

The agent will begin scanning `tasks/*.yaml` and executing its research agenda.
