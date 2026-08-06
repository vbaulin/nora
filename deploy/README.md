# Running nora off the board

The executor is one static Go binary with no CGO, and the research engine is
standard-library Python. Neither needs the LicheeRV Nano. The same tree runs on
a laptop for development and on a cloud VM for experiments whose data arrives
over the network instead of over I2C.

## What changes, and what does not

| | LicheeRV Nano | Laptop | Cloud VM |
|---|---|---|---|
| Task executor | yes | yes | yes |
| Research engine and analyses | yes | yes | yes |
| Domain packs and adapters | yes | yes | yes |
| Camera, NPU/TPU, I2C, GPIO, ADC, audio | yes | no | no |
| Where measurements come from | attached sensors | files you provide | APIs, uploads, a database |

Skills that talk to peripherals declare `requires_hardware: true`. Off-board
they are skipped with a stated reason instead of failing inside a driver:

```text
⏭️  Step observe_scene skipped (1/1): requires board hardware (camera, NPU,
    I2C, GPIO, or audio capture); none present on this host
```

Set `NORA_HARDWARE=1` to force them to run anyway when devices are passed
through, or `NORA_HARDWARE=0` to force the skip on a board.

## Build

The build target is the only thing that changes between hosts:

```bash
# cloud VM, x86_64
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o nora main.go

# cloud VM, ARM (Oracle Cloud Ampere A1, AWS Graviton, Raspberry Pi)
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o nora main.go

# LicheeRV Nano
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main.go

# your own machine, for development
go build -o nora main.go
```

## Layout

The executor finds `skills/` and `tasks/` next to the binary before it looks at
any absolute path, so a self-contained directory is all a host needs:

```text
/opt/nora/
  nora                 # the binary
  program.yaml         # optional; a fallback is used when missing
  skills/              # the skills this host should have
  tasks/               # task YAML
  state/               # research.db and journals
```

Copy only the skills the host can actually use. A cloud VM wants
`research_agent`, `monitor_summary`, `validate_skill`, and whatever domain pack
and adapter you run; it has no use for `capture_image`.

## Systemd

```bash
sudo useradd --system --home /opt/nora --shell /usr/sbin/nologin nora
sudo install -d -o nora -g nora /opt/nora/state /opt/nora/monitors
sudo cp deploy/nora.service /etc/systemd/system/
sudo systemctl enable --now nora
journalctl -u nora -f
```

The unit runs unprivileged with a read-only root, a private `/tmp`, and no new
privileges. It needs no device access, because a host without hardware skills
needs none.

## Container

```bash
podman build -f deploy/Containerfile -t nora:latest .
podman run --rm -v ./state:/opt/nora/state:Z nora:latest
```

The image is Python-based rather than `scratch`: the executor is static, but
the skills it runs are Python scripts, so the runtime needs an interpreter.

## Oracle Cloud (Ampere A1, always-free tier)

1. Create an `Ubuntu 22.04` ARM instance (`VM.Standard.A1.Flex`, 1 OCPU / 6 GB
   is ample; the whole runtime idles well under 100 MB).
2. Build for `linux/arm64` as above and copy the tree to `/opt/nora`.
3. `sudo apt install python3` — the skills need nothing else.
4. Install the systemd unit and enable it.
5. Confirm the engine came up:

   ```bash
   printf '%s' '{"mode":"self_test"}' | /opt/nora/skills/research_agent/run.sh
   ```

Open no inbound ports for the research engine. It reads local evidence and
writes local findings; nothing in this path requires an ingress rule.

## What still assumes the board

- The PicoClaw gateway binary and its Telegram route are deployed separately
  and are RISC-V builds today.
- `native_compile` expects the LicheeRV toolchain at a fixed path.
- `scripts/sync_vineyard_board.sh` deploys to a board over SSH and is not a
  cloud installer.

None of these are needed to run experiments and research their results.
