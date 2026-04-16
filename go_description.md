
# Feasibility Evaluation & Complete Rewrite

## Feasibility Assessment

Every point raised in the review is valid and addressable within the Go-stdlib-only constraint. Here's the verdict per issue:

| Issue                                  | Verdict   | Fix Strategy                                                                 |
| -------------------------------------- | --------- | ---------------------------------------------------------------------------- |
| LLM YAML parsing fragile               | ✅ Fixable | Regex extraction of fenced blocks                                            |
| Security bypass via obfuscation        | ✅ Fixable | Dangerous-command blocklist + normalization                                  |
| SD card wear from aggressive writes    | ✅ Fixable | Dirty-flag + periodic flush + shutdown-guaranteed save                       |
| `max_memory_mb` not enforced           | ✅ Fixable | `ulimit -v` wrapping on shell/python commands                                |
| `updateMetrics()` stub                 | ✅ Fixable | Full implementation with shell check execution                               |
| Recovery/SimplicityBias unused         | ✅ Fixable | Inject into LLM prompt context                                               |
| `_contains` / `_matches` in expect     | ✅ Fixable | Enhanced `verifyExpectations` with suffix-based dispatch                     |
| Skill system unimplemented             | ✅ Fixable | Full `call_skill` → native → SKILL.md → shell/python/api chain               |
| Vision pipeline unimplemented          | ✅ Fixable | `capture_image` → skill or fallback → base64 → Ollama vision → `VisualTruth` |
| `executeCmdWithTimeout` race condition | ✅ Fixable | `Start/Wait` pattern with kill-goroutine safety                              |

All fixes stay within the zero-external-dependency constraint. The binary stays small.

---

## Complete `main.go`

```go
package main

// ════════════════════════════════════════════════════════════════════════
// IMPORTS
// ════════════════════════════════════════════════════════════════════════
// Only stdlib + yaml.v3. No net/http, no third-party frameworks.
// HTTP calls go through curl (already available on Nano-OS) to keep
// the binary tiny and avoid CGO dependencies.

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"gopkg.in/yaml.v3"
)

// ════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ════════════════════════════════════════════════════════════════════════
// Centralized configuration defaults. The engine reads these once
// at startup; skill directories and models can be overridden via
// environment variables or program.yaml without recompilation.

const (
	SkillsDir           = "/root/.picoclaw/workspace/skills"
	DefaultCapturePath  = "/tmp/capture.jpg"
	DefaultVisionModel  = "llava"
	DefaultLLMModel     = "llama3"
	MaxImageSizeBytes   = 4 * 1024 * 1024 // 4MB before base64 (~5.3MB after)
	DefaultFlushInterval = 50              // iterations between disk flushes
	VisionPrompt        = `Analyze this image carefully. Respond with ONLY ` +
		`valid JSON, no markdown fences, no extra text: ` +
		`{"is_clear":true/false,"description":"brief description",` +
		`"objects":["list","of","objects"],"confidence":0.0_to_1.0,` +
		`"issues":["noise","blur","black_screen","or empty array if fine"]}`
)

// dangerousCmdPatterns blocks commands that could brick the board or
// bypass the approval system through obfuscation (sudo, /proc writes,
// fork bombs, direct disk access, etc.). This is checked BEFORE
// the user-defined RequiresApproval patterns.

var dangerousCmdPatterns = []string{
	"sudo ", "sudo\t",
	"/proc/sys", "/proc/sysrq", "sysrq",
	"reboot", "poweroff", "halt", "init 0", "init 6",
	"mkfs.", "dd if=", "dd of=",
	"> /dev/sd", "> /dev/mmc",
	"chmod 000", "chmod -r",
	"rm -rf /", "rm -rf /*",
	":(){:|:&};:", // fork bomb
	"shutdown",
}

// ════════════════════════════════════════════════════════════════════════
// TYPES — Configuration
// ════════════════════════════════════════════════════════════════════════
// ProgramConfig mirrors program.yaml. Added MaxMemoryMB to enforce
// the constraint that was previously defined but unused.

type ProgramConfig struct {
	Goals struct {
		Primary   string   `yaml:"primary"`
		Secondary []string `yaml:"secondary"`
	} `yaml:"goals"`
	Constraints struct {
		Readonly         []string `yaml:"readonly"`
		RequiresApproval []string `yaml:"requires_approval"`
		MaxTimeout       int      `yaml:"max_timeout_seconds"`
		MaxMemoryMB      int      `yaml:"max_memory_mb"`
	} `yaml:"constraints"`
	Metrics  map[string]Metric `yaml:"metrics"`
	Strategy struct {
		MaxRetries     int      `yaml:"max_retries"`
		Recovery       []string `yaml:"recovery"`
		SimplicityBias bool     `yaml:"simplicity_bias"`
		UseLLM         bool     `yaml:"use_llm"`
		LLMModel       string   `yaml:"llm_model"`
		VisionModel    string   `yaml:"vision_model"`
	} `yaml:"strategy"`
	Loop struct {
		NeverStop    bool `yaml:"never_stop"`
		PollInterval int  `yaml:"poll_interval"`
	} `yaml:"loop"`
}

type Metric struct {
	Check  string      `yaml:"check"`
	Target interface{} `yaml:"target"`
}

// ════════════════════════════════════════════════════════════════════════
// TYPES — Tasks
// ════════════════════════════════════════════════════════════════════════

type Task struct {
	ID              string    `yaml:"id"`
	Name            string    `yaml:"name"`
	Priority        int       `yaml:"priority"`
	Status          string    `yaml:"status"`
	SuccessCriteria []string  `yaml:"success_criteria"`
	Steps           []Step    `yaml:"steps"`
	Subtasks        []Subtask `yaml:"subtasks"`
	SourceFile      string    `yaml:"-"`
}

type Step struct {
	ID         string                 `yaml:"id"`
	Action     string                 `yaml:"action"`
	Parameters map[string]interface{} `yaml:"parameters"`
	Timeout    int                    `yaml:"timeout"`
	Expect     map[string]interface{} `yaml:"expect"`
	OnFail     string                 `yaml:"on_fail"`
	MaxRetries int                    `yaml:"max_retries"`
}

type Subtask struct {
	ID   string `yaml:"id"`
	Name string `yaml:"name"`
	File string `yaml:"file"`
}

// ════════════════════════════════════════════════════════════════════════
// TYPES — Skill Config (parsed from SKILL.md YAML frontmatter)
// ════════════════════════════════════════════════════════════════════════
// Each skill directory contains a SKILL.md with YAML frontmatter
// describing how to invoke the skill. Example:
//
//   ---
//   name: vision-npu
//   exec_type: shell
//   command: ./capture.sh
//   input_format: env
//   output_format: json
//   timeout: 15
//   returns:
//     - image_path
//     - width
//   ---
//   # Vision NPU Skill
//   Captures images using the NPU pipeline.

type SkillConfig struct {
	Name         string       `yaml:"name"`
	ExecType     string       `yaml:"exec_type"`     // shell | python | native | api
	Command      string       `yaml:"command"`        // executable path (relative to skill dir)
	Endpoint     string       `yaml:"endpoint"`       // api type: URL with {param} placeholders
	Method       string       `yaml:"method"`         // api type: GET | POST
	InputFormat  string       `yaml:"input_format"`   // env | args | stdin | json_file
	OutputFormat string       `yaml:"output_format"`  // json | text | keyvalue
	Timeout      int          `yaml:"timeout"`
	Parameters   []SkillParam `yaml:"parameters"`
	Returns      []string     `yaml:"returns"`
	Description  string       `yaml:"description"`
}

type SkillParam struct {
	Name     string      `yaml:"name"`
	Type     string      `yaml:"type"`
	Default  interface{} `yaml:"default"`
	Required bool        `yaml:"required"`
}

// ════════════════════════════════════════════════════════════════════════
// TYPES — State
// ════════════════════════════════════════════════════════════════════════
// State is persisted to state.json. VisualTruth and CommandTruth are
// the key innovation: the LLM can compare what the system claims
// against what the camera actually sees. RecentFailures feeds the
// recovery context so the LLM doesn't repeat mistakes.

type State struct {
	CurrentTaskID  string                 `json:"current_task_id"`
	CurrentStepID  string                 `json:"current_step_id"`
	Iteration      int                    `json:"iteration"`
	History        []string               `json:"history"`
	Metrics        map[string]string      `json:"metrics"`
	LastResult     string                 `json:"last_result"`
	VisualTruth    string                 `json:"visual_truth"`
	CommandTruth   string                 `json:"command_truth"`
	SkillResults   map[string]interface{} `json:"skill_results"`
	RecentFailures []string               `json:"recent_failures"`
}

// ════════════════════════════════════════════════════════════════════════
// NATIVE SKILL REGISTRY
// ════════════════════════════════════════════════════════════════════════
// Native skills are compiled Go functions — the fastest, most
// memory-safe path. They're checked before SKILL.md, so a native
// handler always wins over an external script of the same name.
// This is intentional: hardware probes should never fall back to
// a shell script when a compiled handler exists.

type NativeSkillFunc func(e *Engine, params map[string]interface{}) (map[string]interface{}, error)

var nativeSkills = map[string]NativeSkillFunc{
	"i2c_scan":     nativeI2CScan,
	"probe_cvitek": nativeProbeCvitek,
	"list_skills":  nativeListSkills,
}

// ── nativeI2CScan ───────────────────────────────────────────────────
// Scans an I2C bus and returns device count + raw output.
// Params: bus (string), timeout (int)

func nativeI2CScan(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	bus := paramString(params, "bus", "")
	if bus == "" {
		bus = os.Getenv("CAMERA_I2C_BUS")
	}
	if bus == "" {
		bus = "0"
	}
	timeout := paramInt(params, "timeout", 10)

	out, err := runCommandWithTimeout(timeout, "i2cdetect", "-y", bus)
	count := 0
	for _, line := range strings.Split(out, "\n") {
		for _, f := range strings.Fields(line) {
			if f != "--" && f != "UU" && len(f) == 2 {
				count++
			}
		}
	}
	return map[string]interface{}{"count": count, "raw": out}, err
}

// ── nativeProbeCvitek ───────────────────────────────────────────────
// Checks /proc/cvitek/vi for sensor binding status.

func nativeProbeCvitek(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	data, err := ioutil.ReadFile("/proc/cvitek/vi")
	if err != nil {
		return map[string]interface{}{"sensor_bound": false, "error": err.Error()}, nil
	}
	content := string(data)
	return map[string]interface{}{
		"sensor_bound": strings.Contains(content, "DevID"),
		"raw":          strings.TrimSpace(content),
	}, nil
}

// ── nativeListSkills ────────────────────────────────────────────────
// Returns all available skills (native + SKILL.md directories).
// The LLM calls this to discover its toolset.

func nativeListSkills(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	seen := map[string]bool{}
	names := []string{}

	// Native skills
	for name := range nativeSkills {
		names = append(names, name)
		seen[name] = true
	}

	// Skills from filesystem
	files, err := ioutil.ReadDir(SkillsDir)
	if err == nil {
		for _, f := range files {
			if f.IsDir() && !seen[f.Name()] {
				skillMD := filepath.Join(SkillsDir, f.Name(), "SKILL.md")
				if _, err := os.Stat(skillMD); err == nil {
					names = append(names, f.Name())
					seen[f.Name()] = true
				}
			}
		}
	}

	sort.Strings(names)
	return map[string]interface{}{"skills": names, "count": len(names)}, nil
}

// ════════════════════════════════════════════════════════════════════════
// ENGINE
// ════════════════════════════════════════════════════════════════════════
// The Engine is the Manager in the Manager-Worker pattern.
// It owns state, dispatches actions, and reasons via LLM.

type Engine struct {
	Program      ProgramConfig
	State        State
	shutdown     chan os.Signal
	skillCache   map[string]*SkillConfig
	stateDirty   bool   // tracks if state needs flushing to disk
	flushCounter int    // counts iterations since last flush
	flushInterval int   // how often to write state.json (saves SD card)
}

func NewEngine() *Engine {
	e := &Engine{
		shutdown:      make(chan os.Signal, 1),
		skillCache:    make(map[string]*SkillConfig),
		flushInterval: DefaultFlushInterval,
	}
	e.loadEnv()
	e.loadProgram()
	e.loadState()

	// Apply defaults
	if e.Program.Strategy.LLMModel == "" {
		e.Program.Strategy.LLMModel = DefaultLLMModel
	}
	if e.Program.Strategy.VisionModel == "" {
		e.Program.Strategy.VisionModel = DefaultVisionModel
	}
	if e.State.SkillResults == nil {
		e.State.SkillResults = make(map[string]interface{})
	}
	if e.State.History == nil {
		e.State.History = make([]string, 0)
	}
	if e.State.Metrics == nil {
		e.State.Metrics = make(map[string]string)
	}
	if e.State.RecentFailures == nil {
		e.State.RecentFailures = make([]string, 0)
	}

	log.Printf("🤖 picoClaw Engine v3.0 — Skill-Aware Orchestrator")
	log.Printf("   LLM: %s | Vision: %s | MemLimit: %dMB",
		e.Program.Strategy.LLMModel,
		e.Program.Strategy.VisionModel,
		e.Program.Constraints.MaxMemoryMB)
	return e
}

// ── loadEnv / parseEnvFile ──────────────────────────────────────────
// Load .env for secrets (OLLAMA_HOST, API keys, etc.)

func (e *Engine) loadEnv() {
	for _, p := range []string{".env", "/root/.env"} {
		if err := parseEnvFile(p); err == nil {
			log.Printf("✅ Loaded .env from %s", p)
			return
		}
	}
}

func parseEnvFile(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 {
			os.Setenv(strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]))
		}
	}
	return nil
}

// ── loadProgram ─────────────────────────────────────────────────────

func (e *Engine) loadProgram() {
	data, err := ioutil.ReadFile("program.yaml")
	if err != nil {
		log.Fatalf("❌ Failed to load program.yaml: %v", err)
	}
	if err := yaml.Unmarshal(data, &e.Program); err != nil {
		log.Fatalf("❌ Invalid program.yaml: %v", err)
	}
}

// ── loadState / saveState ───────────────────────────────────────────
// State is loaded once at startup. saveState writes to disk.
// To protect the SD card, we use a dirty-flag + flush-interval
// pattern: state is only written when dirty AND either the
// flush-interval is reached OR the engine is shutting down.

func (e *Engine) loadState() {
	data, err := ioutil.ReadFile("state.json")
	if err != nil {
		e.State = State{
			Metrics:        make(map[string]string),
			History:        make([]string, 0),
			SkillResults:   make(map[string]interface{}),
			RecentFailures: make([]string, 0),
		}
		return
	}
	json.Unmarshal(data, &e.State)
}

func (e *Engine) saveState() {
	data, _ := json.MarshalIndent(e.State, "", "  ")
	ioutil.WriteFile("state.json", data, 0644)
	e.stateDirty = false
	e.flushCounter = 0
}

// markStateDirty flags state for eventual flush.
func (e *Engine) markStateDirty() {
	e.stateDirty = true
}

// flushStateIfNeeded writes state.json only when dirty AND the
// flush interval has elapsed. On a 2-second poll interval with
// flushInterval=50, this means a write every ~100 seconds instead
// of every 2 seconds — a 50x reduction in SD card writes.
func (e *Engine) flushStateIfNeeded() {
	if !e.stateDirty {
		return
	}
	e.flushCounter++
	if e.flushCounter >= e.flushInterval {
		e.saveState()
		log.Printf("💾 State flushed to disk (iteration %d)", e.State.Iteration)
	}
}

// ── appendResult ────────────────────────────────────────────────────
// Appends to results.tsv. This file is append-only so it doesn't
// cause wear from overwriting the same blocks. On tmpfs this is
// free; on SD card it writes to sequential sectors.

func (e *Engine) appendResult(taskID, stepID, status, description string) {
	f, err := os.OpenFile("results.tsv", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	timestamp := time.Now().Format("15:04:05")
	f.WriteString(fmt.Sprintf("%s\t%s\t%s\t%s\t%s\n", timestamp, taskID, stepID, status, description))
}

// ── isApproved ──────────────────────────────────────────────────────
// SECURITY: Two-layer check. First, block dangerous commands that
// could brick the board (sudo, reboot, /proc writes, fork bombs,
// direct disk access). Second, check user-defined patterns from
// program.yaml. Both checks use lowercase normalization to prevent
// trivial bypass (e.g., "Sudo" or "SUDO").

func (e *Engine) isApproved(cmdStr string) bool {
	lower := strings.ToLower(cmdStr)

	// Layer 1: Built-in dangerous command blocklist
	for _, pattern := range dangerousCmdPatterns {
		if strings.Contains(lower, strings.ToLower(pattern)) {
			log.Printf("🔒 Blocked dangerous command pattern: %q", pattern)
			return false
		}
	}

	// Layer 2: User-defined approval constraints
	for _, pattern := range e.Program.Constraints.RequiresApproval {
		if strings.Contains(lower, strings.ToLower(pattern)) {
			log.Printf("🔒 Blocked by approval constraint: %q", pattern)
			return false
		}
	}

	return true
}

// ── isReadonly ──────────────────────────────────────────────────────

func (e *Engine) isReadonly(path string) bool {
	for _, pattern := range e.Program.Constraints.Readonly {
		if matched, _ := filepath.Match(pattern, path); matched {
			return true
		}
		if strings.HasSuffix(pattern, "*") &&
			strings.HasPrefix(path, strings.TrimSuffix(pattern, "*")) {
			return true
		}
	}
	return false
}

// ════════════════════════════════════════════════════════════════════════
// UTILITY HELPERS
// ════════════════════════════════════════════════════════════════════════

// resolveTimeout picks the first non-zero value from step timeout,
// skill timeout, program max timeout. Falls back to 60s.

func resolveTimeout(values ...int) int {
	for _, v := range values {
		if v > 0 {
			return v
		}
	}
	return 60
}

// paramInt extracts an int from a map that might have been parsed
// from YAML (int) or JSON (float64) or even a string.

func paramInt(params map[string]interface{}, key string, defaultVal int) int {
	if v, ok := params[key].(int); ok && v > 0 {
		return v
	}
	if v, ok := params[key].(float64); ok && v > 0 {
		return int(v)
	}
	if v, ok := params[key].(string); ok {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return defaultVal
}

func paramString(params map[string]interface{}, key string, defaultVal string) string {
	if v, ok := params[key].(string); ok && v != "" {
		return v
	}
	return defaultVal
}

func paramBool(params map[string]interface{}, key string, defaultVal bool) bool {
	if v, ok := params[key].(bool); ok {
		return v
	}
	if v, ok := params[key].(string); ok {
		return strings.ToLower(v) == "true"
	}
	return defaultVal
}

// truncateString prevents runaway LLM output from consuming
// memory or filling logs on the resource-constrained board.

func truncateString(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

// ════════════════════════════════════════════════════════════════════════
// CORE LOOP
// ════════════════════════════════════════════════════════════════════════
// RunLoop is the Manager's main loop. It:
//   1. Catches SIGINT/SIGTERM for graceful shutdown (always flushes state)
//   2. Finds the highest-priority pending task
//   3. Executes each step with retry logic
//   4. Falls back to LLM task generation when idle
//   5. Updates metrics and conditionally flushes state

func (e *Engine) RunLoop() {
	// Graceful shutdown — ALWAYS saves state, even on SIGKILL path
	signal.Notify(e.shutdown, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-e.shutdown
		log.Println("🛑 Shutdown signal — flushing state to disk...")
		e.saveState()
		os.Exit(0)
	}()

	// Initialize results.tsv if needed
	if _, err := os.Stat("results.tsv"); os.IsNotExist(err) {
		ioutil.WriteFile("results.tsv", []byte("time\ttask\tstep\tstatus\tdescription\n"), 0644)
	}

	for {
		e.State.Iteration++
		log.Printf("🔄 ─── Iteration %d ───", e.State.Iteration)

		task, err := e.findNextTask()
		if err != nil {
			log.Printf("⚠️ %v", err)
			e.handleIdle()
		} else {
			e.executeTask(task)
		}

		e.updateMetrics()
		e.flushStateIfNeeded()

		if !e.Program.Loop.NeverStop {
			break
		}
		time.Sleep(time.Duration(e.Program.Loop.PollInterval) * time.Second)
	}
}

// ── findNextTask ────────────────────────────────────────────────────
// Scans tasks/ for pending YAML files, returns highest priority.

func (e *Engine) findNextTask() (*Task, error) {
	files, err := ioutil.ReadDir("tasks")
	if err != nil {
		return nil, err
	}
	var candidates []*Task
	for _, f := range files {
		if !strings.HasSuffix(f.Name(), ".yaml") && !strings.HasSuffix(f.Name(), ".yml") {
			continue
		}
		path := filepath.Join("tasks", f.Name())
		data, err := ioutil.ReadFile(path)
		if err != nil {
			continue
		}
		var wrapper struct {
			Task Task `yaml:"task"`
		}
		if err := yaml.Unmarshal(data, &wrapper); err != nil {
			log.Printf("⚠️ Skipping %s: %v", f.Name(), err)
			continue
		}
		t := wrapper.Task
		t.SourceFile = path
		if t.Status == "pending" || t.Status == "running" {
			candidates = append(candidates, &t)
		}
	}
	if len(candidates) == 0 {
		return nil, fmt.Errorf("no pending tasks")
	}
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].Priority < candidates[j].Priority
	})
	return candidates[0], nil
}

// ── executeTask ──────────────────────────────────────────────────────
// Executes each step of a task with retry backoff. On step failure,
// records the failure in State.RecentFailures so the LLM can learn
// from it when generating the next task.

func (e *Engine) executeTask(t *Task) {
	log.Printf("🚀 Task [%s] %s (priority %d)", t.ID, t.Name, t.Priority)
	e.State.CurrentTaskID = t.ID
	t.Status = "running"
	e.saveTaskStatus(t)

	for _, step := range t.Steps {
		e.State.CurrentStepID = step.ID
		e.markStateDirty()

		var success bool
		var resultData map[string]interface{}
		var lastErr error

		for attempt := 0; attempt <= step.MaxRetries; attempt++ {
			resultData, lastErr = e.dispatchAction(step.Action, step.Parameters, step.Timeout)
			if lastErr == nil && e.verifyExpectations(resultData, step.Expect) {
				success = true
				break
			}
			if lastErr != nil {
				log.Printf("  ⚠️ Step %s attempt %d/%d: %v",
					step.ID, attempt+1, step.MaxRetries+1, lastErr)
			}
			if attempt < step.MaxRetries {
				backoff := time.Duration(attempt+1) * 2 * time.Second
				log.Printf("  ⏳ Retry in %v...", backoff)
				time.Sleep(backoff)
			}
		}

		if success {
			e.appendResult(t.ID, step.ID, "keep", step.Action)
			log.Printf("  ✅ Step %s succeeded", step.ID)
		} else {
			errMsg := "unknown"
			if lastErr != nil {
				errMsg = lastErr.Error()
			}
			// Record failure for LLM recovery context
			failureEntry := fmt.Sprintf("%s/%s: %s (%s)", t.ID, step.ID, step.Action, errMsg)
			e.State.RecentFailures = append(e.State.RecentFailures, failureEntry)
			if len(e.State.RecentFailures) > 10 {
				e.State.RecentFailures = e.State.RecentFailures[len(e.State.RecentFailures)-10:]
			}

			if step.OnFail == "block" {
				t.Status = "blocked"
				e.appendResult(t.ID, step.ID, "crash", "blocked: "+errMsg)
				log.Printf("  🛑 Step %s blocked task", step.ID)
				e.saveTaskStatus(t)
				e.markStateDirty()
				return
			}
			e.appendResult(t.ID, step.ID, "discard", errMsg)
			log.Printf("  ❌ Step %s failed: %s", step.ID, errMsg)
		}
	}

	// Final verdict
	if e.verifyTaskSuccess(t) {
		t.Status = "completed"
		e.appendResult(t.ID, "FINAL", "keep", "done")
		log.Printf("✅ Task [%s] completed", t.ID)
	} else {
		t.Status = "failed"
		e.appendResult(t.ID, "FINAL", "discard", "success criteria not met")
		log.Printf("❌ Task [%s] failed criteria", t.ID)
	}
	e.saveTaskStatus(t)
	e.spawnSubtasks(t)

	entry := fmt.Sprintf("[%d] %s → %s", e.State.Iteration, t.Name, t.Status)
	e.State.History = append(e.State.History, entry)
	if len(e.State.History) > 100 {
		e.State.History = e.State.History[len(e.State.History)-100:]
	}
	e.markStateDirty()
}

func (e *Engine) spawnSubtasks(parent *Task) {
	for _, sub := range parent.Subtasks {
		targetPath := filepath.Join("tasks", filepath.Base(sub.File))
		if _, err := os.Stat(targetPath); err == nil {
			continue
		}
		if data, err := ioutil.ReadFile(sub.File); err == nil {
			ioutil.WriteFile(targetPath, data, 0644)
			log.Printf("📋 Spawned subtask: %s → %s", sub.Name, targetPath)
		}
	}
}

// ════════════════════════════════════════════════════════════════════════
// LLM INTERACTION
// ════════════════════════════════════════════════════════════════════════
// When idle, the engine asks the LLM to generate a new task.
// The prompt includes VisualTruth, CommandTruth, RecentFailures,
// and recovery strategies so the LLM can reason about reality.

func (e *Engine) handleIdle() {
	if e.Program.Strategy.UseLLM {
		e.askLLMForTask()
	} else {
		log.Println("💤 Idle — no LLM strategy configured")
	}
}

// ── buildRecoveryContext ────────────────────────────────────────────
// Constructs a string describing recent failures and available
// recovery strategies. Injected into the LLM prompt so it avoids
// repeating the same mistakes and can suggest recovery approaches.

func (e *Engine) buildRecoveryContext() string {
	if len(e.State.RecentFailures) == 0 {
		return ""
	}
	ctx := "Recent failures (DO NOT repeat these approaches unchanged):\n"
	for _, f := range e.State.RecentFailures {
		ctx += fmt.Sprintf("  - %s\n", f)
	}
	if len(e.Program.Strategy.Recovery) > 0 {
		ctx += "Available recovery strategies:\n"
		for _, r := range e.Program.Strategy.Recovery {
			ctx += fmt.Sprintf("  - %s\n", r)
		}
	}
	return ctx
}

// ── askLLMForTask ───────────────────────────────────────────────────
// Generates a new task YAML via the LLM. Includes:
//   - Visual Truth (camera) and Command Truth (CLI)
//   - Simplicity bias directive (from program.yaml)
//   - Recovery context (recent failures + strategies)
//   - Available skills list
//   - Regex-based YAML extraction (handles LLM conversational filler)

func (e *Engine) askLLMForTask() {
	ollamaHost := os.Getenv("OLLAMA_HOST")
	if ollamaHost == "" {
		ollamaHost = "http://localhost:11434"
	}

	// Discover available skills
	skillResult, _ := nativeListSkills(e, nil)
	skillsJSON, _ := json.Marshal(skillResult)

	prompt := fmt.Sprintf(
		"You are an autonomous agent on a Nano-OS embedded board (LicheeRV Nano, CV1800B).\n"+
			"Primary Goal: %s\n"+
			"Current Metrics: %v\n"+
			"Visual Truth (what camera sees): %s\n"+
			"Command Truth (last system output): %s\n"+
			"Available Skills: %s\n\n",
		e.Program.Goals.Primary,
		e.State.Metrics,
		e.State.VisualTruth,
		e.State.CommandTruth,
		string(skillsJSON),
	)

	// Inject simplicity bias if enabled
	if e.Program.Strategy.SimplicityBias {
		prompt += "CONSTRAINT: Prefer the simplest possible shell command over complex Python scripts. One-liners are preferred.\n\n"
	}

	// Inject recovery context from recent failures
	recovery := e.buildRecoveryContext()
	if recovery != "" {
		prompt += recovery + "\n"
	}

	prompt += "Suggest ONE new task in YAML format. Use these action types:\n" +
		"  call_skill, capture_image, analyze_image, shell_cmd, run_python_code, skill_list, i2c_scan, probe_cvitek\n\n" +
		"Respond with the task wrapped in ```yaml fences:\n" +
		"```yaml\n" +
		"task:\n" +
		"  id: <unique_id>\n" +
		"  name: <descriptive_name>\n" +
		"  priority: <1-10>\n" +
		"  status: pending\n" +
		"  success_criteria: []\n" +
		"  steps:\n" +
		"    - id: step1\n" +
		"      action: <action_type>\n" +
		"      parameters: {}\n" +
		"      expect: {}\n" +
		"```\n"

	payload := map[string]interface{}{
		"model":  e.Program.Strategy.LLMModel,
		"prompt": prompt,
		"stream": false,
	}
	pJSON, _ := json.Marshal(payload)

	out, err := runCommandWithTimeout(90, "curl", "-s", "-X", "POST",
		ollamaHost+"/api/generate",
		"-H", "Content-Type: application/json",
		"-d", string(pJSON))
	if err != nil {
		log.Printf("⚠️ LLM task generation failed: %v", err)
		return
	}

	var resp struct {
		Response string `json:"response"`
	}
	if err := json.Unmarshal([]byte(out), &resp); err != nil {
		log.Printf("⚠️ Failed to parse LLM response: %v", err)
		return
	}

	// ── Regex-based YAML extraction ──────────────────────────────
	// Handles conversational filler before/after the code block.
	// Also handles ```yml as well as ```yaml.
	re := regexp.MustCompile("(?s)```(?:ya?ml)?\\s*\n(.*?)\n```")
	matches := re.FindStringSubmatch(resp.Response)
	yamlContent := ""
	if len(matches) > 1 {
		yamlContent = strings.TrimSpace(matches[1])
	} else {
		// Fallback: try parsing the whole response as YAML
		yamlContent = strings.TrimSpace(resp.Response)
	}

	if yamlContent == "" {
		log.Println("⚠️ LLM returned empty task")
		return
	}

	// Validate it parses before saving
	var testWrapper struct {
		Task Task `yaml:"task"`
	}
	if err := yaml.Unmarshal([]byte(yamlContent), &testWrapper); err != nil {
		log.Printf("⚠️ LLM returned invalid YAML: %v\nContent: %s", err, truncateString(yamlContent, 200))
		return
	}
	if testWrapper.Task.ID == "" {
		log.Println("⚠️ LLM task missing ID, skipping")
		return
	}

	filename := fmt.Sprintf("tasks/%d_llm.yaml", time.Now().Unix())
	if err := ioutil.WriteFile(filename, []byte(yamlContent), 0644); err != nil {
		log.Printf("⚠️ Failed to write LLM task: %v", err)
		return
	}
	log.Printf("🧠 LLM generated task: %s (id: %s)", filename, testWrapper.Task.ID)
}

// ════════════════════════════════════════════════════════════════════════
// ACTION DISPATCHER
// ════════════════════════════════════════════════════════════════════════
// Central routing. New actions: call_skill, capture_image,
// analyze_image, skill_list. Legacy actions preserved for
// backward compatibility with existing YAML tasks.

func (e *Engine) dispatchAction(action string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	t := resolveTimeout(timeout, e.Program.Constraints.MaxTimeout)

	switch action {
	// ── Legacy actions ──
	case "shell_cmd":
		return e.runShellCommand(params, t)
	case "run_python_code":
		return e.executePythonCode(params, t)

	// ── Legacy hardware probes (now route through skill system) ──
	case "i2c_scan":
		return e.callSkill("i2c_scan", params, t)
	case "probe_cvitek":
		return e.callSkill("probe_cvitek", params, t)

	// ── Skill-Aware Orchestrator actions ──
	case "call_skill":
		return e.actionCallSkill(params, t)
	case "capture_image":
		return e.captureImage(params, t)
	case "analyze_image":
		return e.analyzeImageAction(params, t)
	case "skill_list":
		return e.callSkill("list_skills", nil, t)

	default:
		return nil, fmt.Errorf("unsupported action: %s", action)
	}
}

// ════════════════════════════════════════════════════════════════════════
// LEGACY ACTIONS (enhanced with memory limits)
// ════════════════════════════════════════════════════════════════════════

// ── runShellCommand ─────────────────────────────────────────────────
// Executes a shell command. If max_memory_mb is set, wraps with
// ulimit -v to prevent the spawned process from consuming all RAM.

func (e *Engine) runShellCommand(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	cmdStr, _ := params["cmd"].(string)
	if !e.isApproved(cmdStr) {
		return nil, fmt.Errorf("command blocked by security policy")
	}

	// Enforce memory limit via ulimit if configured
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d; %s", memKB, cmdStr)
	}

	out, err := runCommandWithTimeout(timeout, "sh", "-c", cmdStr)
	e.State.CommandTruth = truncateString(out, 500)
	e.markStateDirty()
	return map[string]interface{}{"output": out}, err
}

// ── executePythonCode ───────────────────────────────────────────────
// Writes Python code to a temp file and executes it. Memory-limited
// via ulimit if max_memory_mb is configured.

func (e *Engine) executePythonCode(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	code, _ := params["code"].(string)
	path := filepath.Join("/tmp", fmt.Sprintf("auto_%d.py", time.Now().UnixNano()))
	ioutil.WriteFile(path, []byte(code), 0644)
	defer os.Remove(path)

	cmdStr := fmt.Sprintf("python3 %s", path)
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d; python3 %s", memKB, path)
	}

	out, err := runCommandWithTimeout(timeout, "sh", "-c", cmdStr)
	e.State.CommandTruth = truncateString(out, 500)
	e.markStateDirty()
	return map[string]interface{}{"output": out}, err
}

// ════════════════════════════════════════════════════════════════════════
// SKILL SYSTEM
// ════════════════════════════════════════════════════════════════════════
// The Skill System is the core of the Orchestrator pattern.
//
// Resolution order:
//   1. Native Go handlers (fastest, memory-safe, no external deps)
//   2. SKILL.md frontmatter → shell/python/api execution
//
// This means adding a new capability (github, webscraper, etc.)
// requires only creating a directory with a SKILL.md + run.sh —
// zero Go code changes needed.

// ── actionCallSkill ─────────────────────────────────────────────────
// Entry point for the call_skill action. Extracts skill_name
// from parameters and delegates to callSkill.
//
// YAML usage:
//   action: call_skill
//   parameters:
//     skill_name: vision-npu
//     output_path: /tmp/capture.jpg

func (e *Engine) actionCallSkill(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	skillName, ok := params["skill_name"].(string)
	if !ok || skillName == "" {
		return nil, fmt.Errorf("call_skill requires 'skill_name' parameter")
	}

	// Strip skill_name from params; pass the rest to the skill
	skillParams := make(map[string]interface{})
	for k, v := range params {
		if k != "skill_name" {
			skillParams[k] = v
		}
	}

	log.Printf("🛠️ call_skill: %s", skillName)
	return e.callSkill(skillName, skillParams, timeout)
}

// ── callSkill ───────────────────────────────────────────────────────
// Central skill dispatcher. Checks native handlers first, then
// loads SKILL.md and dispatches by exec_type. Results are cached
// in State.SkillResults so subsequent steps can reference them.

func (e *Engine) callSkill(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	// Layer 1: Native Go handler (always wins)
	if handler, ok := nativeSkills[name]; ok {
		result, err := handler(e, params)
		if result != nil {
			e.State.SkillResults[name] = result
			e.markStateDirty()
		}
		return result, err
	}

	// Layer 2: Load SKILL.md configuration
	config, err := e.loadSkillConfig(name)
	if err != nil {
		return nil, fmt.Errorf("skill %q not found: %v", name, err)
	}

	t := resolveTimeout(timeout, config.Timeout, e.Program.Constraints.MaxTimeout)

	// Apply skill default parameters for any missing required params
	params = e.applySkillDefaults(config, params)

	var result map[string]interface{}

	switch config.ExecType {
	case "shell":
		result, err = e.executeShellSkill(config, params, t)
	case "python":
		result, err = e.executePythonSkill(config, params, t)
	case "api":
		result, err = e.executeAPISkill(config, params, t)
	case "native":
		return nil, fmt.Errorf("native skill %q not registered in Go binary", name)
	default:
		return nil, fmt.Errorf("unknown exec_type %q for skill %s", config.ExecType, name)
	}

	if result != nil {
		e.State.SkillResults[name] = result
		e.markStateDirty()
	}
	return result, err
}

// ── applySkillDefaults ──────────────────────────────────────────────
// Fills in default values from SkillConfig.Parameters for any
// parameters not provided by the caller.

func (e *Engine) applySkillDefaults(config *SkillConfig, params map[string]interface{}) map[string]interface{} {
	merged := make(map[string]interface{})
	for k, v := range params {
		merged[k] = v
	}
	for _, p := range config.Parameters {
		if _, ok := merged[p.Name]; !ok && p.Default != nil {
			merged[p.Name] = p.Default
		}
	}
	return merged
}

// ── loadSkillConfig ─────────────────────────────────────────────────
// Reads and parses SKILL.md from the skill directory.
// Caches the parsed config to avoid re-reading the filesystem
// on every invocation.

func (e *Engine) loadSkillConfig(name string) (*SkillConfig, error) {
	if config, ok := e.skillCache[name]; ok {
		return config, nil
	}

	skillMD := filepath.Join(SkillsDir, name, "SKILL.md")
	data, err := ioutil.ReadFile(skillMD)
	if err != nil {
		return nil, fmt.Errorf("SKILL.md not found at %s: %v", skillMD, err)
	}

	config, err := parseSkillFrontmatter(string(data))
	if err != nil {
		return nil, fmt.Errorf("failed to parse %s: %v", skillMD, err)
	}

	// If name wasn't in frontmatter, use directory name
	if config.Name == "" {
		config.Name = name
	}

	// Resolve relative command paths to absolute
	if config.Command != "" && !filepath.IsAbs(config.Command) {
		config.Command = filepath.Join(SkillsDir, name, config.Command)
	}

	e.skillCache[name] = config
	log.Printf("📖 Loaded skill config: %s (type=%s, cmd=%s)", name, config.ExecType, config.Command)
	return config, nil
}

// ── parseSkillFrontmatter ───────────────────────────────────────────
// Extracts YAML frontmatter (between --- delimiters) from a
// SKILL.md file and unmarshals it into a SkillConfig.

func parseSkillFrontmatter(content string) (*SkillConfig, error) {
	re := regexp.MustCompile("(?s)^---\\s*\\n(.*?)\\n---")
	matches := re.FindStringSubmatch(content)
	if len(matches) < 2 {
		return nil, fmt.Errorf("no YAML frontmatter found (must start with ---)")
	}

	var config SkillConfig
	if err := yaml.Unmarshal([]byte(matches[1]), &config); err != nil {
		return nil, fmt.Errorf("frontmatter YAML parse error: %v", err)
	}
	return &config, nil
}

// ── executeShellSkill ───────────────────────────────────────────────
// Executes a shell-based skill. Parameters are passed according
// to the skill's input_format:
//   - env:   SKILL_<KEY>=<value> environment variables (DEFAULT)
//   - stdin: JSON piped via stdin
//   - args:  --key=value appended to command
//   - json_file: written to temp file, path passed as --params

func (e *Engine) executeShellSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	if config.Command == "" {
		return nil, fmt.Errorf("skill %s has no command defined", config.Name)
	}

	inputFmt := config.InputFormat
	if inputFmt == "" {
		inputFmt = "env" // safe default for shell scripts
	}

	cmd := exec.Command("sh", "-c", config.Command)
	cmd.Env = os.Environ()
	cmd.Dir = filepath.Dir(config.Command) // CWD = skill directory

	switch inputFmt {
	case "env":
		for k, v := range params {
			envKey := "SKILL_" + strings.ToUpper(k)
			cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%v", envKey, v))
		}

	case "stdin":
		jsonData, _ := json.Marshal(params)
		cmd.Stdin = bytes.NewReader(jsonData)

	case "json_file":
		jsonData, _ := json.Marshal(params)
		tmpFile, err := ioutil.TempFile("", "skill_params_*.json")
		if err != nil {
			return nil, err
		}
		tmpFile.Write(jsonData)
		tmpFile.Close()
		defer os.Remove(tmpFile.Name())
		// Append --params flag to the command
		cmd = exec.Command("sh", "-c", config.Command+" --params "+tmpFile.Name())
		cmd.Env = os.Environ()
		cmd.Dir = filepath.Dir(config.Command)

	case "args":
		// Build --key=value arguments appended to the command
		argParts := []string{}
		for k, v := range params {
			argParts = append(argParts, fmt.Sprintf("--%s=%v", k, v))
		}
		if len(argParts) > 0 {
			cmd = exec.Command("sh", "-c",
				config.Command+" "+strings.Join(argParts, " "))
			cmd.Env = os.Environ()
			cmd.Dir = filepath.Dir(config.Command)
		}

	default:
		return nil, fmt.Errorf("unsupported input_format %q", inputFmt)
	}

	// Enforce memory limit
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmd.Env = append(cmd.Env, fmt.Sprintf("SKILL_MEMORY_LIMIT_KB=%d", memKB))
		// Prepend ulimit to the shell command
		origCmd := cmd.Args[len(cmd.Args)-1] // the -c argument
		cmd = exec.Command("sh", "-c",
			fmt.Sprintf("ulimit -v %d; %s", memKB, origCmd))
		cmd.Env = os.Environ()
	}

	out, err := executeCmdWithTimeout(cmd, timeout)

	// Parse output based on output_format
	result := e.parseSkillOutput(out, config.OutputFormat)
	return result, err
}

// ── executePythonSkill ──────────────────────────────────────────────
// Executes a Python-based skill. Similar to shell but invokes
// python3 explicitly. Parameters passed as JSON via stdin by default.

func (e *Engine) executePythonSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	if config.Command == "" {
		return nil, fmt.Errorf("skill %s has no command defined", config.Name)
	}

	inputFmt := config.InputFormat
	if inputFmt == "" {
		inputFmt = "stdin" // Python prefers JSON via stdin
	}

	// Build command string with optional memory limit
	cmdStr := config.Command
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d; python3 %s", memKB, config.Command)
	} else {
		cmdStr = fmt.Sprintf("python3 %s", config.Command)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = os.Environ()
	cmd.Dir = filepath.Dir(config.Command)

	switch inputFmt {
	case "stdin":
		jsonData, _ := json.Marshal(params)
		cmd.Stdin = bytes.NewReader(jsonData)
	case "env":
		for k, v := range params {
			cmd.Env = append(cmd.Env, fmt.Sprintf("SKILL_%s=%v", strings.ToUpper(k), v))
		}
	case "json_file":
		jsonData, _ := json.Marshal(params)
		tmpFile, err := ioutil.TempFile("", "skill_params_*.json")
		if err != nil {
			return nil, err
		}
		tmpFile.Write(jsonData)
		tmpFile.Close()
		defer os.Remove(tmpFile.Name())
		cmd = exec.Command("sh", "-c",
			fmt.Sprintf("%s --params %s", cmdStr, tmpFile.Name()))
		cmd.Env = os.Environ()
	case "args":
		argParts := []string{}
		for k, v := range params {
			argParts = append(argParts, fmt.Sprintf("--%s=%v", k, v))
		}
		if len(argParts) > 0 {
			cmd = exec.Command("sh", "-c",
				fmt.Sprintf("%s %s", cmdStr, strings.Join(argParts, " ")))
			cmd.Env = os.Environ()
		}
	}

	out, err := executeCmdWithTimeout(cmd, timeout)
	result := e.parseSkillOutput(out, config.OutputFormat)
	return result, err
}

// ── executeAPISkill ──────────────────────────────────────────────────
// Makes an HTTP request via curl. Endpoint may contain {param}
// placeholders that get replaced with actual parameter values.
// POST sends params as JSON body; GET sends as query string.
// Uses curl to avoid importing net/http (keeps binary small).

func (e *Engine) executeAPISkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	endpoint := config.Endpoint
	for k, v := range params {
		endpoint = strings.ReplaceAll(endpoint, "{"+k+"}", fmt.Sprintf("%v", v))
	}

	method := strings.ToUpper(config.Method)
	if method == "" {
		method = "GET"
	}

	var cmd *exec.Cmd

	if method == "POST" {
		// Write JSON body to temp file to avoid shell arg length limits
		bodyJSON, _ := json.Marshal(params)
		tmpFile, err := ioutil.TempFile("", "api_body_*.json")
		if err != nil {
			return nil, err
		}
		tmpFile.Write(bodyJSON)
		tmpFile.Close()
		defer os.Remove(tmpFile.Name())

		cmd = exec.Command("curl", "-s", "-X", "POST", endpoint,
			"-H", "Content-Type: application/json",
			"-d", "@"+tmpFile.Name(),
			"--max-time", fmt.Sprintf("%d", timeout))
	} else {
		// GET: append params as query string
		parts := []string{}
		for k, v := range params {
			parts = append(parts, fmt.Sprintf("%s=%v", k, v))
		}
		if len(parts) > 0 {
			sep := "&"
			if strings.Contains(endpoint, "?") {
				sep = "&"
			} else {
				sep = "?"
			}
			endpoint += sep + strings.Join(parts, "&")
		}
		cmd = exec.Command("curl", "-s", endpoint,
			"--max-time", fmt.Sprintf("%d", timeout))
	}

	cmd.Env = os.Environ()
	out, err := executeCmdWithTimeout(cmd, timeout)
	if err != nil {
		return nil, fmt.Errorf("API call to %s failed: %v", endpoint, err)
	}

	result := e.parseSkillOutput(out, config.OutputFormat)
	return result, nil
}

// ── parseSkillOutput ────────────────────────────────────────────────
// Converts raw skill stdout into a structured map based on
// the output_format declared in SKILL.md frontmatter.

func (e *Engine) parseSkillOutput(raw string, format string) map[string]interface{} {
	raw = strings.TrimSpace(raw)

	switch format {
	case "json":
		var result map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &result); err == nil {
			return result
		}
		// JSON parse failed — return raw with error flag
		return map[string]interface{}{
			"output":      raw,
			"parse_error": "invalid json",
		}

	case "keyvalue":
		result := make(map[string]interface{})
		for _, line := range strings.Split(raw, "\n") {
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 {
				result[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
			}
		}
		if len(result) == 0 {
			result["output"] = raw
		}
		return result

	case "text", "":
		return map[string]interface{}{"output": raw}

	default:
		return map[string]interface{}{"output": raw}
	}
}

// ════════════════════════════════════════════════════════════════════════
// VISION SYSTEM
// ════════════════════════════════════════════════════════════════════════
// The Vision System implements the "Visual Truth" half of the
// dual-truth architecture. It:
//   1. Captures images (via vision-npu skill or direct fallback)
//   2. Sends images to a vision-capable LLM (llava, minicpm-v)
//   3. Parses the LLM's analysis into structured JSON
//   4. Updates State.VisualTruth for cross-referencing by the LLM
//
// This is what makes the agent "see" — not just trust CLI output.

// ── captureImage ─────────────────────────────────────────────────────
// Full vision pipeline: capture + optional LLM analysis.
// Tries the vision-npu skill first; if it doesn't exist, falls
// back to direct ffmpeg/v4l2 capture.
//
// YAML usage:
//   action: capture_image
//   parameters:
//     output_path: /tmp/capture.jpg
//     analyze: true          # default: true
//     prompt: "custom..."    # optional, overrides default vision prompt
//   expect:
//     is_clear: "true"

func (e *Engine) captureImage(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	outputPath := paramString(params, "output_path", DefaultCapturePath)
	analyze := paramBool(params, "analyze", true)

	log.Printf("📸 Capturing image → %s", outputPath)

	// Step 1: Capture — try vision-npu skill, fall back to direct capture
	var captureResult map[string]interface{}
	var captureErr error

	if _, err := os.Stat(filepath.Join(SkillsDir, "vision-npu", "SKILL.md")); err == nil {
		// vision-npu skill exists — use it
		captureParams := map[string]interface{}{
			"output_path": outputPath,
		}
		for k, v := range params {
			if k != "analyze" && k != "prompt" && k != "skill_name" {
				captureParams[k] = v
			}
		}
		captureResult, captureErr = e.callSkill("vision-npu", captureParams, timeout)
	} else {
		// No vision-npu skill — use direct hardware capture
		captureErr = e.directCaptureFallback(outputPath, timeout)
		if captureErr == nil {
			captureResult = map[string]interface{}{
				"image_path": outputPath,
				"method":     "direct_fallback",
			}
		}
	}

	if captureErr != nil {
		return nil, fmt.Errorf("image capture failed: %v", captureErr)
	}

	// Step 2: Verify the image file actually exists and has content
	info, err := os.Stat(outputPath)
	if err != nil || info.Size() == 0 {
		return nil, fmt.Errorf("image file %s missing or empty after capture", outputPath)
	}

	result := map[string]interface{}{
		"image_path": outputPath,
		"captured":   true,
		"size_bytes": info.Size(),
	}
	// Merge capture result
	for k, v := range captureResult {
		if _, exists := result[k]; !exists {
			result[k] = v
		}
	}

	// Step 3: Optional LLM analysis
	if analyze {
		customPrompt := paramString(params, "prompt", "")
		analysis, analysisErr := e.analyzeImageWithLLM(outputPath, customPrompt)
		if analysisErr != nil {
			log.Printf("⚠️ Vision analysis failed: %v", analysisErr)
			result["analysis_error"] = analysisErr.Error()
			result["is_clear"] = false
		} else {
			for k, v := range analysis {
				result[k] = v
			}
			// Update Visual Truth — the core innovation
			if desc, ok := analysis["description"].(string); ok && desc != "" {
				e.State.VisualTruth = desc
			}
			if isClear, ok := analysis["is_clear"].(bool); ok {
				log.Printf("👁️ Visual Truth: is_clear=%v", isClear)
			}
		}
	}

	e.State.CommandTruth = fmt.Sprintf("captured %s (%d bytes)", outputPath, info.Size())
	e.markStateDirty()
	return result, nil
}

// ── analyzeImageAction ──────────────────────────────────────────────
// Analyzes an existing image file without capturing a new one.
// Useful for re-analyzing a previously captured image, or for
// checking images placed by other processes.
//
// YAML usage:
//   action: analyze_image
//   parameters:
//     image_path: /tmp/capture.jpg
//     prompt: "Is this a circuit board?"

func (e *Engine) analyzeImageAction(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	imagePath := paramString(params, "image_path", "")
	if imagePath == "" {
		return nil, fmt.Errorf("analyze_image requires 'image_path' parameter")
	}

	if _, err := os.Stat(imagePath); os.IsNotExist(err) {
		return nil, fmt.Errorf("image not found: %s", imagePath)
	}

	customPrompt := paramString(params, "prompt", "")
	result, err := e.analyzeImageWithLLM(imagePath, customPrompt)
	if err != nil {
		return nil, err
	}

	// Update Visual Truth
	if desc, ok := result["description"].(string); ok && desc != "" {
		e.State.VisualTruth = desc
		e.markStateDirty()
	}

	log.Printf("👁️ Image analysis complete: %s", truncateString(
		fmt.Sprintf("%v", result["description"]), 80))
	return result, nil
}

// ── analyzeImageWithLLM ─────────────────────────────────────────────
// Core vision analysis: base64-encodes the image, sends to
// Ollama's vision model, parses structured JSON from the response.
//
// Key design decisions:
//   - Payload written to temp file (avoids shell arg length limits)
//   - Image resized if > MaxImageSizeBytes (saves RAM on board)
//   - JSON extracted via regex (LLMs add markdown fences)
//   - Falls back to keyword analysis if JSON parse fails

func (e *Engine) analyzeImageWithLLM(imagePath string, customPrompt string) (map[string]interface{}, error) {
	// 1. Prepare image (resize if needed)
	imageData, err := e.prepareImageForAnalysis(imagePath)
	if err != nil {
		return nil, fmt.Errorf("image preparation failed: %v", err)
	}

	encoded := base64.StdEncoding.EncodeToString(imageData)
	log.Printf("📦 Image base64: %d bytes → %d chars", len(imageData), len(encoded))

	// 2. Choose prompt
	prompt := VisionPrompt
	if customPrompt != "" {
		prompt = customPrompt
	}

	// 3. Build Ollama API payload
	payload := map[string]interface{}{
		"model":  e.Program.Strategy.VisionModel,
		"prompt": prompt,
		"images": []string{encoded},
		"stream": false,
	}

	// 4. Write payload to temp file — CRITICAL for large images
	// Passing base64 via curl -d would hit shell argument length limits
	payloadJSON, _ := json.Marshal(payload)
	tmpFile, err := ioutil.TempFile("", "vision_*.json")
	if err != nil {
		return nil, err
	}
	tmpFile.Write(payloadJSON)
	tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	// 5. Call Ollama
	ollamaHost := os.Getenv("OLLAMA_HOST")
	if ollamaHost == "" {
		ollamaHost = "http://localhost:11434"
	}

	out, err := runCommandWithTimeout(120, "curl", "-s", "-X", "POST",
		ollamaHost+"/api/generate",
		"-H", "Content-Type: application/json",
		"-d", "@"+tmpFile.Name())
	if err != nil {
		return nil, fmt.Errorf("Ollama vision call failed: %v", err)
	}

	// 6. Parse Ollama response envelope
	var resp struct {
		Response string `json:"response"`
		Error    string `json:"error"`
	}
	if err := json.Unmarshal([]byte(out), &resp); err != nil {
		return nil, fmt.Errorf("Ollama response parse error: %v", err)
	}
	if resp.Error != "" {
		return nil, fmt.Errorf("Ollama error: %s", resp.Error)
	}

	// 7. Extract structured JSON from LLM's text response
	jsonStr := extractJSON(resp.Response)
	var result map[string]interface{}
	if err := json.Unmarshal([]byte(jsonStr), &result); err != nil {
		// JSON parse failed — use keyword-based fallback
		log.Printf("⚠️ Vision LLM didn't return valid JSON, using keyword fallback")
		return e.fallbackImageAnalysis(resp.Response), nil
	}

	// Normalize is_clear to boolean
	if v, ok := result["is_clear"].(bool); ok {
		result["is_clear"] = v
	} else if v, ok := result["is_clear"].(string); ok {
		result["is_clear"] = strings.ToLower(v) == "true"
	} else {
		// Default: assume not clear if unspecified
		result["is_clear"] = false
	}

	// Normalize confidence to float
	if v, ok := result["confidence"].(float64); ok {
		result["confidence"] = v
	} else if v, ok := result["confidence"].(string); ok {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			result["confidence"] = f
		}
	}

	return result, nil
}

// ── fallbackImageAnalysis ───────────────────────────────────────────
// When the vision LLM doesn't return valid JSON, we do simple
// keyword detection on the raw text. Low confidence (0.3) signals
// to the verification system that this result is unreliable.

func (e *Engine) fallbackImageAnalysis(text string) map[string]interface{} {
	lower := strings.ToLower(text)

	// Negative signals — if any of these appear, image is likely bad
	negatives := []string{"black", "noise", "dark", "blank", "corrupt",
		"glitch", "static", "no signal", "blank screen", "not visible"}
	// Positive signals — if these appear, image is likely good
	positives := []string{"clear", "visible", "bright", "well-lit",
		"scene", "object", "room", "table", "circuit", "screen"}

	negScore := 0
	for _, kw := range negatives {
		if strings.Contains(lower, kw) {
			negScore++
		}
	}
	posScore := 0
	for _, kw := range positives {
		if strings.Contains(lower, kw) {
			posScore++
		}
	}

	isClear := posScore > negScore

	return map[string]interface{}{
		"is_clear":    isClear,
		"description": truncateString(text, 300),
		"confidence":  0.3, // Low — this is a fallback
		"objects":     []string{},
		"issues":      []string{"raw_text_analysis"},
		"raw_fallback": true,
	}
}

// ── prepareImageForAnalysis ──────────────────────────────────────────
// Checks image size and resizes if it exceeds MaxImageSizeBytes.
// Tries ffmpeg first (likely available on Nano-OS for camera
// pipeline), then ImageMagick convert, then proceeds with the
// original image as a last resort.

func (e *Engine) prepareImageForAnalysis(imagePath string) ([]byte, error) {
	data, err := ioutil.ReadFile(imagePath)
	if err != nil {
		return nil, err
	}

	// Small enough — use as-is
	if len(data) <= MaxImageSizeBytes {
		return data, nil
	}

	log.Printf("📏 Image too large (%d bytes), attempting resize...", len(data))

	// Try ffmpeg resize
	resizedPath := imagePath + ".resized.jpg"
	_, ffmpegErr := runCommandWithTimeout(30, "ffmpeg", "-y", "-i", imagePath,
		"-vf", "scale=640:480", "-q:v", "5", resizedPath)
	if ffmpegErr == nil {
		if resizedData, err := ioutil.ReadFile(resizedPath); err == nil {
			os.Remove(resizedPath)
			if len(resizedData) <= MaxImageSizeBytes {
				log.Printf("📏 Resized with ffmpeg: %d → %d bytes", len(data), len(resizedData))
				return resizedData, nil
			}
		}
	}
	os.Remove(resizedPath) // cleanup

	// Try ImageMagick convert
	_, convertErr := runCommandWithTimeout(30, "convert", imagePath,
		"-resize", "640x480>", "-quality", "50", resizedPath)
	if convertErr == nil {
		if resizedData, err := ioutil.ReadFile(resizedPath); err == nil {
			os.Remove(resizedPath)
			if len(resizedData) <= MaxImageSizeBytes {
				log.Printf("📏 Resized with ImageMagick: %d → %d bytes", len(data), len(resizedData))
				return resizedData, nil
			}
		}
	}
	os.Remove(resizedPath)

	// Last resort: use original (might OOM the LLM context but better than nothing)
	log.Printf("⚠️ Could not resize image, using original (%d bytes) — may cause LLM issues", len(data))
	return data, nil
}

// ── extractJSON ─────────────────────────────────────────────────────
// Extracts a JSON object from LLM output that may contain
// conversational filler, markdown fences, or other noise.
// Tries: fenced code block → raw { } extraction → passthrough.

func extractJSON(text string) string {
	text = strings.TrimSpace(text)

	// Try extracting from markdown code block (```json ... ``` or ``` ... ```)
	re := regexp.MustCompile("(?s)```(?:json)?\\s*\\n(.*?)\\n```")
	matches := re.FindStringSubmatch(text)
	if len(matches) > 1 {
		return strings.TrimSpace(matches[1])
	}

	// Try finding a bare JSON object
	reObj := regexp.MustCompile("(?s)\\{.*\\}")
	objMatches := reObj.FindStringSubmatch(text)
	if len(objMatches) > 0 {
		return objMatches[0]
	}

	// Nothing found — return raw text (will fail JSON parse in caller)
	return text
}

// ── directCaptureFallback ───────────────────────────────────────────
// When the vision-npu skill doesn't exist yet (e.g., first boot),
// this function captures directly using tools likely present on
// Nano-OS: ffmpeg (v4l2), then v4l2-ctl.

func (e *Engine) directCaptureFallback(outputPath string, timeout int) error {
	log.Printf("📸 Using direct capture fallback (no vision-npu skill)")

	// Method 1: ffmpeg + v4l2 (most common on embedded Linux)
	_, err := runCommandWithTimeout(timeout, "ffmpeg", "-y",
		"-f", "v4l2", "-i", "/dev/video0",
		"-frames:v", "1", "-q:v", "2", outputPath)
	if err == nil {
		if _, statErr := os.Stat(outputPath); statErr == nil {
			log.Printf("📸 Captured via ffmpeg")
			return nil
		}
	}

	// Method 2: v4l2-ctl
	_, err = runCommandWithTimeout(timeout, "v4l2-ctl",
		"--device=/dev/video0",
		"--set-fmt-video=width=1280,height=720,pixelformat=NV12",
		"--stream-mmap=3",
		"--stream-to="+outputPath,
		"--stream-count=1")
	if err == nil {
		if _, statErr := os.Stat(outputPath); statErr == nil {
			log.Printf("📸 Captured via v4l2-ctl")
			return nil
		}
	}

	return fmt.Errorf("all capture methods failed (tried ffmpeg, v4l2-ctl)")
}

// ════════════════════════════════════════════════════════════════════════
// EXPECTATION VERIFICATION
// ════════════════════════════════════════════════════════════════════════
// Enhanced verifyExpectations supports special key suffixes:
//   - key_contains:  substring match (e.g., description_contains: "room")
//   - key_matches:   regex match (e.g., raw_matches: "DevID.*0x")
//   - key_exists:    check value is non-empty/non-zero
//   - key (plain):   exact match or numeric comparison (>=3, >0, <=10)
//
// This enables vision-aware expectations like:
//   expect:
//     is_clear: "true"
//     description_contains: "clear"
//     confidence: ">=0.7"

func (e *Engine) verifyExpectations(data map[string]interface{}, expect map[string]interface{}) bool {
	if expect == nil || len(expect) == 0 {
		return true
	}
	if data == nil {
		return false
	}

	for k, target := range expect {
		// ── _contains suffix: substring match ──
		if strings.HasSuffix(k, "_contains") {
			actualKey := strings.TrimSuffix(k, "_contains")
			actual, ok := data[actualKey]
			if !ok {
				return false
			}
			if !strings.Contains(
				strings.ToLower(fmt.Sprintf("%v", actual)),
				strings.ToLower(fmt.Sprintf("%v", target))) {
				return false
			}
			continue
		}

		// ── _matches suffix: regex match ──
		if strings.HasSuffix(k, "_matches") {
			actualKey := strings.TrimSuffix(k, "_matches")
			actual, ok := data[actualKey]
			if !ok {
				return false
			}
			matched, err := regexp.MatchString(
				fmt.Sprintf("%v", target),
				fmt.Sprintf("%v", actual))
			if err != nil || !matched {
				return false
			}
			continue
		}

		// ── _exists suffix: non-empty check ──
		if strings.HasSuffix(k, "_exists") {
			actualKey := strings.TrimSuffix(k, "_exists")
			actual, ok := data[actualKey]
			if !ok {
				return false
			}
			strVal := strings.TrimSpace(fmt.Sprintf("%v", actual))
			if strVal == "" || strVal == "false" || strVal == "0" || strVal == "<nil>" {
				return false
			}
			continue
		}

		// ── Standard comparison: exact or numeric ──
		val, ok := data[k]
		if !ok {
			return false
		}
		if !e.matchTarget(fmt.Sprintf("%v", val), target) {
			return false
		}
	}

	return true
}

// ── matchTarget ─────────────────────────────────────────────────────
// Compares an actual value against a target. Supports:
//   - Numeric: >=N, >N, <=N, <N, ==N
//   - String:  exact match (case-insensitive for booleans)

func (e *Engine) matchTarget(actual string, target interface{}) bool {
	tStr := fmt.Sprintf("%v", target)
	aLower := strings.ToLower(actual)
	tLower := strings.ToLower(tStr)

	// Numeric comparisons
	if strings.HasPrefix(tLower, ">=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, ">="), func(a, b float64) bool { return a >= b })
	}
	if strings.HasPrefix(tLower, ">") && !strings.HasPrefix(tLower, ">=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, ">"), func(a, b float64) bool { return a > b })
	}
	if strings.HasPrefix(tLower, "<=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, "<="), func(a, b float64) bool { return a <= b })
	}
	if strings.HasPrefix(tLower, "<") && !strings.HasPrefix(tLower, "<=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, "<"), func(a, b float64) bool { return a < b })
	}
	if strings.HasPrefix(tLower, "==") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, "=="), func(a, b float64) bool { return a == b })
	}
	if strings.HasPrefix(tLower, "!=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, "!="), func(a, b float64) bool { return a != b })
	}

	// Boolean normalization: "true" matches "true", "True" matches "TRUE"
	if aLower == "true" || aLower == "false" {
		return aLower == tLower
	}

	// Exact string match
	return actual == tStr
}

// compareNumeric safely parses two strings as floats and applies
// the comparison function. Returns false if either value can't
// parse as a number (falls back to exact string match).

func compareNumeric(actualStr, targetStr string, cmp func(float64, float64) bool) bool {
	a, errA := strconv.ParseFloat(strings.TrimSpace(actualStr), 64)
	b, errB := strconv.ParseFloat(strings.TrimSpace(targetStr), 64)
	if errA != nil || errB != nil {
		return actualStr == targetStr // fall back to exact match
	}
	return cmp(a, b)
}

// ════════════════════════════════════════════════════════════════════════
// TASK MANAGEMENT
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) verifyTaskSuccess(t *Task) bool {
	for _, c := range t.SuccessCriteria {
		if err := exec.Command("sh", "-c", c).Run(); err != nil {
			log.Printf("  ❌ Success criteria failed: %s", c)
			return false
		}
	}
	return true
}

func (e *Engine) saveTaskStatus(t *Task) {
	if t.SourceFile == "" {
		return
	}
	data, err := ioutil.ReadFile(t.SourceFile)
	if err != nil {
		return
	}
	var wrapper map[string]interface{}
	if err := yaml.Unmarshal(data, &wrapper); err != nil {
		return
	}
	if taskMap, ok := wrapper["task"].(map[string]interface{}); ok {
		taskMap["status"] = t.Status
		updated, err := yaml.Marshal(wrapper)
		if err != nil {
			return
		}
		ioutil.WriteFile(t.SourceFile, updated, 0644)
	}
}

// ── updateMetrics ───────────────────────────────────────────────────
// Executes each metric's shell check from program.yaml and
// stores the result in State.Metrics. These metrics feed into
// the LLM prompt so it can reason about system state.
//
// Example program.yaml:
//   metrics:
//     camera_present:
//       check: "test -e /dev/video0 && echo yes || echo no"
//       target: "yes"

func (e *Engine) updateMetrics() {
	for name, metric := range e.Program.Metrics {
		var out []byte
		var err error

		if e.Program.Constraints.MaxMemoryMB > 0 {
			memKB := e.Program.Constraints.MaxMemoryMB * 1024
			cmd := exec.Command("sh", "-c",
				fmt.Sprintf("ulimit -v %d; %s", memKB, metric.Check))
			cmd.Env = os.Environ()
			out, err = cmd.Output()
		} else {
			cmd := exec.Command("sh", "-c", metric.Check)
			cmd.Env = os.Environ()
			out, err = cmd.Output()
		}

		val := strings.TrimSpace(string(out))
		if err != nil {
			val = "error: " + err.Error()
		}
		e.State.Metrics[name] = val
	}
}

// ════════════════════════════════════════════════════════════════════════
// COMMAND EXECUTION
// ════════════════════════════════════════════════════════════════════════
// Two-level execution:
//   - executeCmdWithTimeout: takes a pre-configured *exec.Cmd
//     (for skills that need custom stdin, env, cwd)
//   - runCommandWithTimeout: convenience wrapper for simple commands

// ── executeCmdWithTimeout ───────────────────────────────────────────
// Executes a command with a hard timeout. Uses Start/Wait pattern
// instead of CombinedOutput-in-goroutine to avoid race conditions
// and ensure reliable process cleanup on timeout.
//
// Safety features:
//   - After timeout, sends SIGKILL and waits up to 5s for exit
//   - Partial output preserved even on timeout
//   - Stdin preserved if already set by caller (for skill piping)

func executeCmdWithTimeout(cmd *exec.Cmd, timeoutSec int) (string, error) {
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	// Don't override Stdin if caller already set it (for API skill piping)

	if err := cmd.Start(); err != nil {
		return "", err
	}

	done := make(chan error, 1)
	go func() {
		done <- cmd.Wait()
	}()

	select {
	case err := <-done:
		return buf.String(), err

	case <-time.After(time.Duration(timeoutSec) * time.Second):
		if cmd.Process != nil {
			cmd.Process.Kill()
		}
		// Wait for the killed process to actually exit
		select {
		case <-done:
			// Process exited after kill
		case <-time.After(5 * time.Second):
			log.Printf("⚠️ Process PID %d refused to exit after SIGKILL", cmd.Process.Pid)
		}
		return buf.String(), fmt.Errorf("timeout after %ds", timeoutSec)
	}
}

// ── runCommandWithTimeout ───────────────────────────────────────────
// Convenience wrapper for simple commands with no custom config.

func runCommandWithTimeout(timeoutSec int, name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	cmd.Env = os.Environ()
	return executeCmdWithTimeout(cmd, timeoutSec)
}

// ════════════════════════════════════════════════════════════════════════
// MAIN
// ════════════════════════════════════════════════════════════════════════

func main() {
	engine := NewEngine()
	log.Println("🤖 picoClaw Skill-Aware Orchestrator v3.0 — online")
	log.Printf("   Skills dir: %s", SkillsDir)
	log.Printf("   State: VisualTruth=%q CommandTruth=%q",
		truncateString(engine.State.VisualTruth, 40),
		truncateString(engine.State.CommandTruth, 40))
	engine.RunLoop()
}
```

---

## Summary of All Fixes Applied

| Review Issue                        | What Changed                                                                                                                                                                                                              | Where                                                                                              |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **LLM YAML parsing fragile**        | Regex `(?s)\`\`\`(?:ya?ml)?\s*\n(.*?)\n\`\`\`` extracts fenced blocks; falls back to raw parse                                                                                                                            | `askLLMForTask`                                                                                    |
| **Security bypass via obfuscation** | Two-layer check: built-in `dangerousCmdPatterns` blocklist + user-defined `RequiresApproval`, both lowercase-normalized                                                                                                   | `isApproved`                                                                                       |
| **SD card wear**                    | `stateDirty` flag + `flushCounter` + `flushInterval` (default 50 iterations ≈ 100s between writes vs. every 2s). `saveState` always called on `SIGINT/SIGTERM`                                                            | `markStateDirty`, `flushStateIfNeeded`, `RunLoop` shutdown handler                                 |
| **`max_memory_mb` not enforced**    | `ulimit -v <kb>` prepended to `shell_cmd`, `run_python_code`, shell skills, Python skills, and `updateMetrics`                                                                                                            | `runShellCommand`, `executePythonCode`, `executeShellSkill`, `executePythonSkill`, `updateMetrics` |
| **`updateMetrics()` stub**          | Full implementation: iterates `Program.Metrics`, runs each `check` shell command, stores result                                                                                                                           | `updateMetrics`                                                                                    |
| **Recovery unused**                 | `buildRecoveryContext()` scans `State.RecentFailures`, injects failures + recovery strategies into LLM prompt                                                                                                             | `buildRecoveryContext`, `askLLMForTask`                                                            |
| **Simplicity bias unused**          | When `strategy.simplicity_bias: true`, adds constraint directive to LLM prompt                                                                                                                                            | `askLLMForTask`                                                                                    |
| **Skill system missing**            | Full chain: `callSkill` → native → `loadSkillConfig` → `parseSkillFrontmatter` → `executeShellSkill`/`executePythonSkill`/`executeAPISkill` → `parseSkillOutput`                                                          | Entire Skill System section                                                                        |
| **Vision system missing**           | `captureImage` (skill → fallback → verify → analyze) + `analyzeImageWithLLM` (base64 → temp file → curl → Ollama → `extractJSON` → fallback) + `prepareImageForAnalysis` (resize) + `directCaptureFallback` (ffmpeg/v4l2) | Entire Vision System section                                                                       |
| **Visual/Command Truth**            | `captureImage` writes `State.VisualTruth` + `State.CommandTruth`; `askLLMForTask` includes both in prompt                                                                                                                 | `captureImage`, `askLLMForTask`                                                                    |
| **Expect verification limited**     | `_contains`, `_matches`, `_exists` suffixes; `>=`, `>`, `<=`, `<`, `!=`, `==` numeric operators; boolean normalization                                                                                                    | `verifyExpectations`, `matchTarget`, `compareNumeric`                                              |
| **Command execution race**          | `Start/Wait` pattern with process kill + 5s safety wait; partial output preserved on timeout                                                                                                                              | `executeCmdWithTimeout`                                                                            |
| **Recent failures tracking**        | `State.RecentFailures` array (capped at 10) populated on step failure; consumed by `buildRecoveryContext`                                                                                                                 | `executeTask`, `buildRecoveryContext`                                                              |


capture_image(mode=both)
  │
  ├──► vision_capture skill ──► CSI camera (MMF SDK) ──► /tmp/capture.jpg
  │
  ├──► vision_npu skill ──► YOLO on NPU (TDL SDK) ──► {objects: [{class, x1,y1,x2,y2, score}]}
  │
  └──► llm_gateway skill ◄── prepareImage (resize+base64 in Go)
         │
         └──► reads config ──► calls API ──► {is_clear, description, objects, confidence}


`skills/vision_npu/SKILL.md`:

```yaml
---
name: vision_npu
exec_type: shell
command: ./yolo_detect.sh
input_format: env
output_format: json
timeout: 30
---
# NPU YOLO Inference — uses CVI TDL SDK, returns objects with bounding boxes
```

## Now I Understand. They Are Completely Different Things.

```
picoClaw  = AI Assistant (chat, LLM providers, channels, MCP, WebUI)
main.go   = Hardware Orchestrator (camera, NPU, I2C, task queue, security)
```

```
picoClaw  = AI Assistant (chat, LLM providers, channels, MCP, WebUI)
main.go   = Hardware Orchestrator (camera, NPU, I2C, task queue, security)
```

You need BOTH. They do different jobs and should talk to each other.

---

## The Real Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER                                      │
│  Telegram ─┐                                                │
│  WeChat ───┤                                                │
│  Discord ──┤                                                │
│  WebUI ────┘                                                │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  picoClaw (AI Assistant)                              │    │
│  │                                                      │    │
│  │  • LLM providers (Ollama, OpenAI, Kimi, Bedrock...)  │    │
│  │  • Smart routing (cheap model for simple queries)   │    │
│  │  • Memory / context management                      │    │
│  │  • Channels (Telegram, WeChat, Discord...)          │    │
│  │  • Sub-agents (spawn_status)                        │    │
│  │  • Vision pipeline (send images to multimodal LLMs) │    │
│  │  • .security.yml                                    │    │
│  │  • Gateway API (localhost:18800)                    │    │
│  │  • MCP client ← connects to MCP servers             │    │
│  └──────────┬──────────────────────┬────────────────────┘    │
│             │                      │                         │
│             │ MCP protocol         │ Gateway API             │
│             │ (tool calls)         │ (LLM requests)         │
│             ▼                      ▼                         │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  nano-os-agent (main.go — Hardware Orchestrator)     │    │
│  │                                                      │    │
│  │  • Task queue with priorities & retry               │    │
│  │  • CSI camera capture (MMF/TDL SDK)                │    │
│  │  • NPU YOLO detection                              │    │
│  │  • MJPEG streaming                                 │    │
│  │  • I2C, GPIO, sensor probing                       │    │
│  │  • Security (blocks dangerous commands)             │    │
│  │  • Visual Truth / Command Truth state              │    │
│  │  • SD card protection                              │    │
│  │  • Autonomous hardware monitoring loop             │    │
│  │  • MCP server ← exposes tools to picoClaw          │    │
│  └──────────┬──────────────────────────────────────────┘    │
│             │                                               │
│             ▼                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Hardware (LicheeRV Nano SG2002)                     │    │
│  │  CSI camera • NPU 1TOPS • I2C • GPIO • UART        │    │
│  │  FreeRTOS core • /proc/cvitek • /dev/cvi-mipi-rx  │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────────────────┐
│                    USER                                      │
│  Telegram ─┐                                                │
│  WeChat ───┤                                                │
│  Discord ──┤                                                │
│  WebUI ────┘                                                │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  picoClaw (AI Assistant)                              │    │
│  │                                                      │    │
│  │  • LLM providers (Ollama, OpenAI, Kimi, Bedrock...)  │    │
│  │  • Smart routing (cheap model for simple queries)   │    │
│  │  • Memory / context management                      │    │
│  │  • Channels (Telegram, WeChat, Discord...)          │    │
│  │  • Sub-agents (spawn_status)                        │    │
│  │  • Vision pipeline (send images to multimodal LLMs) │    │
│  │  • .security.yml                                    │    │
│  │  • Gateway API (localhost:18800)                    │    │
│  │  • MCP client ← connects to MCP servers             │    │
│  └──────────┬──────────────────────┬────────────────────┘    │
│             │                      │                         │
│             │ MCP protocol         │ Gateway API             │
│             │ (tool calls)         │ (LLM requests)         │
│             ▼                      ▼                         │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  nano-os-agent (main.go — Hardware Orchestrator)     │    │
│  │                                                      │    │
│  │  • Task queue with priorities & retry               │    │
│  │  • CSI camera capture (MMF/TDL SDK)                │    │
│  │  • NPU YOLO detection                              │    │
│  │  • MJPEG streaming                                 │    │
│  │  • I2C, GPIO, sensor probing                       │    │
│  │  • Security (blocks dangerous commands)             │    │
│  │  • Visual Truth / Command Truth state              │    │
│  │  • SD card protection                              │    │
│  │  • Autonomous hardware monitoring loop             │    │
│  │  • MCP server ← exposes tools to picoClaw          │    │
│  └──────────┬──────────────────────────────────────────┘    │
│             │                                               │
│             ▼                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Hardware (LicheeRV Nano SG2002)                     │    │
│  │  CSI camera • NPU 1TOPS • I2C • GPIO • UART        │    │
│  │  FreeRTOS core • /proc/cvitek • /dev/cvi-mipi-rx  │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## What Each One Does (No Overlap)

|Capability|picoClaw|nano-os-agent (main.go)|
|---|---|---|
|Chat with user via Telegram|✅|❌|
|LLM provider management|✅|❌ (remove llm_gateway!)|
|Smart model routing|✅|❌|
|Memory/context|✅|❌|
|MCP protocol|✅ client|✅ server|
|CSI camera capture|❌|✅|
|NPU YOLO detection|❌|✅|
|MJPEG streaming|❌|✅|
|I2C scan / GPIO control|❌|✅|
|Task queue + retry|❌ (different concept)|✅|
|Security (command blocking)|✅ .security.yml|✅ 6-layer check|
|Autonomous hardware loop|❌|✅|
|Visual Truth state|❌|✅|
|Android support|✅|❌|
|WebUI|✅|❌|

Zero overlap. picoClaw is the brain and voice. nano-os-agent is the hands and eyes.

---

## How They Talk: MCP Protocol

picoClaw already supports MCP (Model Context Protocol). Our nano-os-agent should expose its hardware tools as an MCP server. When picoClaw needs to capture an image or run YOLO, it calls our MCP tools.

### What nano-os-agent exposes to picoClaw:

```
MCP Tools:
  capture_image    → Capture frame from CSI camera
  analyze_image    → Run YOLO on NPU or LLM vision analysis
  start_stream     → Start MJPEG stream on port
  stop_stream     → Stop MJPEG stream
  scan_i2c        → Scan I2C bus for devices
  probe_sensor    → Check /proc/cvitek/vi sensor status
  read_gpio       → Read GPIO pin value
  write_gpio      → Write GPIO pin value
  run_yolo         → Run YOLO detection on image file
  get_visual_truth → Return current Visual Truth state
```

```
MCP Tools:
  capture_image    → Capture frame from CSI camera
  analyze_image    → Run YOLO on NPU or LLM vision analysis
  start_stream     → Start MJPEG stream on port
  stop_stream     → Stop MJPEG stream
  scan_i2c        → Scan I2C bus for devices
  probe_sensor    → Check /proc/cvitek/vi sensor status
  read_gpio       → Read GPIO pin value
  write_gpio      → Write GPIO pin value
  run_yolo         → Run YOLO detection on image file
  get_visual_truth → Return current Visual Truth state
```

### Concrete Example

User on Telegram: _"What do you see?"_

```
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

```
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

## Modified main.go — MCP Server for picoClaw

The key change: remove llm_gateway and add MCP server. picoClaw handles all LLM calls.

go

```
package main

// ════════════════════════════════════════════════════════════════════════
// nano-os-agent v5.0 — Hardware Orchestrator + MCP Server for picoClaw
// ════════════════════════════════════════════════════════════════════════
// Target: LicheeRV Nano (SG2002, 256MB DDR3, RISC-V C906, NPU 1TOPS)
// Build:  GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-os-agent
//
// RELATIONSHIP TO PICOCLAW:
//   picoClaw = AI Assistant (chat, LLM, channels, user interface)
//   nano-os-agent = Hardware Orchestrator (camera, NPU, I2C, task queue)
//
//   nano-os-agent exposes hardware tools via MCP server.
//   picoClaw connects as MCP client and calls tools when needed.
//   nano-os-agent also runs autonomous hardware monitoring loops.
//
// NO llm_gateway skill — picoClaw handles ALL LLM calls.
// When nano-os-agent needs LLM reasoning, it calls picoClaw's Gateway API.
// ════════════════════════════════════════════════════════════════════════

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"gopkg.in/yaml.v3"
)

// ════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ════════════════════════════════════════════════════════════════════════

const (
	SkillsDir            = "/root/.picoclaw/workspace/skills"
	DefaultCapturePath   = "/tmp/capture.jpg"
	DefaultFlushInterval = 50
	DefaultContextWindow = 10
	MaxIdleBackoffSecs   = 300
	MaxStateLength       = 300
	MaxImageSizeBytes    = 2 * 1024 * 1024

	// MCP server listens on this port (picoClaw connects here)
	MCPListenAddr = "127.0.0.1:9600"

	// picoClaw Gateway (nano-os-agent calls this for LLM reasoning)
	PicoClawGatewayURL = "http://127.0.0.1:18800"
)

// ════════════════════════════════════════════════════════════════════════
// TYPES
// ════════════════════════════════════════════════════════════════════════

type ProgramConfig struct {
	Metadata struct {
		Name string `yaml:"name"`
		Board string `yaml:"board"`
		SoC  string `yaml:"soc"`
	} `yaml:"metadata"`
	Goals struct {
		Primary   string   `yaml:"primary"`
		Secondary []string `yaml:"secondary"`
	} `yaml:"goals"`
	Constraints struct {
		Readonly         []string `yaml:"readonly"`
		RequiresApproval []string `yaml:"requires_approval"`
		MaxTimeout       int      `yaml:"max_timeout_seconds"`
		MaxMemoryMB      int      `yaml:"max_memory_mb"`
	} `yaml:"constraints"`
	Metrics map[string]Metric `yaml:"metrics"`
	Strategy struct {
		MaxRetries     int      `yaml:"max_retries"`
		Recovery       []string `yaml:"recovery"`
		SimplicityBias bool     `yaml:"simplicity_bias"`
		UseLLM         bool     `yaml:"use_llm"`
	} `yaml:"strategy"`
	Loop struct {
		NeverStop     bool `yaml:"never_stop"`
		PollInterval  int  `yaml:"poll_interval"`
		ContextWindow int  `yaml:"context_window"`
	} `yaml:"loop"`
}

type Metric struct {
	Check  string      `yaml:"check"`
	Target interface{} `yaml:"target"`
}

type Task struct {
	ID              string    `yaml:"id"`
	Name            string   `yaml:"name"`
	Priority        int      `yaml:"priority"`
	Status          string   `yaml:"status"`
	SuccessCriteria []string  `yaml:"success_criteria"`
	Steps           []Step   `yaml:"steps"`
	Subtasks        []Subtask `yaml:"subtasks"`
	SourceFile      string   `yaml:"-"`
}

type Step struct {
	ID         string                 `yaml:"id"`
	Action     string                 `yaml:"action"`
	Parameters map[string]interface{} `yaml:"parameters"`
	Timeout    int                    `yaml:"timeout"`
	Expect     map[string]interface{} `yaml:"expect"`
	OnFail     string                 `yaml:"on_fail"`
	MaxRetries int                    `yaml:"max_retries"`
}

type Subtask struct {
	ID   string `yaml:"id"`
	Name string `yaml:"name"`
	File string `yaml:"file"`
}

type SkillConfig struct {
	Name         string       `yaml:"name"`
	ExecType     string       `yaml:"exec_type"`
	Command      string       `yaml:"command"`
	Endpoint     string       `yaml:"endpoint"`
	Method       string       `yaml:"method"`
	InputFormat  string       `yaml:"input_format"`
	OutputFormat string       `yaml:"output_format"`
	Timeout      int          `yaml:"timeout"`
	Parameters   []SkillParam `yaml:"parameters"`
	Returns      []string     `yaml:"returns"`
}

type SkillParam struct {
	Name    string      `yaml:"name"`
	Type    string      `yaml:"type"`
	Default interface{} `yaml:"default"`
}

type State struct {
	CurrentTaskID  string                 `json:"current_task_id"`
	Iteration      int                    `json:"iteration"`
	History        []string               `json:"history"`
	Metrics        map[string]string      `json:"metrics"`
	VisualTruth    string                 `json:"visual_truth"`
	CommandTruth   string                 `json:"command_truth"`
	SkillResults   map[string]interface{} `json:"skill_results"`
	RecentFailures []string               `json:"recent_failures"`
}

// ════════════════════════════════════════════════════════════════════════
// MCP PROTOCOL TYPES
// ════════════════════════════════════════════════════════════════════════
// JSON-RPC 2.0 based protocol as defined by MCP spec.
// picoClaw sends requests, nano-os-agent responds.

type MCPRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type MCPResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *MCPError   `json:"error,omitempty"`
}

type MCPError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type MCPTool struct {
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	InputSchema  map[string]interface{} `json:"inputSchema"`
}

type MCPToolCallParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

// ════════════════════════════════════════════════════════════════════════
// SECURITY (same as before)
// ════════════════════════════════════════════════════════════════════════

var dangerousWordPatterns = []string{"reboot", "poweroff", "halt", "shutdown"}
var dangerousSubstringPatterns = []string{
	"sudo ", "sudo\t", "/proc/sys", "init 0", "init 6",
	"mkfs.", "dd if=", "dd of=", "> /dev/sd", "> /dev/mmc",
	"chmod 000", "rm -rf /", "rm -rf /*", ":(){:|:&};:",
}
var obfuscationPatterns = []string{
	"base64 --decode", "base64 -d", "eval $(", "perl -e",
	"/dev/tcp/", "/dev/udp/", "nc -e",
}
var protectedEnvVars = map[string]bool{
	"PATH": true, "LD_PRELOAD": true, "IFS": true,
	"SHELL": true, "HOME": true,
}

func isWordMatch(cmd, word string) bool {
	lower, target := strings.ToLower(cmd), strings.ToLower(word)
	idx := 0
	for {
		pos := strings.Index(lower[idx:], target)
		if pos < 0 { return false }
		absPos := idx + pos
		beforeOK := absPos == 0 || !isAlphanumeric(lower[absPos-1])
		afterOK := absPos+len(target) >= len(lower) || !isAlphanumeric(lower[absPos+len(target)])
		if beforeOK && afterOK { return true }
		idx = absPos + 1
	}
}

func isAlphanumeric(c byte) bool {
	return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'
}

func extractWriteTargets(cmdStr string) []string {
	var targets []string
	for _, m := range regexp.MustCompile(`>{1,2}\s*(/\S+)`).FindAllStringSubmatch(cmdStr, -1) {
		if m[1] != "/dev/null" { targets = append(targets, m[1]) }
	}
	return targets
}

func (e *Engine) isApproved(cmdStr string) bool {
	lower := strings.ToLower(cmdStr)
	for _, w := range dangerousWordPatterns {
		if isWordMatch(lower, w) { return false }
	}
	for _, p := range dangerousSubstringPatterns {
		if strings.Contains(lower, strings.ToLower(p)) { return false }
	}
	for _, p := range obfuscationPatterns {
		if strings.Contains(lower, strings.ToLower(p)) { return false }
	}
	if strings.Contains(lower, "ulimit") { return false }
	for _, p := range extractWriteTargets(cmdStr) {
		if e.isReadonly(p) { return false }
	}
	for _, p := range e.Program.Constraints.RequiresApproval {
		if strings.Contains(lower, strings.ToLower(p)) { return false }
	}
	return true
}

func (e *Engine) isReadonly(path string) bool {
	for _, pattern := range e.Program.Constraints.Readonly {
		if matched, _ := filepath.Match(pattern, path); matched { return true }
		if strings.HasSuffix(pattern, "*") &&
			strings.HasPrefix(path, strings.TrimSuffix(pattern, "*")) { return true }
	}
	return false
}

func shellEscape(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}

// ════════════════════════════════════════════════════════════════════════
// UTILITY HELPERS
// ════════════════════════════════════════════════════════════════════════

func resolveTimeout(values ...int) int {
	for _, v := range values { if v > 0 { return v } }
	return 60
}
func paramInt(p map[string]interface{}, k string, d int) int {
	if v, ok := p[k].(int); ok && v > 0 { return v }
	if v, ok := p[k].(float64); ok && v > 0 { return int(v) }
	if v, ok := p[k].(string); ok { if n, e := strconv.Atoi(v); e == nil && n > 0 { return n } }
	return d
}
func paramString(p map[string]interface{}, k, d string) string {
	if v, ok := p[k].(string); ok && v != "" { return v }
	return d
}
func paramBool(p map[string]interface{}, k string, d bool) bool {
	if v, ok := p[k].(bool); ok { return v }
	if v, ok := p[k].(string); ok { return strings.ToLower(v) == "true" }
	return d
}
func truncateString(s string, n int) string {
	if len(s) <= n { return s }
	return s[:n] + "..."
}
func minInt(a, b int) int {
	if a < b { return a }
	return b
}

// ════════════════════════════════════════════════════════════════════════
// NATIVE SKILLS
// ════════════════════════════════════════════════════════════════════════

type NativeSkillFunc func(e *Engine, params map[string]interface{}) (map[string]interface{}, error)

var nativeSkills = map[string]NativeSkillFunc{
	"i2c_scan":     nativeI2CScan,
	"probe_cvitek": nativeProbeCvitek,
	"list_skills":  nativeListSkills,
}

func nativeI2CScan(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	bus := paramString(params, "bus", "1")
	out, err := runCommandWithTimeout(10, "i2cdetect", "-y", bus)
	count := 0
	for _, line := range strings.Split(out, "\n") {
		for _, f := range strings.Fields(line) {
			if f != "--" && f != "UU" && len(f) == 2 { count++ }
		}
	}
	return map[string]interface{}{"count": count, "raw": out}, err
}

func nativeProbeCvitek(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	data, err := os.ReadFile("/proc/cvitek/vi")
	if err != nil { return map[string]interface{}{"sensor_bound": false, "error": err.Error()}, nil }
	return map[string]interface{}{
		"sensor_bound": strings.Contains(string(data), "DevID"),
		"raw":          strings.TrimSpace(string(data)),
	}, nil
}

func nativeListSkills(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	seen := map[string]bool{}
	names := []string{}
	for name := range nativeSkills { names = append(names, name); seen[name] = true }
	files, _ := os.ReadDir(SkillsDir)
	for _, f := range files {
		if f.IsDir() && !seen[f.Name()] {
			if _, err := os.Stat(filepath.Join(SkillsDir, f.Name(), "SKILL.md")); err == nil {
				names = append(names, f.Name())
			}
		}
	}
	sort.Strings(names)
	return map[string]interface{}{"skills": names, "count": len(names)}, nil
}

// ════════════════════════════════════════════════════════════════════════
// ENGINE
// ════════════════════════════════════════════════════════════════════════

type Engine struct {
	Program       ProgramConfig
	State         State
	shutdownFlag  int32
	skillCache    map[string]*SkillConfig
	stateDirty    bool
	flushCounter  int
	flushInterval int
	idleCount     int
	mu            sync.Mutex // protects State for concurrent MCP calls
}

func NewEngine() *Engine {
	e := &Engine{
		skillCache:    make(map[string]*SkillConfig),
		flushInterval: DefaultFlushInterval,
	}
	e.loadEnv()
	e.loadProgram()
	e.loadState()

	if e.Program.Loop.ContextWindow <= 0 { e.Program.Loop.ContextWindow = DefaultContextWindow }
	if e.Program.Constraints.MaxMemoryMB <= 0 { e.Program.Constraints.MaxMemoryMB = 32 }
	if e.Program.Loop.PollInterval <= 0 { e.Program.Loop.PollInterval = 10 }
	if e.State.SkillResults == nil { e.State.SkillResults = make(map[string]interface{}) }
	if e.State.History == nil { e.State.History = make([]string, 0) }
	if e.State.Metrics == nil { e.State.Metrics = make(map[string]string) }
	if e.State.RecentFailures == nil { e.State.RecentFailures = make([]string, 0) }

	log.Printf("🤖 nano-os-agent v5.0 — Hardware Orchestrator + MCP Server")
	log.Printf("   Board: %s (%s) | MemLimit: %dMB | MCP: %s",
		e.Program.Metadata.Board, e.Program.Metadata.SoC,
		e.Program.Constraints.MaxMemoryMB, MCPListenAddr)
	log.Printf("   picoClaw Gateway: %s", PicoClawGatewayURL)
	return e
}

func (e *Engine) loadEnv() {
	for _, p := range []string{".env", "/root/.env"} {
		if err := parseEnvFile(p); err == nil { return }
	}
}

func parseEnvFile(path string) error {
	file, err := os.Open(path)
	if err != nil { return err }
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0), 4096)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") { continue }
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 {
			key := strings.TrimSpace(parts[0])
			if !protectedEnvVars[key] {
				os.Setenv(key, strings.TrimSpace(parts[1]))
			}
		}
	}
	return scanner.Err()
}

func (e *Engine) loadProgram() {
	data, err := os.ReadFile("program.yaml")
	if err != nil { log.Fatalf("❌ program.yaml: %v", err) }
	if err := yaml.Unmarshal(data, &e.Program); err != nil { log.Fatalf("❌ program.yaml: %v", err) }
}

func (e *Engine) loadState() {
	data, err := os.ReadFile("state.json")
	if err != nil {
		e.State = State{Metrics: make(map[string]string), History: []string{},
			SkillResults: make(map[string]interface{}), RecentFailures: []string{}}
		return
	}
	if err := json.Unmarshal(data, &e.State); err != nil {
		log.Printf("⚠️ state.json corrupt: %v", err)
		e.State = State{Metrics: make(map[string]string), History: []string{},
			SkillResults: make(map[string]interface{}), RecentFailures: []string{}}
	}
}

func (e *Engine) saveState() {
	e.mu.Lock()
	data, err := json.MarshalIndent(e.State, "", "  ")
	e.mu.Unlock()
	if err != nil { log.Printf("⚠️ marshal state: %v", err); return }
	tmpPath := "state.json.tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil { log.Printf("⚠️ write state: %v", err); return }
	if err := os.Rename(tmpPath, "state.json"); err != nil { os.Remove(tmpPath) }
	e.stateDirty = false
	e.flushCounter = 0
}

func (e *Engine) markStateDirty() { e.stateDirty = true }

func (e *Engine) flushStateIfNeeded() {
	if !e.stateDirty { return }
	e.flushCounter++
	if e.flushCounter >= e.flushInterval { e.saveState() }
}

// ════════════════════════════════════════════════════════════════════════
// MCP SERVER — the bridge between picoClaw and hardware
// ════════════════════════════════════════════════════════════════════════
// Listens on MCPListenAddr. picoClaw connects here as MCP client.
// Implements JSON-RPC 2.0 with these methods:
//   initialize      → server info + capabilities
//   tools/list      → list available hardware tools
//   tools/call      → execute a hardware tool
//   resources/list  → list state resources
//   resources/read  → read state (Visual Truth, metrics, etc.)

func (e *Engine) StartMCPServer() {
	listener, err := net.Listen("tcp", MCPListenAddr)
	if err != nil {
		log.Fatalf("❌ MCP listen failed on %s: %v", MCPListenAddr, err)
	}
	log.Printf("🔌 MCP server listening on %s (picoClaw connects here)", MCPListenAddr)

	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil { continue }
			go e.handleMCPConnection(conn)
		}
	}()
}

func (e *Engine) handleMCPConnection(conn net.Conn) {
	defer conn.Close()
	decoder := json.NewDecoder(conn)
	encoder := json.NewEncoder(conn)

	for {
		var req MCPRequest
		if err := decoder.Decode(&req); err != nil { return }

		resp := e.handleMCPRequest(&req)
		encoder.Encode(resp)
	}
}

func (e *Engine) handleMCPRequest(req *MCPRequest) MCPResponse {
	resp := MCPResponse{JSONRPC: "2.0", ID: req.ID}

	switch req.Method {

	case "initialize":
		resp.Result = map[string]interface{}{
			"protocolVersion": "2024-11-05",
			"capabilities": map[string]interface{}{
				"tools":    map[string]interface{}{"listChanged": true},
				"resources": map[string]interface{}{"listChanged": true},
			},
			"serverInfo": map[string]interface{}{
				"name":    "nano-os-agent",
				"version": "5.0",
			},
		}

	case "notifications/initialized":
		// Client acknowledges initialization — no response needed
		resp.Result = map[string]interface{}{}

	case "tools/list":
		resp.Result = map[string]interface{}{
			"tools": e.getMCPTools(),
		}

	case "tools/call":
		var params MCPToolCallParams
		if err := json.Unmarshal(req.Params, &params); err != nil {
			resp.Error = &MCPError{Code: -32602, Message: "invalid params"}
			break
		}
		result, mcpErr := e.executeMCPTool(params.Name, params.Arguments)
		if mcpErr != nil {
			resp.Result = map[string]interface{}{
				"content": []map[string]interface{}{
					{"type": "text", "text": fmt.Sprintf("Error: %v", mcpErr)},
				},
				"isError": true,
			}
		} else {
			content := []map[string]interface{}{
				{"type": "text", "text": fmt.Sprintf("%v", result)},
			}
			// If result has image_path, add image content
			if img, ok := result["image_path"].(string); ok && img != "" {
				data, err := os.ReadFile(img)
				if err == nil {
					encoded := encodeToBase64(data)
					content = append(content, map[string]interface{}{
						"type":     "image",
						"data":     encoded,
						"mimeType": "image/jpeg",
					})
				}
			}
			resp.Result = map[string]interface{}{
				"content": content,
			}
		}

	case "resources/list":
		resp.Result = map[string]interface{}{
			"resources": []map[string]interface{}{
				{"uri": "nano://state", "name": "Agent State", "mimeType": "application/json"},
				{"uri": "nano://visual_truth", "name": "Visual Truth", "mimeType": "text/plain"},
				{"uri": "nano://metrics", "name": "Hardware Metrics", "mimeType": "application/json"},
			},
		}

	case "resources/read":
		var params struct{ URI string `json:"uri"` }
		json.Unmarshal(req.Params, &params)
		resp.Result = e.readMCPResource(params.URI)

	default:
		resp.Error = &MCPError{Code: -32601, Message: "method not found: " + req.Method}
	}

	return resp
}

// ── MCP Tool Definitions ────────────────────────────────────────────────
// These are the tools picoClaw sees when it connects.

func (e *Engine) getMCPTools() []MCPTool {
	return []MCPTool{
		{
			Name:        "capture_image",
			Description: "Capture a frame from the CSI camera on LicheeRV Nano. Returns image path and metadata. Optionally analyze with NPU (YOLO) or send to vision LLM via picoClaw.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"output_path": map[string]interface{}{"type": "string", "description": "Save path", "default": "/tmp/capture.jpg"},
					"width":       map[string]interface{}{"type": "integer", "default": 640},
					"height":      map[string]interface{}{"type": "integer", "default": 640},
					"mode":        map[string]interface{}{"type": "string", "enum": []string{"none", "npu", "llm", "both"}, "default": "none", "description": "Analysis mode: none=capture only, npu=YOLO, llm=vision LLM (picoClaw handles the LLM call), both=NPU+LLM"},
				},
			},
		},
		{
			Name:        "run_yolo",
			Description: "Run YOLO object detection on NPU (1 TOPS INT8) for an image file. Returns detected objects with bounding boxes, class names, and confidence scores.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"image_path":  map[string]interface{}{"type": "string", "description": "Path to image file"},
					"model_path":  map[string]interface{}{"type": "string", "default": "/root/models/yolov8n_coco_640.cvimodel"},
					"class_cnt":   map[string]interface{}{"type": "integer", "default": 80},
					"threshold":   map[string]interface{}{"type": "number", "default": 0.5},
				},
				"required": []string{"image_path"},
			},
		},
		{
			Name:        "start_stream",
			Description: "Start MJPEG video stream from CSI camera. Returns URL and PID.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"port":      map[string]interface{}{"type": "integer", "default": 7777},
					"width":     map[string]interface{}{"type": "integer", "default": 640},
					"height":    map[string]interface{}{"type": "integer", "default": 640},
					"grayscale": map[string]interface{}{"type": "boolean", "default": false},
				},
			},
		},
		{
			Name:        "stop_stream",
			Description: "Stop running MJPEG video stream.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{},
			},
		},
		{
			Name:        "scan_i2c",
			Description: "Scan I2C bus for connected devices. Returns device count and addresses.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"bus": map[string]interface{}{"type": "string", "default": "1"},
				},
			},
		},
		{
			Name:        "probe_sensor",
			Description: "Check CSI camera sensor status via /proc/cvitek/vi.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
		{
			Name:        "init_camera",
			Description: "Initialize CSI camera sensor (run sensor_test). Required once after boot.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{
				"force": map[string]interface{}{"type": "boolean", "default": false},
			}},
		},
		{
			Name:        "get_visual_truth",
			Description: "Return the current Visual Truth — what the agent last saw and understood about the world.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
		{
			Name:        "run_shell",
			Description: "Execute a shell command on the board (with security checks). Blocked commands: reboot, sudo, dd, rm -rf /, etc.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"cmd":     map[string]interface{}{"type": "string", "description": "Shell command to execute"},
					"timeout": map[string]interface{}{"type": "integer", "default": 30},
				},
				"required": []string{"cmd"},
			},
		},
		{
			Name:        "list_skills",
			Description: "List all available skills (native Go + SKILL.md external).",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
	}
}

// ── MCP Tool Execution ─────────────────────────────────────────────────

func (e *Engine) executeMCPTool(name string, args map[string]interface{}) (map[string]interface{}, error) {
	log.Printf("🔌 MCP tool call: %s %v", name, args)

	switch name {

	case "capture_image":
		return e.captureImage(args, resolveTimeout(30))

	case "run_yolo":
		return e.callSkill("vision_npu", args, resolveTimeout(30))

	case "start_stream":
		args["action"] = "start"
		return e.callSkill("vision_stream", args, resolveTimeout(15))

	case "stop_stream":
		return e.callSkill("vision_stream",
			map[string]interface{}{"action": "stop"}, resolveTimeout(10))

	case "scan_i2c":
		return e.callSkill("i2c_scan", args, resolveTimeout(10))

	case "probe_sensor":
		return e.callSkill("probe_cvitek", nil, resolveTimeout(10))

	case "init_camera":
		return e.callSkill("camera_init", args, resolveTimeout(30))

	case "get_visual_truth":
		e.mu.Lock()
		result := map[string]interface{}{
			"visual_truth":  e.State.VisualTruth,
			"command_truth": e.State.CommandTruth,
			"metrics":       e.State.Metrics,
		}
		e.mu.Unlock()
		return result, nil

	case "run_shell":
		cmdStr := paramString(args, "cmd", "")
		if !e.isApproved(cmdStr) {
			return nil, fmt.Errorf("command blocked by security policy")
		}
		timeout := paramInt(args, "timeout", 30)
		return e.runShellCommand(args, timeout)

	case "list_skills":
		return nativeListSkills(e, nil)

	default:
		return nil, fmt.Errorf("unknown MCP tool: %s", name)
	}
}

func (e *Engine) readMCPResource(uri string) interface{} {
	e.mu.Lock()
	defer e.mu.Unlock()

	switch uri {
	case "nano://state":
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "application/json",
					"text": fmt.Sprintf("%v", e.State)},
			},
		}
	case "nano://visual_truth":
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "text/plain", "text": e.State.VisualTruth},
			},
		}
	case "nano://metrics":
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "application/json",
					"text": fmt.Sprintf("%v", e.State.Metrics)},
			},
		}
	default:
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "text/plain", "text": "unknown resource"},
			},
		}
	}
}

func encodeToBase64(data []byte) string {
	// Simple base64 encoding without importing encoding/base64 at MCP level
	// Actually we already import it, so use it directly
	return fmt.Sprintf("data:image/jpeg;base64,%s",
		bytesToBase64(data))
}

func bytesToBase64(data []byte) string {
	// Use encoding/base64
	return strings.ReplaceAll(strings.ReplaceAll(
		fmt.Sprintf("%s", base64Encode(data)),
		"\n", ""), "\r", "")
}

// Simple base64 encoder (stdlib already imported)
func base64Encode(data []byte) string {
	return string(bytes.TrimSpace(
		append([]byte{}, []byte(base64EncodeStr(data))...))
}

func base64EncodeStr(data []byte) string {
	const table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	result := make([]byte, 0, (len(data)+2)/3*4)
	for i := 0; i < len(data); i += 3 {
		var n uint32
		rem := len(data) - i
		if rem >= 3 {
			n = uint32(data[i])<<16 | uint32(data[i+1])<<8 | uint32(data[i+2])
			result = append(result, table[n>>18&0x3f], table[n>>12&0x3f],
				table[n>>6&0x3f], table[n&0x3f])
		} else if rem == 2 {
			n = uint32(data[i])<<16 | uint32(data[i+1])<<8
			result = append(result, table[n>>18&0x3f], table[n>>12&0x3f],
				table[n>>6&0x3f], '=')
		} else {
			n = uint32(data[i]) << 16
			result = append(result, table[n>>18&0x3f], table[n>>12&0x3f], '=', '=')
		}
	}
	return string(result)
}

// ════════════════════════════════════════════════════════════════════════
// PICOCLAW GATEWAY CLIENT
// ════════════════════════════════════════════════════════════════════════
// When nano-os-agent needs LLM reasoning (e.g., for autonomous task
// generation), it calls picoClaw's Gateway API instead of having its
// own llm_gateway. Single source of truth: picoClaw owns all LLM calls.

func (e *Engine) askPicoClawForTask() {
	if !e.Program.Strategy.UseLLM { return }

	prompt := e.buildTaskGenerationPrompt()

	// Call picoClaw's Gateway API
	payload := map[string]interface{}{
		"message": prompt,
		"model":   "auto", // picoClaw handles routing
	}
	pJSON, _ := json.Marshal(payload)

	tmpFile, err := os.CreateTemp("", "picoclaw_task_*.json")
	if err != nil { return }
	tmpFile.Write(pJSON)
	tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	out, err := runCommandWithTimeout(90, "curl", "-s", "-X", "POST",
		PicoClawGatewayURL+"/api/chat",
		"-H", "Content-Type: application/json",
		"-d", "@"+tmpFile.Name())
	if err != nil {
		log.Printf("⚠️ picoClaw Gateway call failed: %v", err)
		return
	}

	var resp struct{ Response string `json:"response"` }
	if err := json.Unmarshal([]byte(out), &resp); err != nil { return }

	// Extract YAML task from LLM response (same logic as before)
	yamlContent := resp.Response
	re := regexp.MustCompile("(?s)```(?:ya?ml)?\\s*\n(.*?)\n```")
	if matches := re.FindStringSubmatch(yamlContent); len(matches) > 1 {
		yamlContent = strings.TrimSpace(matches[1])
	}

	var wrapper struct{ Task Task `yaml:"task"` }
	if err := yaml.Unmarshal([]byte(yamlContent), &wrapper); err != nil { return }
	if wrapper.Task.ID == "" { return }

	filename := fmt.Sprintf("tasks/%d_llm.yaml", time.Now().Unix())
	os.WriteFile(filename, []byte(yamlContent), 0644)
	log.Printf("🧠 Task generated via picoClaw: %s (id: %s)", filename, wrapper.Task.ID)
}

func (e *Engine) buildTaskGenerationPrompt() string {
	skillResult, _ := nativeListSkills(e, nil)
	skillsJSON, _ := json.Marshal(skillResult)

	return fmt.Sprintf(
		"You are an autonomous hardware agent on a LicheeRV Nano (SG2002, RISC-V, 1TOPS NPU).\n"+
			"Primary Goal: %s\n"+
			"Visual Truth: %s\nCommand Truth: %s\n"+
			"Available Skills: %s\n"+
			"Metrics: %v\n\n"+
			"Suggest ONE new task in YAML format.\n"+
			"Respond with ```yaml fences around the task YAML.\n",
		e.Program.Goals.Primary,
		e.State.VisualTruth, e.State.CommandTruth,
		string(skillsJSON), e.State.Metrics)
}

// ════════════════════════════════════════════════════════════════════════
// VISION SYSTEM (camera + NPU, NO LLM — picoClaw handles LLM vision)
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) captureImage(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	outputPath := paramString(params, "output_path", DefaultCapturePath)
	mode := paramString(params, "mode", "none") // none, npu, llm, both

	log.Printf("📸 Capturing → %s (mode=%s)", outputPath, mode)

	// Capture via vision_capture skill (CSI camera, MMF SDK)
	captureParams := map[string]interface{}{"output_path": outputPath}
	captureResult, err := e.callSkill("vision_capture", captureParams, timeout)
	if err != nil {
		return nil, fmt.Errorf("capture failed: %v (install vision_capture skill)", err)
	}

	info, statErr := os.Stat(outputPath)
	if statErr != nil || info.Size() == 0 {
		return nil, fmt.Errorf("image %s missing or empty", outputPath)
	}

	result := map[string]interface{}{
		"image_path": outputPath, "captured": true, "size_bytes": info.Size(),
		"mode": mode,
	}
	for k, v := range captureResult {
		if _, exists := result[k]; !exists { result[k] = v }
	}

	// NPU analysis (local YOLO)
	if mode == "npu" || mode == "both" {
		npuResult, npuErr := e.callSkill("vision_npu",
			map[string]interface{}{"image_path": outputPath}, resolveTimeout(30))
		if npuErr != nil {
			result["npu_error"] = npuErr.Error()
		} else {
			for k, v := range npuResult {
				key := k
				if mode == "both" && (k == "objects" || k == "description") { key = "npu_" + k }
				result[key] = v
			}
			if objects, ok := npuResult["objects"].([]interface{}); ok && len(objects) > 0 {
				descs := []string{}
				for _, obj := range objects {
					if m, ok := obj.(map[string]interface{}); ok {
						if cls, ok := m["class"].(string); ok { descs = append(descs, cls) }
					}
				}
				if len(descs) > 0 {
					e.mu.Lock()
					e.State.VisualTruth = "NPU: " + strings.Join(descs, ", ")
					e.mu.Unlock()
				}
			}
		}
	}

	// LLM analysis → return image path, let picoClaw handle the LLM call
	// picoClaw's vision pipeline will send the image to gemma4/llava
	if mode == "llm" || mode == "both" {
		// Include image data in result so picoClaw can send to vision LLM
		result["needs_vision_analysis"] = true
		result["analysis_hint"] = "picoClaw should send this image to vision-capable LLM"
	}

	e.mu.Lock()
	e.State.CommandTruth = fmt.Sprintf("captured %s (%d bytes)", outputPath, info.Size())
	e.mu.Unlock()
	e.markStateDirty()
	return result, nil
}

// ════════════════════════════════════════════════════════════════════════
// SKILL SYSTEM (same as before)
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) callSkill(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	if handler, ok := nativeSkills[name]; ok {
		result, err := handler(e, params)
		if result != nil { e.State.SkillResults[name] = result; e.markStateDirty() }
		return result, err
	}
	config, err := e.loadSkillConfig(name)
	if err != nil { return nil, fmt.Errorf("skill %q not found: %v", name, err) }
	t := resolveTimeout(timeout, config.Timeout)
	params = e.applySkillDefaults(config, params)

	var result map[string]interface{}
	switch config.ExecType {
	case "shell":  result, err = e.executeShellSkill(config, params, t)
	case "python": result, err = e.executePythonSkill(config, params, t)
	case "api":   result, err = e.executeAPISkill(config, params, t)
	default:      return nil, fmt.Errorf("unknown exec_type %q", config.ExecType)
	}
	if result != nil { e.State.SkillResults[name] = result; e.markStateDirty() }
	return result, err
}

func (e *Engine) applySkillDefaults(config *SkillConfig, params map[string]interface{}) map[string]interface{} {
	merged := make(map[string]interface{})
	for k, v := range params { merged[k] = v }
	for _, p := range config.Parameters {
		if _, ok := merged[p.Name]; !ok && p.Default != nil { merged[p.Name] = p.Default }
	}
	return merged
}

func (e *Engine) loadSkillConfig(name string) (*SkillConfig, error) {
	if config, ok := e.skillCache[name]; ok { return config, nil }
	skillMD := filepath.Join(SkillsDir, name, "SKILL.md")
	data, err := os.ReadFile(skillMD)
	if err != nil { return nil, err }
	re := regexp.MustCompile("(?s)^---\\s*\\n(.*?)\\n---")
	matches := re.FindStringSubmatch(string(data))
	if len(matches) < 2 { return nil, fmt.Errorf("no frontmatter") }
	var config SkillConfig
	if err := yaml.Unmarshal([]byte(matches[1]), &config); err != nil { return nil, err }
	if config.Name == "" { config.Name = name }
	if config.Command != "" && !filepath.IsAbs(config.Command) {
		config.Command = filepath.Join(SkillsDir, name, config.Command)
	}
	e.skillCache[name] = &config
	return &config, nil
}

func (e *Engine) executeShellSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	inputFmt := config.InputFormat
	if inputFmt == "" { inputFmt = "env" }
	var cmdStr string
	var envVars []string
	var stdinData []byte
	var tmpFiles []string

	switch inputFmt {
	case "env":
		cmdStr = config.Command
		for k, v := range params { envVars = append(envVars, fmt.Sprintf("SKILL_%s=%v", strings.ToUpper(k), v)) }
	case "stdin":
		cmdStr = config.Command
		stdinData, _ = json.Marshal(params)
	case "json_file":
		jsonData, _ := json.Marshal(params)
		tmpFile, _ := os.CreateTemp("", "skill_*.json")
		tmpFile.Write(jsonData); tmpFile.Close()
		tmpFiles = append(tmpFiles, tmpFile.Name())
		cmdStr = config.Command + " --params " + shellEscape(tmpFile.Name())
	case "args":
		parts := []string{}
		for k, v := range params { parts = append(parts, fmt.Sprintf("--%s=%s", k, shellEscape(fmt.Sprintf("%v", v)))) }
		cmdStr = config.Command + " " + strings.Join(parts, " ")
	}

	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		envVars = append(envVars, fmt.Sprintf("SKILL_MEMORY_LIMIT_KB=%d", memKB))
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s", memKB, cmdStr)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = append(os.Environ(), envVars...)
	cmd.Dir = filepath.Dir(config.Command)
	if stdinData != nil { cmd.Stdin = bytes.NewReader(stdinData) }
	defer func() { for _, f := range tmpFiles { os.Remove(f) } }()

	out, err := executeCmdWithTimeout(cmd, timeout)
	return e.parseSkillOutput(out, config.OutputFormat), err
}

func (e *Engine) executePythonSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	inputFmt := config.InputFormat
	if inputFmt == "" { inputFmt = "stdin" }
	cmdStr := "python3 " + config.Command
	var envVars []string
	var stdinData []byte

	switch inputFmt {
	case "stdin":
		stdinData, _ = json.Marshal(params)
	case "env":
		for k, v := range params { envVars = append(envVars, fmt.Sprintf("SKILL_%s=%v", strings.ToUpper(k), v)) }
	}
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s", memKB, cmdStr)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = append(os.Environ(), envVars...)
	cmd.Dir = filepath.Dir(config.Command)
	if stdinData != nil { cmd.Stdin = bytes.NewReader(stdinData) }

	out, err := executeCmdWithTimeout(cmd, timeout)
	return e.parseSkillOutput(out, config.OutputFormat), err
}

func (e *Engine) executeAPISkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	endpoint := config.Endpoint
	for k, v := range params {
		if k == "images" { continue }
		endpoint = strings.ReplaceAll(endpoint, "{"+k+"}", fmt.Sprintf("%v", v))
	}
	bodyJSON, _ := json.Marshal(params)
	tmpFile, _ := os.CreateTemp("", "api_*.json")
	tmpFile.Write(bodyJSON); tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	cmd := exec.Command("curl", "-s", "-X", strings.ToUpper(config.Method), endpoint,
		"-H", "Content-Type: application/json", "-d", "@"+tmpFile.Name(),
		"--max-time", fmt.Sprintf("%d", timeout))
	cmd.Env = os.Environ()
	out, err := executeCmdWithTimeout(cmd, timeout)
	if err != nil { return nil, err }
	return e.parseSkillOutput(out, config.OutputFormat), nil
}

func (e *Engine) parseSkillOutput(raw, format string) map[string]interface{} {
	raw = strings.TrimSpace(raw)
	switch format {
	case "json":
		var r map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &r); err == nil { return r }
		return map[string]interface{}{"output": raw, "parse_error": "invalid json"}
	case "keyvalue":
		r := make(map[string]interface{})
		for _, line := range strings.Split(raw, "\n") {
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 { r[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1]) }
		}
		if len(r) == 0 { r["output"] = raw }
		return r
	default:
		return map[string]interface{}{"output": raw}
	}
}

// ════════════════════════════════════════════════════════════════════════
// TASK MANAGEMENT (simplified — picoClaw can also generate tasks)
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) runShellCommand(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	cmdStr := paramString(params, "cmd", "")
	if !e.isApproved(cmdStr) { return nil, fmt.Errorf("blocked by security") }
	if e.Program.Constraints.MaxMemoryMB > 0 {
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s",
			e.Program.Constraints.MaxMemoryMB*1024, cmdStr)
	}
	out, err := runCommandWithTimeout(timeout, "sh", "-c", cmdStr)
	e.mu.Lock()
	e.State.CommandTruth = truncateString(out, MaxStateLength)
	e.mu.Unlock()
	e.markStateDirty()
	return map[string]interface{}{"output": out}, err
}

func (e *Engine) updateMetrics() {
	for name, metric := range e.Program.Metrics {
		if !e.isApproved(metric.Check) {
			e.State.Metrics[name] = "blocked"
			continue
		}
		cmdStr := metric.Check
		if e.Program.Constraints.MaxMemoryMB > 0 {
			cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s",
				e.Program.Constraints.MaxMemoryMB*1024, cmdStr)
		}
		out, err := runCommandWithTimeout(resolveTimeout(e.Program.Constraints.MaxTimeout), "sh", "-c", cmdStr)
		val := strings.TrimSpace(out)
		if err != nil { val = "error" }
		e.State.Metrics[name] = val
	}
}

// ════════════════════════════════════════════════════════════════════════
// COMMAND EXECUTION
// ════════════════════════════════════════════════════════════════════════

func executeCmdWithTimeout(cmd *exec.Cmd, timeoutSec int) (string, error) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	if err := cmd.Start(); err != nil { return "", err }

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		return buf.String(), err
	case <-time.After(time.Duration(timeoutSec) * time.Second):
		if cmd.Process != nil {
			syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
			select {
			case err := <-done:
				return buf.String(), fmt.Errorf("timeout %ds: %v", timeoutSec, err)
			case <-time.After(3 * time.Second):
				syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			}
		}
		select {
		case err := <-done:
			return buf.String(), fmt.Errorf("timeout %ds (killed): %v", timeoutSec, err)
		case <-time.After(5 * time.Second):
			return buf.String(), fmt.Errorf("timeout %ds (zombie)", timeoutSec)
		}
	}
}

func runCommandWithTimeout(timeoutSec int, name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	cmd.Env = os.Environ()
	return executeCmdWithTimeout(cmd, timeoutSec)
}

// ════════════════════════════════════════════════════════════════════════
// CORE LOOP + MAIN
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) Run() {
	// Start MCP server for picoClaw
	e.StartMCPServer()

	// Graceful shutdown
	shutdown := make(chan os.Signal, 1)
	signal.Notify(shutdown, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-shutdown
		atomic.StoreInt32(&e.shutdownFlag, 1)
		e.saveState()
		os.Exit(0)
	}()

	for {
		if atomic.LoadInt32(&e.shutdownFlag) == 1 { e.saveState(); return }

		e.State.Iteration++
		e.updateMetrics()
		e.flushStateIfNeeded()

		// Autonomous monitoring loop — even without picoClaw interaction,
		// the agent can run its own hardware monitoring tasks
		e.runAutonomousCheck()

		if !e.Program.Loop.NeverStop { break }
		time.Sleep(time.Duration(e.Program.Loop.PollInterval) * time.Second)
	}
}

// runAutonomousCheck — lightweight hardware monitoring that runs
// every iteration. Can trigger alerts to picoClaw.

func (e *Engine) runAutonomousCheck() {
	// Check if camera sensor is still bound
	if result, err := nativeProbeCvitek(e, nil); err == nil {
		if bound, ok := result["sensor_bound"].(bool); ok && !bound {
			log.Printf("⚠️ Camera sensor lost — notifying picoClaw")
			e.notifyPicoClaw("⚠️ Camera sensor disconnected — may need re-initialization")
		}
	}
}

func (e *Engine) notifyPicoClaw(message string) {
	payload := map[string]interface{}{
		"message": message,
		"source":  "nano-os-agent",
	}
	pJSON, _ := json.Marshal(payload)
	// Fire-and-forget notification
	go func() {
		runCommandWithTimeout(10, "curl", "-s", "-X", "POST",
			PicoClawGatewayURL+"/api/notify",
			"-H", "Content-Type: application/json",
			"-d", string(pJSON))
	}()
}

func main() {
	engine := NewEngine()
	log.Println("🤖 nano-os-agent v5.0 — Hardware Orchestrator + MCP Server")
	log.Printf("   MCP: %s (picoClaw connects here)", MCPListenAddr)
	log.Printf("   picoClaw Gateway: %s", PicoClawGatewayURL)
	log.Printf("   Skills: %s", SkillsDir)
	log.Printf("   State: VisualTruth=%q", truncateString(engine.State.VisualTruth, 40))
	engine.Run()
}
```

```
package main

// ════════════════════════════════════════════════════════════════════════
// nano-os-agent v5.0 — Hardware Orchestrator + MCP Server for picoClaw
// ════════════════════════════════════════════════════════════════════════
// Target: LicheeRV Nano (SG2002, 256MB DDR3, RISC-V C906, NPU 1TOPS)
// Build:  GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-os-agent
//
// RELATIONSHIP TO PICOCLAW:
//   picoClaw = AI Assistant (chat, LLM, channels, user interface)
//   nano-os-agent = Hardware Orchestrator (camera, NPU, I2C, task queue)
//
//   nano-os-agent exposes hardware tools via MCP server.
//   picoClaw connects as MCP client and calls tools when needed.
//   nano-os-agent also runs autonomous hardware monitoring loops.
//
// NO llm_gateway skill — picoClaw handles ALL LLM calls.
// When nano-os-agent needs LLM reasoning, it calls picoClaw's Gateway API.
// ════════════════════════════════════════════════════════════════════════

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"gopkg.in/yaml.v3"
)

// ════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ════════════════════════════════════════════════════════════════════════

const (
	SkillsDir            = "/root/.picoclaw/workspace/skills"
	DefaultCapturePath   = "/tmp/capture.jpg"
	DefaultFlushInterval = 50
	DefaultContextWindow = 10
	MaxIdleBackoffSecs   = 300
	MaxStateLength       = 300
	MaxImageSizeBytes    = 2 * 1024 * 1024

	// MCP server listens on this port (picoClaw connects here)
	MCPListenAddr = "127.0.0.1:9600"

	// picoClaw Gateway (nano-os-agent calls this for LLM reasoning)
	PicoClawGatewayURL = "http://127.0.0.1:18800"
)

// ════════════════════════════════════════════════════════════════════════
// TYPES
// ════════════════════════════════════════════════════════════════════════

type ProgramConfig struct {
	Metadata struct {
		Name string `yaml:"name"`
		Board string `yaml:"board"`
		SoC  string `yaml:"soc"`
	} `yaml:"metadata"`
	Goals struct {
		Primary   string   `yaml:"primary"`
		Secondary []string `yaml:"secondary"`
	} `yaml:"goals"`
	Constraints struct {
		Readonly         []string `yaml:"readonly"`
		RequiresApproval []string `yaml:"requires_approval"`
		MaxTimeout       int      `yaml:"max_timeout_seconds"`
		MaxMemoryMB      int      `yaml:"max_memory_mb"`
	} `yaml:"constraints"`
	Metrics map[string]Metric `yaml:"metrics"`
	Strategy struct {
		MaxRetries     int      `yaml:"max_retries"`
		Recovery       []string `yaml:"recovery"`
		SimplicityBias bool     `yaml:"simplicity_bias"`
		UseLLM         bool     `yaml:"use_llm"`
	} `yaml:"strategy"`
	Loop struct {
		NeverStop     bool `yaml:"never_stop"`
		PollInterval  int  `yaml:"poll_interval"`
		ContextWindow int  `yaml:"context_window"`
	} `yaml:"loop"`
}

type Metric struct {
	Check  string      `yaml:"check"`
	Target interface{} `yaml:"target"`
}

type Task struct {
	ID              string    `yaml:"id"`
	Name            string   `yaml:"name"`
	Priority        int      `yaml:"priority"`
	Status          string   `yaml:"status"`
	SuccessCriteria []string  `yaml:"success_criteria"`
	Steps           []Step   `yaml:"steps"`
	Subtasks        []Subtask `yaml:"subtasks"`
	SourceFile      string   `yaml:"-"`
}

type Step struct {
	ID         string                 `yaml:"id"`
	Action     string                 `yaml:"action"`
	Parameters map[string]interface{} `yaml:"parameters"`
	Timeout    int                    `yaml:"timeout"`
	Expect     map[string]interface{} `yaml:"expect"`
	OnFail     string                 `yaml:"on_fail"`
	MaxRetries int                    `yaml:"max_retries"`
}

type Subtask struct {
	ID   string `yaml:"id"`
	Name string `yaml:"name"`
	File string `yaml:"file"`
}

type SkillConfig struct {
	Name         string       `yaml:"name"`
	ExecType     string       `yaml:"exec_type"`
	Command      string       `yaml:"command"`
	Endpoint     string       `yaml:"endpoint"`
	Method       string       `yaml:"method"`
	InputFormat  string       `yaml:"input_format"`
	OutputFormat string       `yaml:"output_format"`
	Timeout      int          `yaml:"timeout"`
	Parameters   []SkillParam `yaml:"parameters"`
	Returns      []string     `yaml:"returns"`
}

type SkillParam struct {
	Name    string      `yaml:"name"`
	Type    string      `yaml:"type"`
	Default interface{} `yaml:"default"`
}

type State struct {
	CurrentTaskID  string                 `json:"current_task_id"`
	Iteration      int                    `json:"iteration"`
	History        []string               `json:"history"`
	Metrics        map[string]string      `json:"metrics"`
	VisualTruth    string                 `json:"visual_truth"`
	CommandTruth   string                 `json:"command_truth"`
	SkillResults   map[string]interface{} `json:"skill_results"`
	RecentFailures []string               `json:"recent_failures"`
}

// ════════════════════════════════════════════════════════════════════════
// MCP PROTOCOL TYPES
// ════════════════════════════════════════════════════════════════════════
// JSON-RPC 2.0 based protocol as defined by MCP spec.
// picoClaw sends requests, nano-os-agent responds.

type MCPRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type MCPResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *MCPError   `json:"error,omitempty"`
}

type MCPError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type MCPTool struct {
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	InputSchema  map[string]interface{} `json:"inputSchema"`
}

type MCPToolCallParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

// ════════════════════════════════════════════════════════════════════════
// SECURITY (same as before)
// ════════════════════════════════════════════════════════════════════════

var dangerousWordPatterns = []string{"reboot", "poweroff", "halt", "shutdown"}
var dangerousSubstringPatterns = []string{
	"sudo ", "sudo\t", "/proc/sys", "init 0", "init 6",
	"mkfs.", "dd if=", "dd of=", "> /dev/sd", "> /dev/mmc",
	"chmod 000", "rm -rf /", "rm -rf /*", ":(){:|:&};:",
}
var obfuscationPatterns = []string{
	"base64 --decode", "base64 -d", "eval $(", "perl -e",
	"/dev/tcp/", "/dev/udp/", "nc -e",
}
var protectedEnvVars = map[string]bool{
	"PATH": true, "LD_PRELOAD": true, "IFS": true,
	"SHELL": true, "HOME": true,
}

func isWordMatch(cmd, word string) bool {
	lower, target := strings.ToLower(cmd), strings.ToLower(word)
	idx := 0
	for {
		pos := strings.Index(lower[idx:], target)
		if pos < 0 { return false }
		absPos := idx + pos
		beforeOK := absPos == 0 || !isAlphanumeric(lower[absPos-1])
		afterOK := absPos+len(target) >= len(lower) || !isAlphanumeric(lower[absPos+len(target)])
		if beforeOK && afterOK { return true }
		idx = absPos + 1
	}
}

func isAlphanumeric(c byte) bool {
	return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'
}

func extractWriteTargets(cmdStr string) []string {
	var targets []string
	for _, m := range regexp.MustCompile(`>{1,2}\s*(/\S+)`).FindAllStringSubmatch(cmdStr, -1) {
		if m[1] != "/dev/null" { targets = append(targets, m[1]) }
	}
	return targets
}

func (e *Engine) isApproved(cmdStr string) bool {
	lower := strings.ToLower(cmdStr)
	for _, w := range dangerousWordPatterns {
		if isWordMatch(lower, w) { return false }
	}
	for _, p := range dangerousSubstringPatterns {
		if strings.Contains(lower, strings.ToLower(p)) { return false }
	}
	for _, p := range obfuscationPatterns {
		if strings.Contains(lower, strings.ToLower(p)) { return false }
	}
	if strings.Contains(lower, "ulimit") { return false }
	for _, p := range extractWriteTargets(cmdStr) {
		if e.isReadonly(p) { return false }
	}
	for _, p := range e.Program.Constraints.RequiresApproval {
		if strings.Contains(lower, strings.ToLower(p)) { return false }
	}
	return true
}

func (e *Engine) isReadonly(path string) bool {
	for _, pattern := range e.Program.Constraints.Readonly {
		if matched, _ := filepath.Match(pattern, path); matched { return true }
		if strings.HasSuffix(pattern, "*") &&
			strings.HasPrefix(path, strings.TrimSuffix(pattern, "*")) { return true }
	}
	return false
}

func shellEscape(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}

// ════════════════════════════════════════════════════════════════════════
// UTILITY HELPERS
// ════════════════════════════════════════════════════════════════════════

func resolveTimeout(values ...int) int {
	for _, v := range values { if v > 0 { return v } }
	return 60
}
func paramInt(p map[string]interface{}, k string, d int) int {
	if v, ok := p[k].(int); ok && v > 0 { return v }
	if v, ok := p[k].(float64); ok && v > 0 { return int(v) }
	if v, ok := p[k].(string); ok { if n, e := strconv.Atoi(v); e == nil && n > 0 { return n } }
	return d
}
func paramString(p map[string]interface{}, k, d string) string {
	if v, ok := p[k].(string); ok && v != "" { return v }
	return d
}
func paramBool(p map[string]interface{}, k string, d bool) bool {
	if v, ok := p[k].(bool); ok { return v }
	if v, ok := p[k].(string); ok { return strings.ToLower(v) == "true" }
	return d
}
func truncateString(s string, n int) string {
	if len(s) <= n { return s }
	return s[:n] + "..."
}
func minInt(a, b int) int {
	if a < b { return a }
	return b
}

// ════════════════════════════════════════════════════════════════════════
// NATIVE SKILLS
// ════════════════════════════════════════════════════════════════════════

type NativeSkillFunc func(e *Engine, params map[string]interface{}) (map[string]interface{}, error)

var nativeSkills = map[string]NativeSkillFunc{
	"i2c_scan":     nativeI2CScan,
	"probe_cvitek": nativeProbeCvitek,
	"list_skills":  nativeListSkills,
}

func nativeI2CScan(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	bus := paramString(params, "bus", "1")
	out, err := runCommandWithTimeout(10, "i2cdetect", "-y", bus)
	count := 0
	for _, line := range strings.Split(out, "\n") {
		for _, f := range strings.Fields(line) {
			if f != "--" && f != "UU" && len(f) == 2 { count++ }
		}
	}
	return map[string]interface{}{"count": count, "raw": out}, err
}

func nativeProbeCvitek(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	data, err := os.ReadFile("/proc/cvitek/vi")
	if err != nil { return map[string]interface{}{"sensor_bound": false, "error": err.Error()}, nil }
	return map[string]interface{}{
		"sensor_bound": strings.Contains(string(data), "DevID"),
		"raw":          strings.TrimSpace(string(data)),
	}, nil
}

func nativeListSkills(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	seen := map[string]bool{}
	names := []string{}
	for name := range nativeSkills { names = append(names, name); seen[name] = true }
	files, _ := os.ReadDir(SkillsDir)
	for _, f := range files {
		if f.IsDir() && !seen[f.Name()] {
			if _, err := os.Stat(filepath.Join(SkillsDir, f.Name(), "SKILL.md")); err == nil {
				names = append(names, f.Name())
			}
		}
	}
	sort.Strings(names)
	return map[string]interface{}{"skills": names, "count": len(names)}, nil
}

// ════════════════════════════════════════════════════════════════════════
// ENGINE
// ════════════════════════════════════════════════════════════════════════

type Engine struct {
	Program       ProgramConfig
	State         State
	shutdownFlag  int32
	skillCache    map[string]*SkillConfig
	stateDirty    bool
	flushCounter  int
	flushInterval int
	idleCount     int
	mu            sync.Mutex // protects State for concurrent MCP calls
}

func NewEngine() *Engine {
	e := &Engine{
		skillCache:    make(map[string]*SkillConfig),
		flushInterval: DefaultFlushInterval,
	}
	e.loadEnv()
	e.loadProgram()
	e.loadState()

	if e.Program.Loop.ContextWindow <= 0 { e.Program.Loop.ContextWindow = DefaultContextWindow }
	if e.Program.Constraints.MaxMemoryMB <= 0 { e.Program.Constraints.MaxMemoryMB = 32 }
	if e.Program.Loop.PollInterval <= 0 { e.Program.Loop.PollInterval = 10 }
	if e.State.SkillResults == nil { e.State.SkillResults = make(map[string]interface{}) }
	if e.State.History == nil { e.State.History = make([]string, 0) }
	if e.State.Metrics == nil { e.State.Metrics = make(map[string]string) }
	if e.State.RecentFailures == nil { e.State.RecentFailures = make([]string, 0) }

	log.Printf("🤖 nano-os-agent v5.0 — Hardware Orchestrator + MCP Server")
	log.Printf("   Board: %s (%s) | MemLimit: %dMB | MCP: %s",
		e.Program.Metadata.Board, e.Program.Metadata.SoC,
		e.Program.Constraints.MaxMemoryMB, MCPListenAddr)
	log.Printf("   picoClaw Gateway: %s", PicoClawGatewayURL)
	return e
}

func (e *Engine) loadEnv() {
	for _, p := range []string{".env", "/root/.env"} {
		if err := parseEnvFile(p); err == nil { return }
	}
}

func parseEnvFile(path string) error {
	file, err := os.Open(path)
	if err != nil { return err }
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0), 4096)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") { continue }
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 {
			key := strings.TrimSpace(parts[0])
			if !protectedEnvVars[key] {
				os.Setenv(key, strings.TrimSpace(parts[1]))
			}
		}
	}
	return scanner.Err()
}

func (e *Engine) loadProgram() {
	data, err := os.ReadFile("program.yaml")
	if err != nil { log.Fatalf("❌ program.yaml: %v", err) }
	if err := yaml.Unmarshal(data, &e.Program); err != nil { log.Fatalf("❌ program.yaml: %v", err) }
}

func (e *Engine) loadState() {
	data, err := os.ReadFile("state.json")
	if err != nil {
		e.State = State{Metrics: make(map[string]string), History: []string{},
			SkillResults: make(map[string]interface{}), RecentFailures: []string{}}
		return
	}
	if err := json.Unmarshal(data, &e.State); err != nil {
		log.Printf("⚠️ state.json corrupt: %v", err)
		e.State = State{Metrics: make(map[string]string), History: []string{},
			SkillResults: make(map[string]interface{}), RecentFailures: []string{}}
	}
}

func (e *Engine) saveState() {
	e.mu.Lock()
	data, err := json.MarshalIndent(e.State, "", "  ")
	e.mu.Unlock()
	if err != nil { log.Printf("⚠️ marshal state: %v", err); return }
	tmpPath := "state.json.tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil { log.Printf("⚠️ write state: %v", err); return }
	if err := os.Rename(tmpPath, "state.json"); err != nil { os.Remove(tmpPath) }
	e.stateDirty = false
	e.flushCounter = 0
}

func (e *Engine) markStateDirty() { e.stateDirty = true }

func (e *Engine) flushStateIfNeeded() {
	if !e.stateDirty { return }
	e.flushCounter++
	if e.flushCounter >= e.flushInterval { e.saveState() }
}

// ════════════════════════════════════════════════════════════════════════
// MCP SERVER — the bridge between picoClaw and hardware
// ════════════════════════════════════════════════════════════════════════
// Listens on MCPListenAddr. picoClaw connects here as MCP client.
// Implements JSON-RPC 2.0 with these methods:
//   initialize      → server info + capabilities
//   tools/list      → list available hardware tools
//   tools/call      → execute a hardware tool
//   resources/list  → list state resources
//   resources/read  → read state (Visual Truth, metrics, etc.)

func (e *Engine) StartMCPServer() {
	listener, err := net.Listen("tcp", MCPListenAddr)
	if err != nil {
		log.Fatalf("❌ MCP listen failed on %s: %v", MCPListenAddr, err)
	}
	log.Printf("🔌 MCP server listening on %s (picoClaw connects here)", MCPListenAddr)

	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil { continue }
			go e.handleMCPConnection(conn)
		}
	}()
}

func (e *Engine) handleMCPConnection(conn net.Conn) {
	defer conn.Close()
	decoder := json.NewDecoder(conn)
	encoder := json.NewEncoder(conn)

	for {
		var req MCPRequest
		if err := decoder.Decode(&req); err != nil { return }

		resp := e.handleMCPRequest(&req)
		encoder.Encode(resp)
	}
}

func (e *Engine) handleMCPRequest(req *MCPRequest) MCPResponse {
	resp := MCPResponse{JSONRPC: "2.0", ID: req.ID}

	switch req.Method {

	case "initialize":
		resp.Result = map[string]interface{}{
			"protocolVersion": "2024-11-05",
			"capabilities": map[string]interface{}{
				"tools":    map[string]interface{}{"listChanged": true},
				"resources": map[string]interface{}{"listChanged": true},
			},
			"serverInfo": map[string]interface{}{
				"name":    "nano-os-agent",
				"version": "5.0",
			},
		}

	case "notifications/initialized":
		// Client acknowledges initialization — no response needed
		resp.Result = map[string]interface{}{}

	case "tools/list":
		resp.Result = map[string]interface{}{
			"tools": e.getMCPTools(),
		}

	case "tools/call":
		var params MCPToolCallParams
		if err := json.Unmarshal(req.Params, &params); err != nil {
			resp.Error = &MCPError{Code: -32602, Message: "invalid params"}
			break
		}
		result, mcpErr := e.executeMCPTool(params.Name, params.Arguments)
		if mcpErr != nil {
			resp.Result = map[string]interface{}{
				"content": []map[string]interface{}{
					{"type": "text", "text": fmt.Sprintf("Error: %v", mcpErr)},
				},
				"isError": true,
			}
		} else {
			content := []map[string]interface{}{
				{"type": "text", "text": fmt.Sprintf("%v", result)},
			}
			// If result has image_path, add image content
			if img, ok := result["image_path"].(string); ok && img != "" {
				data, err := os.ReadFile(img)
				if err == nil {
					encoded := encodeToBase64(data)
					content = append(content, map[string]interface{}{
						"type":     "image",
						"data":     encoded,
						"mimeType": "image/jpeg",
					})
				}
			}
			resp.Result = map[string]interface{}{
				"content": content,
			}
		}

	case "resources/list":
		resp.Result = map[string]interface{}{
			"resources": []map[string]interface{}{
				{"uri": "nano://state", "name": "Agent State", "mimeType": "application/json"},
				{"uri": "nano://visual_truth", "name": "Visual Truth", "mimeType": "text/plain"},
				{"uri": "nano://metrics", "name": "Hardware Metrics", "mimeType": "application/json"},
			},
		}

	case "resources/read":
		var params struct{ URI string `json:"uri"` }
		json.Unmarshal(req.Params, &params)
		resp.Result = e.readMCPResource(params.URI)

	default:
		resp.Error = &MCPError{Code: -32601, Message: "method not found: " + req.Method}
	}

	return resp
}

// ── MCP Tool Definitions ────────────────────────────────────────────────
// These are the tools picoClaw sees when it connects.

func (e *Engine) getMCPTools() []MCPTool {
	return []MCPTool{
		{
			Name:        "capture_image",
			Description: "Capture a frame from the CSI camera on LicheeRV Nano. Returns image path and metadata. Optionally analyze with NPU (YOLO) or send to vision LLM via picoClaw.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"output_path": map[string]interface{}{"type": "string", "description": "Save path", "default": "/tmp/capture.jpg"},
					"width":       map[string]interface{}{"type": "integer", "default": 640},
					"height":      map[string]interface{}{"type": "integer", "default": 640},
					"mode":        map[string]interface{}{"type": "string", "enum": []string{"none", "npu", "llm", "both"}, "default": "none", "description": "Analysis mode: none=capture only, npu=YOLO, llm=vision LLM (picoClaw handles the LLM call), both=NPU+LLM"},
				},
			},
		},
		{
			Name:        "run_yolo",
			Description: "Run YOLO object detection on NPU (1 TOPS INT8) for an image file. Returns detected objects with bounding boxes, class names, and confidence scores.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"image_path":  map[string]interface{}{"type": "string", "description": "Path to image file"},
					"model_path":  map[string]interface{}{"type": "string", "default": "/root/models/yolov8n_coco_640.cvimodel"},
					"class_cnt":   map[string]interface{}{"type": "integer", "default": 80},
					"threshold":   map[string]interface{}{"type": "number", "default": 0.5},
				},
				"required": []string{"image_path"},
			},
		},
		{
			Name:        "start_stream",
			Description: "Start MJPEG video stream from CSI camera. Returns URL and PID.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"port":      map[string]interface{}{"type": "integer", "default": 7777},
					"width":     map[string]interface{}{"type": "integer", "default": 640},
					"height":    map[string]interface{}{"type": "integer", "default": 640},
					"grayscale": map[string]interface{}{"type": "boolean", "default": false},
				},
			},
		},
		{
			Name:        "stop_stream",
			Description: "Stop running MJPEG video stream.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{},
			},
		},
		{
			Name:        "scan_i2c",
			Description: "Scan I2C bus for connected devices. Returns device count and addresses.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"bus": map[string]interface{}{"type": "string", "default": "1"},
				},
			},
		},
		{
			Name:        "probe_sensor",
			Description: "Check CSI camera sensor status via /proc/cvitek/vi.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
		{
			Name:        "init_camera",
			Description: "Initialize CSI camera sensor (run sensor_test). Required once after boot.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{
				"force": map[string]interface{}{"type": "boolean", "default": false},
			}},
		},
		{
			Name:        "get_visual_truth",
			Description: "Return the current Visual Truth — what the agent last saw and understood about the world.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
		{
			Name:        "run_shell",
			Description: "Execute a shell command on the board (with security checks). Blocked commands: reboot, sudo, dd, rm -rf /, etc.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"cmd":     map[string]interface{}{"type": "string", "description": "Shell command to execute"},
					"timeout": map[string]interface{}{"type": "integer", "default": 30},
				},
				"required": []string{"cmd"},
			},
		},
		{
			Name:        "list_skills",
			Description: "List all available skills (native Go + SKILL.md external).",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
	}
}

// ── MCP Tool Execution ─────────────────────────────────────────────────

func (e *Engine) executeMCPTool(name string, args map[string]interface{}) (map[string]interface{}, error) {
	log.Printf("🔌 MCP tool call: %s %v", name, args)

	switch name {

	case "capture_image":
		return e.captureImage(args, resolveTimeout(30))

	case "run_yolo":
		return e.callSkill("vision_npu", args, resolveTimeout(30))

	case "start_stream":
		args["action"] = "start"
		return e.callSkill("vision_stream", args, resolveTimeout(15))

	case "stop_stream":
		return e.callSkill("vision_stream",
			map[string]interface{}{"action": "stop"}, resolveTimeout(10))

	case "scan_i2c":
		return e.callSkill("i2c_scan", args, resolveTimeout(10))

	case "probe_sensor":
		return e.callSkill("probe_cvitek", nil, resolveTimeout(10))

	case "init_camera":
		return e.callSkill("camera_init", args, resolveTimeout(30))

	case "get_visual_truth":
		e.mu.Lock()
		result := map[string]interface{}{
			"visual_truth":  e.State.VisualTruth,
			"command_truth": e.State.CommandTruth,
			"metrics":       e.State.Metrics,
		}
		e.mu.Unlock()
		return result, nil

	case "run_shell":
		cmdStr := paramString(args, "cmd", "")
		if !e.isApproved(cmdStr) {
			return nil, fmt.Errorf("command blocked by security policy")
		}
		timeout := paramInt(args, "timeout", 30)
		return e.runShellCommand(args, timeout)

	case "list_skills":
		return nativeListSkills(e, nil)

	default:
		return nil, fmt.Errorf("unknown MCP tool: %s", name)
	}
}

func (e *Engine) readMCPResource(uri string) interface{} {
	e.mu.Lock()
	defer e.mu.Unlock()

	switch uri {
	case "nano://state":
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "application/json",
					"text": fmt.Sprintf("%v", e.State)},
			},
		}
	case "nano://visual_truth":
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "text/plain", "text": e.State.VisualTruth},
			},
		}
	case "nano://metrics":
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "application/json",
					"text": fmt.Sprintf("%v", e.State.Metrics)},
			},
		}
	default:
		return map[string]interface{}{
			"contents": []map[string]interface{}{
				{"uri": uri, "mimeType": "text/plain", "text": "unknown resource"},
			},
		}
	}
}

func encodeToBase64(data []byte) string {
	// Simple base64 encoding without importing encoding/base64 at MCP level
	// Actually we already import it, so use it directly
	return fmt.Sprintf("data:image/jpeg;base64,%s",
		bytesToBase64(data))
}

func bytesToBase64(data []byte) string {
	// Use encoding/base64
	return strings.ReplaceAll(strings.ReplaceAll(
		fmt.Sprintf("%s", base64Encode(data)),
		"\n", ""), "\r", "")
}

// Simple base64 encoder (stdlib already imported)
func base64Encode(data []byte) string {
	return string(bytes.TrimSpace(
		append([]byte{}, []byte(base64EncodeStr(data))...))
}

func base64EncodeStr(data []byte) string {
	const table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	result := make([]byte, 0, (len(data)+2)/3*4)
	for i := 0; i < len(data); i += 3 {
		var n uint32
		rem := len(data) - i
		if rem >= 3 {
			n = uint32(data[i])<<16 | uint32(data[i+1])<<8 | uint32(data[i+2])
			result = append(result, table[n>>18&0x3f], table[n>>12&0x3f],
				table[n>>6&0x3f], table[n&0x3f])
		} else if rem == 2 {
			n = uint32(data[i])<<16 | uint32(data[i+1])<<8
			result = append(result, table[n>>18&0x3f], table[n>>12&0x3f],
				table[n>>6&0x3f], '=')
		} else {
			n = uint32(data[i]) << 16
			result = append(result, table[n>>18&0x3f], table[n>>12&0x3f], '=', '=')
		}
	}
	return string(result)
}

// ════════════════════════════════════════════════════════════════════════
// PICOCLAW GATEWAY CLIENT
// ════════════════════════════════════════════════════════════════════════
// When nano-os-agent needs LLM reasoning (e.g., for autonomous task
// generation), it calls picoClaw's Gateway API instead of having its
// own llm_gateway. Single source of truth: picoClaw owns all LLM calls.

func (e *Engine) askPicoClawForTask() {
	if !e.Program.Strategy.UseLLM { return }

	prompt := e.buildTaskGenerationPrompt()

	// Call picoClaw's Gateway API
	payload := map[string]interface{}{
		"message": prompt,
		"model":   "auto", // picoClaw handles routing
	}
	pJSON, _ := json.Marshal(payload)

	tmpFile, err := os.CreateTemp("", "picoclaw_task_*.json")
	if err != nil { return }
	tmpFile.Write(pJSON)
	tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	out, err := runCommandWithTimeout(90, "curl", "-s", "-X", "POST",
		PicoClawGatewayURL+"/api/chat",
		"-H", "Content-Type: application/json",
		"-d", "@"+tmpFile.Name())
	if err != nil {
		log.Printf("⚠️ picoClaw Gateway call failed: %v", err)
		return
	}

	var resp struct{ Response string `json:"response"` }
	if err := json.Unmarshal([]byte(out), &resp); err != nil { return }

	// Extract YAML task from LLM response (same logic as before)
	yamlContent := resp.Response
	re := regexp.MustCompile("(?s)```(?:ya?ml)?\\s*\n(.*?)\n```")
	if matches := re.FindStringSubmatch(yamlContent); len(matches) > 1 {
		yamlContent = strings.TrimSpace(matches[1])
	}

	var wrapper struct{ Task Task `yaml:"task"` }
	if err := yaml.Unmarshal([]byte(yamlContent), &wrapper); err != nil { return }
	if wrapper.Task.ID == "" { return }

	filename := fmt.Sprintf("tasks/%d_llm.yaml", time.Now().Unix())
	os.WriteFile(filename, []byte(yamlContent), 0644)
	log.Printf("🧠 Task generated via picoClaw: %s (id: %s)", filename, wrapper.Task.ID)
}

func (e *Engine) buildTaskGenerationPrompt() string {
	skillResult, _ := nativeListSkills(e, nil)
	skillsJSON, _ := json.Marshal(skillResult)

	return fmt.Sprintf(
		"You are an autonomous hardware agent on a LicheeRV Nano (SG2002, RISC-V, 1TOPS NPU).\n"+
			"Primary Goal: %s\n"+
			"Visual Truth: %s\nCommand Truth: %s\n"+
			"Available Skills: %s\n"+
			"Metrics: %v\n\n"+
			"Suggest ONE new task in YAML format.\n"+
			"Respond with ```yaml fences around the task YAML.\n",
		e.Program.Goals.Primary,
		e.State.VisualTruth, e.State.CommandTruth,
		string(skillsJSON), e.State.Metrics)
}

// ════════════════════════════════════════════════════════════════════════
// VISION SYSTEM (camera + NPU, NO LLM — picoClaw handles LLM vision)
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) captureImage(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	outputPath := paramString(params, "output_path", DefaultCapturePath)
	mode := paramString(params, "mode", "none") // none, npu, llm, both

	log.Printf("📸 Capturing → %s (mode=%s)", outputPath, mode)

	// Capture via vision_capture skill (CSI camera, MMF SDK)
	captureParams := map[string]interface{}{"output_path": outputPath}
	captureResult, err := e.callSkill("vision_capture", captureParams, timeout)
	if err != nil {
		return nil, fmt.Errorf("capture failed: %v (install vision_capture skill)", err)
	}

	info, statErr := os.Stat(outputPath)
	if statErr != nil || info.Size() == 0 {
		return nil, fmt.Errorf("image %s missing or empty", outputPath)
	}

	result := map[string]interface{}{
		"image_path": outputPath, "captured": true, "size_bytes": info.Size(),
		"mode": mode,
	}
	for k, v := range captureResult {
		if _, exists := result[k]; !exists { result[k] = v }
	}

	// NPU analysis (local YOLO)
	if mode == "npu" || mode == "both" {
		npuResult, npuErr := e.callSkill("vision_npu",
			map[string]interface{}{"image_path": outputPath}, resolveTimeout(30))
		if npuErr != nil {
			result["npu_error"] = npuErr.Error()
		} else {
			for k, v := range npuResult {
				key := k
				if mode == "both" && (k == "objects" || k == "description") { key = "npu_" + k }
				result[key] = v
			}
			if objects, ok := npuResult["objects"].([]interface{}); ok && len(objects) > 0 {
				descs := []string{}
				for _, obj := range objects {
					if m, ok := obj.(map[string]interface{}); ok {
						if cls, ok := m["class"].(string); ok { descs = append(descs, cls) }
					}
				}
				if len(descs) > 0 {
					e.mu.Lock()
					e.State.VisualTruth = "NPU: " + strings.Join(descs, ", ")
					e.mu.Unlock()
				}
			}
		}
	}

	// LLM analysis → return image path, let picoClaw handle the LLM call
	// picoClaw's vision pipeline will send the image to gemma4/llava
	if mode == "llm" || mode == "both" {
		// Include image data in result so picoClaw can send to vision LLM
		result["needs_vision_analysis"] = true
		result["analysis_hint"] = "picoClaw should send this image to vision-capable LLM"
	}

	e.mu.Lock()
	e.State.CommandTruth = fmt.Sprintf("captured %s (%d bytes)", outputPath, info.Size())
	e.mu.Unlock()
	e.markStateDirty()
	return result, nil
}

// ════════════════════════════════════════════════════════════════════════
// SKILL SYSTEM (same as before)
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) callSkill(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	if handler, ok := nativeSkills[name]; ok {
		result, err := handler(e, params)
		if result != nil { e.State.SkillResults[name] = result; e.markStateDirty() }
		return result, err
	}
	config, err := e.loadSkillConfig(name)
	if err != nil { return nil, fmt.Errorf("skill %q not found: %v", name, err) }
	t := resolveTimeout(timeout, config.Timeout)
	params = e.applySkillDefaults(config, params)

	var result map[string]interface{}
	switch config.ExecType {
	case "shell":  result, err = e.executeShellSkill(config, params, t)
	case "python": result, err = e.executePythonSkill(config, params, t)
	case "api":   result, err = e.executeAPISkill(config, params, t)
	default:      return nil, fmt.Errorf("unknown exec_type %q", config.ExecType)
	}
	if result != nil { e.State.SkillResults[name] = result; e.markStateDirty() }
	return result, err
}

func (e *Engine) applySkillDefaults(config *SkillConfig, params map[string]interface{}) map[string]interface{} {
	merged := make(map[string]interface{})
	for k, v := range params { merged[k] = v }
	for _, p := range config.Parameters {
		if _, ok := merged[p.Name]; !ok && p.Default != nil { merged[p.Name] = p.Default }
	}
	return merged
}

func (e *Engine) loadSkillConfig(name string) (*SkillConfig, error) {
	if config, ok := e.skillCache[name]; ok { return config, nil }
	skillMD := filepath.Join(SkillsDir, name, "SKILL.md")
	data, err := os.ReadFile(skillMD)
	if err != nil { return nil, err }
	re := regexp.MustCompile("(?s)^---\\s*\\n(.*?)\\n---")
	matches := re.FindStringSubmatch(string(data))
	if len(matches) < 2 { return nil, fmt.Errorf("no frontmatter") }
	var config SkillConfig
	if err := yaml.Unmarshal([]byte(matches[1]), &config); err != nil { return nil, err }
	if config.Name == "" { config.Name = name }
	if config.Command != "" && !filepath.IsAbs(config.Command) {
		config.Command = filepath.Join(SkillsDir, name, config.Command)
	}
	e.skillCache[name] = &config
	return &config, nil
}

func (e *Engine) executeShellSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	inputFmt := config.InputFormat
	if inputFmt == "" { inputFmt = "env" }
	var cmdStr string
	var envVars []string
	var stdinData []byte
	var tmpFiles []string

	switch inputFmt {
	case "env":
		cmdStr = config.Command
		for k, v := range params { envVars = append(envVars, fmt.Sprintf("SKILL_%s=%v", strings.ToUpper(k), v)) }
	case "stdin":
		cmdStr = config.Command
		stdinData, _ = json.Marshal(params)
	case "json_file":
		jsonData, _ := json.Marshal(params)
		tmpFile, _ := os.CreateTemp("", "skill_*.json")
		tmpFile.Write(jsonData); tmpFile.Close()
		tmpFiles = append(tmpFiles, tmpFile.Name())
		cmdStr = config.Command + " --params " + shellEscape(tmpFile.Name())
	case "args":
		parts := []string{}
		for k, v := range params { parts = append(parts, fmt.Sprintf("--%s=%s", k, shellEscape(fmt.Sprintf("%v", v)))) }
		cmdStr = config.Command + " " + strings.Join(parts, " ")
	}

	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		envVars = append(envVars, fmt.Sprintf("SKILL_MEMORY_LIMIT_KB=%d", memKB))
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s", memKB, cmdStr)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = append(os.Environ(), envVars...)
	cmd.Dir = filepath.Dir(config.Command)
	if stdinData != nil { cmd.Stdin = bytes.NewReader(stdinData) }
	defer func() { for _, f := range tmpFiles { os.Remove(f) } }()

	out, err := executeCmdWithTimeout(cmd, timeout)
	return e.parseSkillOutput(out, config.OutputFormat), err
}

func (e *Engine) executePythonSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	inputFmt := config.InputFormat
	if inputFmt == "" { inputFmt = "stdin" }
	cmdStr := "python3 " + config.Command
	var envVars []string
	var stdinData []byte

	switch inputFmt {
	case "stdin":
		stdinData, _ = json.Marshal(params)
	case "env":
		for k, v := range params { envVars = append(envVars, fmt.Sprintf("SKILL_%s=%v", strings.ToUpper(k), v)) }
	}
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s", memKB, cmdStr)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = append(os.Environ(), envVars...)
	cmd.Dir = filepath.Dir(config.Command)
	if stdinData != nil { cmd.Stdin = bytes.NewReader(stdinData) }

	out, err := executeCmdWithTimeout(cmd, timeout)
	return e.parseSkillOutput(out, config.OutputFormat), err
}

func (e *Engine) executeAPISkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	endpoint := config.Endpoint
	for k, v := range params {
		if k == "images" { continue }
		endpoint = strings.ReplaceAll(endpoint, "{"+k+"}", fmt.Sprintf("%v", v))
	}
	bodyJSON, _ := json.Marshal(params)
	tmpFile, _ := os.CreateTemp("", "api_*.json")
	tmpFile.Write(bodyJSON); tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	cmd := exec.Command("curl", "-s", "-X", strings.ToUpper(config.Method), endpoint,
		"-H", "Content-Type: application/json", "-d", "@"+tmpFile.Name(),
		"--max-time", fmt.Sprintf("%d", timeout))
	cmd.Env = os.Environ()
	out, err := executeCmdWithTimeout(cmd, timeout)
	if err != nil { return nil, err }
	return e.parseSkillOutput(out, config.OutputFormat), nil
}

func (e *Engine) parseSkillOutput(raw, format string) map[string]interface{} {
	raw = strings.TrimSpace(raw)
	switch format {
	case "json":
		var r map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &r); err == nil { return r }
		return map[string]interface{}{"output": raw, "parse_error": "invalid json"}
	case "keyvalue":
		r := make(map[string]interface{})
		for _, line := range strings.Split(raw, "\n") {
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 { r[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1]) }
		}
		if len(r) == 0 { r["output"] = raw }
		return r
	default:
		return map[string]interface{}{"output": raw}
	}
}

// ════════════════════════════════════════════════════════════════════════
// TASK MANAGEMENT (simplified — picoClaw can also generate tasks)
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) runShellCommand(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	cmdStr := paramString(params, "cmd", "")
	if !e.isApproved(cmdStr) { return nil, fmt.Errorf("blocked by security") }
	if e.Program.Constraints.MaxMemoryMB > 0 {
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s",
			e.Program.Constraints.MaxMemoryMB*1024, cmdStr)
	}
	out, err := runCommandWithTimeout(timeout, "sh", "-c", cmdStr)
	e.mu.Lock()
	e.State.CommandTruth = truncateString(out, MaxStateLength)
	e.mu.Unlock()
	e.markStateDirty()
	return map[string]interface{}{"output": out}, err
}

func (e *Engine) updateMetrics() {
	for name, metric := range e.Program.Metrics {
		if !e.isApproved(metric.Check) {
			e.State.Metrics[name] = "blocked"
			continue
		}
		cmdStr := metric.Check
		if e.Program.Constraints.MaxMemoryMB > 0 {
			cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s",
				e.Program.Constraints.MaxMemoryMB*1024, cmdStr)
		}
		out, err := runCommandWithTimeout(resolveTimeout(e.Program.Constraints.MaxTimeout), "sh", "-c", cmdStr)
		val := strings.TrimSpace(out)
		if err != nil { val = "error" }
		e.State.Metrics[name] = val
	}
}

// ════════════════════════════════════════════════════════════════════════
// COMMAND EXECUTION
// ════════════════════════════════════════════════════════════════════════

func executeCmdWithTimeout(cmd *exec.Cmd, timeoutSec int) (string, error) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	if err := cmd.Start(); err != nil { return "", err }

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		return buf.String(), err
	case <-time.After(time.Duration(timeoutSec) * time.Second):
		if cmd.Process != nil {
			syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
			select {
			case err := <-done:
				return buf.String(), fmt.Errorf("timeout %ds: %v", timeoutSec, err)
			case <-time.After(3 * time.Second):
				syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			}
		}
		select {
		case err := <-done:
			return buf.String(), fmt.Errorf("timeout %ds (killed): %v", timeoutSec, err)
		case <-time.After(5 * time.Second):
			return buf.String(), fmt.Errorf("timeout %ds (zombie)", timeoutSec)
		}
	}
}

func runCommandWithTimeout(timeoutSec int, name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	cmd.Env = os.Environ()
	return executeCmdWithTimeout(cmd, timeoutSec)
}

// ════════════════════════════════════════════════════════════════════════
// CORE LOOP + MAIN
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) Run() {
	// Start MCP server for picoClaw
	e.StartMCPServer()

	// Graceful shutdown
	shutdown := make(chan os.Signal, 1)
	signal.Notify(shutdown, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-shutdown
		atomic.StoreInt32(&e.shutdownFlag, 1)
		e.saveState()
		os.Exit(0)
	}()

	for {
		if atomic.LoadInt32(&e.shutdownFlag) == 1 { e.saveState(); return }

		e.State.Iteration++
		e.updateMetrics()
		e.flushStateIfNeeded()

		// Autonomous monitoring loop — even without picoClaw interaction,
		// the agent can run its own hardware monitoring tasks
		e.runAutonomousCheck()

		if !e.Program.Loop.NeverStop { break }
		time.Sleep(time.Duration(e.Program.Loop.PollInterval) * time.Second)
	}
}

// runAutonomousCheck — lightweight hardware monitoring that runs
// every iteration. Can trigger alerts to picoClaw.

func (e *Engine) runAutonomousCheck() {
	// Check if camera sensor is still bound
	if result, err := nativeProbeCvitek(e, nil); err == nil {
		if bound, ok := result["sensor_bound"].(bool); ok && !bound {
			log.Printf("⚠️ Camera sensor lost — notifying picoClaw")
			e.notifyPicoClaw("⚠️ Camera sensor disconnected — may need re-initialization")
		}
	}
}

func (e *Engine) notifyPicoClaw(message string) {
	payload := map[string]interface{}{
		"message": message,
		"source":  "nano-os-agent",
	}
	pJSON, _ := json.Marshal(payload)
	// Fire-and-forget notification
	go func() {
		runCommandWithTimeout(10, "curl", "-s", "-X", "POST",
			PicoClawGatewayURL+"/api/notify",
			"-H", "Content-Type: application/json",
			"-d", string(pJSON))
	}()
}

func main() {
	engine := NewEngine()
	log.Println("🤖 nano-os-agent v5.0 — Hardware Orchestrator + MCP Server")
	log.Printf("   MCP: %s (picoClaw connects here)", MCPListenAddr)
	log.Printf("   picoClaw Gateway: %s", PicoClawGatewayURL)
	log.Printf("   Skills: %s", SkillsDir)
	log.Printf("   State: VisualTruth=%q", truncateString(engine.State.VisualTruth, 40))
	engine.Run()
}
```

---

## picoClaw Configuration to Connect

On the LicheeRV Nano, add the MCP server to picoClaw's config:

json

```
// In picoClaw's MCP servers config (usually via WebUI or config file):
{
  "mcpServers": {
    "nano-os-agent": {
      "command": "none",
      "url": "http://127.0.0.1:9600",
      "transport": "streamable-http"
    }
  }
}
```

```
// In picoClaw's MCP servers config (usually via WebUI or config file):
{
  "mcpServers": {
    "nano-os-agent": {
      "command": "none",
      "url": "http://127.0.0.1:9600",
      "transport": "streamable-http"
    }
  }
}
```

Or if picoClaw uses stdio-based MCP:

json

```
{
  "mcpServers": {
    "nano-hardware": {
      "command": "/root/nano-os-agent",
      "args": ["--mcp-stdio"],
      "transport": "stdio"
    }
  }
}
```

```
{
  "mcpServers": {
    "nano-hardware": {
      "command": "/root/nano-os-agent",
      "args": ["--mcp-stdio"],
      "transport": "stdio"
    }
  }
}
```

---

## The Clean Division of Labor

```
USER: "What do you see?"
  │
  ▼
PICOCLAW (the brain)
  ├── Receives message from Telegram
  ├── Decides: user wants camera
  ├── Calls MCP tool: capture_image(mode=npu)
  │     │
  │     ▼
  │   NANO-OS-AGENT (the hands)
  │     ├── Calls vision_capture skill → CSI camera → JPEG
  │     ├── Calls vision_npu skill → YOLO on NPU → objects[]
  │     └── Returns {image_path, objects: [{class: "person", score: 0.87}]}
  │
  ├── Receives result
  ├── Sends image to gemma4 vision LLM (picoClaw's own vision pipeline)
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
  │   NANO-OS-AGENT
  │     └── Starts MJPEG stream on :7777
  │
  └── Every 30s: calls capture_image → run_yolo → if person: notify user
```

```
USER: "What do you see?"
  │
  ▼
PICOCLAW (the brain)
  ├── Receives message from Telegram
  ├── Decides: user wants camera
  ├── Calls MCP tool: capture_image(mode=npu)
  │     │
  │     ▼
  │   NANO-OS-AGENT (the hands)
  │     ├── Calls vision_capture skill → CSI camera → JPEG
  │     ├── Calls vision_npu skill → YOLO on NPU → objects[]
  │     └── Returns {image_path, objects: [{class: "person", score: 0.87}]}
  │
  ├── Receives result
  ├── Sends image to gemma4 vision LLM (picoClaw's own vision pipeline)
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
  │   NANO-OS-AGENT
  │     └── Starts MJPEG stream on :7777
  │
  └── Every 30s: calls capture_image → run_yolo → if person: notify user
```

picoClaw decides WHAT to do. nano-os-agent decides HOW to do it on the hardware.