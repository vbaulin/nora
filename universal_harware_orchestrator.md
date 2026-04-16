I have implemented the **Universal Research Engine**. This is the "Brain-Body" interface that allows us to run a loop for hours without needing to recompile.

### 🚀 The Architecture: "Compile Once, Run Forever"

Instead of writing new code for every hypothesis, we now have a **Dispatcher**.

**The Logic Flow:**

1. **Configuration:** I generate a `config.json` (or YAML) that describes the experiment.
2. **Execution:** The `nano-research-engine` (the Go binary) reads this file, maps the `action` to a pre-compiled "Capability," and executes it.
3. **Reporting:** It saves the results to `result.json`.

#### 🛠️ What I have created in the workspace:

1. **`/root/.picoclaw/workspace/research/engine/main.go`**: This is the source for the Universal Engine. It contains a modular `switch` system. I have already implemented two base capabilities:
    - `measure_performance`: A CPU stress/latency test.
    - `check_hardware`: A probe to check for `/dev/video0`, `/dev/mmf`, etc.
2. **`/root/.picoclaw/workspace/research/configs/baseline.json`**: The first experiment definition.

---

### 📦 How to Deploy This

Since you are handling the compilation, here is the workflow:

**1. Compile the Engine (Your Machine):** Compile the Go code into a static binary for the SG2002:

```bash
# Example command (adjust for your Go environment)
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-research-engine /root/.picoclaw/workspace/research/engine/main.go
```

**2. Push to Board:** Put the binary and the config file on the board:

```bash
scp nano-research-engine root@<ip>:/root/
scp /root/.picoclaw/workspace/research/configs/baseline.json root@<ip>:/root/config.json
```

**3. Run the Loop:** Run the engine:

```bash
./nano-research-engine
```

---

### 🔄 How the Autonomous Loop Works Now

Now that the engine is on the board, the **"No-Human" loop** looks like this:

1. **Gemma 4 (Me):** I analyze the `result.json` from the previous run.
2. **Gemma 4 (Me):** I decide to change a parameter (e.g., "Increase CPU iterations to 10,000,000 to test thermal throttling").
3. **Deployment:** I provide you with a new `config.json`.
4. **Execution:** You push the JSON and run the binary.
5. **Observation:** I read the new `result.json` and refine the hypothesis.

**This is a universal loop.** If we want to add NPU testing, I will simply add a `runNPUinference()` function to the Go source, you recompile **one last time**, and then we can iterate on NPU parameters for weeks without ever touching the compiler again.

**Do you want to try this "Baseline" run now to verify the engine works?** 🦞

This is a massive expansion of the scope. We are moving from a "Hardware Probe" to a Full-Stack Autonomous Research Station.

To achieve this without making the binary too bloated or unstable, we need to evolve the **nano-research-engine** from a simple "Dispatcher" into a "System Agent."

🏗️ The Evolved Architecture: "Nano-OS Agent"

Since you want the agent to:

1. Handle Files: Find, read, and upload images/logs to the LLM.
2. Execute Python: Run dynamic scripts for data processing.
3. Web Presence: Deploy sites via here.now to showcase results.
4. Internet Access: Use skills to fetch documentation or search.

We will split this into two components:

Component A: The Go Engine (The "Kernel")

The Go binary remains the "Kernel" because it is fast and static. I will add three new "Super-Capabilities" to it:

- file_manager: Can scan directories, find the largest images, and read binary data to send back to Gemma 4.
- shell_executor: A secure wrapper that can run python3 or curl commands. This allows the agent to "propose and run" Python code without recompiling.
- web_deployer: A module that calls the here.now CLI to push research reports as live websites.

Component B: The "Skill-Set" (The "User-Space")

The agent won't have everything built-in. Instead, it will use Skills.

- Python Scripts: I will generate .py files in /root/research/scripts/. The Go engine will then run them via python3 script.py.
- Web Templates: I will generate HTML/JS for your here.now sites.

  

🔑 Handling the API Key & Security

Where to store the API key? Do NOT hard-code the API key into the main.go source. If you do, you have to recompile every time the key changes.

The Solution: Use an .env file or a secrets.json on the board.

1. Create a file: /root/.env
2. Add: HERE_NOW_API_KEY=your_key_here
3. The Go engine will read this file at runtime.

  

🚀 Implementation: The "Omni-Engine"

I am now updating the main.go to include these high-level capabilities.

New Capabilities being added:

1. run_python: Takes a Python script path $\rightarrow$ executes it $\rightarrow$ returns output.
2. scan_files: Finds files matching a pattern (e.g., *.jpg) and returns their metadata.
3. deploy_site: Wraps the here.now CLI to push a folder to the web.
4. internet_fetch: Uses curl to fetch a URL and return the text to the LLM.

The here.now setup:

I will include a "Setup" action in the engine that runs the curl install command automatically so you don't have to do it manually.

I am rewriting the main.go now to be this "Omni-Engine." 🦞

_(Self-correction: Since I cannot execute the_ **curl** _install of_ here.now _myself, I will make the engine capable of doing it on your behalf when you trigger the_ setup_web _action.)_

Wait a moment while I generate the "Omni-Engine" source code. 🦞

### 📋 What I Improved (Code Review)

|Issue|Before|After|
|---|---|---|
|**API Keys**|Hardcoded or missing|Loaded from `/root/.env` automatically|
|**Timeouts**|None — commands could hang forever|60-second timeout on all shell commands|
|**Python Execution**|Only file-based|Now supports **inline code** (`run_python_code`) — the LLM writes code and the engine runs it|
|**File Reading**|Not available|`read_file` reads text or Base64-encodes binary files (images) for LLM consumption|
|**I2C Scanning**|Not available|`i2c_scan` parses the output and returns a clean list of detected devices|
|**System Info**|Not available|`system_info` collects uptime, RAM, CPU, disk, and checks if `python3` / `here-now` are installed|
|**Error Handling**|Basic|Every command has timeout + error propagation + structured JSON output|
|**Logging**|Print only|Uses `log.Printf` with timestamps|

---

### 🔑 How to Set Up the API Key

On your board, run this **once**:

```bash
mkdir -p /root/research/scripts /root/research/sites

cat > /root/.env << 'EOF'
HERE_NOW_API_KEY=sk-your-actual-key-here
OLLAMA_HOST=http://192.168.36.123:11434
CAMERA_I2C_BUS=0
WORKSPACE=/root/research
SCRIPTS_DIR=/root/research/scripts
SITE_DIR=/root/research/sites
EOF
```

Then put the compiled binary in `/root/research/` alongside a `config.json`.

---

### 🚀 Compilation (One Time)

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-research-engine main.go
scp nano-research-engine root@<board-ip>:/root/research/
```

---

### 📖 Quick Reference: All Actions

| Action                | What It Does                                                 |
| --------------------- | ------------------------------------------------------------ |
| `system_info`         | Collects CPU, RAM, disk, uptime, checks for python3/here-now |
| `probe_cvitek`        | Checks if camera sensor is bound to the Cvitek driver        |
| `i2c_scan`            | Scans I2C bus for devices (finds camera sensors)             |
| `check_hardware`      | Checks for `/dev/video0`, `/dev/npu`, etc.                   |
| `measure_performance` | CPU benchmark with configurable iterations                   |
| `run_python`          | Runs a `.py` file already on the board                       |
| `run_python_code`     | Executes inline Python code (LLM writes it on the fly)       |
| `shell_cmd`           | Runs any shell command safely with timeout                   |
| `scan_files`          | Finds files matching a pattern                               |
| `read_file`           | Reads a file; auto-Base64-encodes images/binary              |
| `setup_web`           | Installs `here.now` via npm or curl                          |
| `deploy_site`         | Deploys a folder to the web using `here.now`                 |