package main

// ════════════════════════════════════════════════════════════════════════
// nano-os-agent — Self-Improving Autonomous Research Engine
// Target: SG2002 (LicheeRV Nano, RISC-V C906, NPU 1TOPS)
// ════════════════════════════════════════════════════════════════════════
// Relationship to picoClaw:
//   picoClaw = AI Assistant (Brain)
//   nano-os-agent = Hardware Orchestrator (Nervous System)
//   Communication: Strictly File-Driven (Binary Preference Locking)
// ════════════════════════════════════════════════════════════════════════

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	_ "image/jpeg"
	"io"
	"log"
	"math"
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

const (
	AgentVersion   = "6.8.30"
	BuildTimestamp = "2026-04-21T23:50:00Z"
)

// ════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ════════════════════════════════════════════════════════════════════════

var (
	SkillsDir          = "/root/.picoclaw/workspace/skills"
	TasksDir           = "tasks"
	DefaultCapturePath = "/tmp/capture.jpg"
)

const (
	DefaultFlushInterval = 50
	DefaultContextWindow = 20
	MaxIdleBackoffSecs   = 300
	MaxStateLength       = 300
	MaxImageSizeBytes    = 2 * 1024 * 1024 // 2MB safety limit for LicheeRV Nano (64MB RAM limit)
	ModelInputResolution = 640             // Standard YOLOv8n resolution
	MaxExperimentContext = 5               // last N experiments to include in LLM prompt

	MCPListenAddr        = "0.0.0.0:9600"
	FederatedListenAddr  = ":9601"
	MaxExperiments       = 1000
)

// ════════════════════════════════════════════════════════════════════════
// TYPES — Configuration
// ════════════════════════════════════════════════════════════════════════

type ProgramConfig struct {
	Metadata struct {
		Name    string `yaml:"name"`
		Version string `yaml:"version"`
		Board   string `yaml:"board"`
		SoC     string `yaml:"soc"`
		Arch    string `yaml:"arch"`
		RAMMB   int    `yaml:"ram_mb"`
	} `yaml:"metadata"`
	Goals struct {
		Primary   string   `yaml:"primary"`
		Secondary []string `yaml:"secondary"`
	} `yaml:"goals"`
	ResearchAgenda struct {
		Hypotheses []Hypothesis `yaml:"hypotheses"`
	} `yaml:"research_agenda"`
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
	} `yaml:"strategy"`
	Experiments struct {
		JournalPath       string `yaml:"journal_path"`
		ArchivePath       string `yaml:"archive_path"`
		ArchiveInterval   int    `yaml:"archive_interval"`
		MaxJournalEntries int    `yaml:"max_journal_entries"`
		MaxArchiveEntries int    `yaml:"max_archive_entries"`
		KeepPolicy        string `yaml:"keep_policy"`
	} `yaml:"experiments"`
	SelfImprovement struct {
		Enabled        bool   `yaml:"enabled"`
		EvolveProgram  bool   `yaml:"evolve_program"`
		EvolveTasks    bool   `yaml:"evolve_tasks"`
		EvolveSkills   bool   `yaml:"evolve_skills"`
		EvolveResearch bool   `yaml:"evolve_research"`
		SkillTemplate  string `yaml:"skill_template"`
	} `yaml:"self_improvement"`
	SubAgents struct {
		MaxConcurrent  int      `yaml:"max_concurrent"`
		SpawnOn        []string `yaml:"spawn_on"`
		Communication  string   `yaml:"communication"`
		ResultDir      string   `yaml:"result_dir"`
		TimeoutSeconds int      `yaml:"timeout_seconds"`
	} `yaml:"sub_agents"`
	Loop struct {
		NeverStop      bool `yaml:"never_stop"`
		PollInterval   int  `yaml:"poll_interval"`
		ContextWindow  int  `yaml:"context_window"`
		IdleBackoffMax int  `yaml:"idle_backoff_max"`
		MetricsEveryN  int  `yaml:"metrics_every_n"`
	} `yaml:"loop"`
}

type Hypothesis struct {
	ID         string `yaml:"id"`
	Claim      string `yaml:"claim"`
	Experiment string `yaml:"experiment"`
	Metric     string `yaml:"metric"`
	Status     string `yaml:"status"` // untested, confirmed, refuted, inconclusive
	Priority   int    `yaml:"priority"`
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
	HypothesisRef   string    `yaml:"hypothesis_ref,omitempty"`
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
// TYPES — Perception Atoms
// ════════════════════════════════════════════════════════════════════════

type PerceptionAtom struct {
	ID           int                 `json:"id"`
	Class        string              `json:"class"`
	Confidence   float64             `json:"confidence"`
	Centroid     Point               `json:"centroid"`
	Area         float64             `json:"area"`
	Perimeter    float64             `json:"perimeter"`
	Intensity    float64             `json:"intensity"`
	Color        ColorInfo           `json:"color"`
	Displacement Delta               `json:"displacement,omitempty"`
}

type ColorInfo struct {
	RGB RGBInfo `json:"rgb"`
	HSV HSVInfo `json:"hsv"`
}

type RGBInfo struct {
	R float64 `json:"r"`
	G float64 `json:"g"`
	B float64 `json:"b"`
}

type HSVInfo struct {
	H float64 `json:"h"`
	S float64 `json:"s"`
	V float64 `json:"v"`
}

type Point struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
}

type Delta struct {
	DX float64 `json:"dx"`
	DY float64 `json:"dy"`
}

type RawDetection struct {
	Class      string    `json:"class"`
	Confidence float64   `json:"confidence"`
	Box        []float64 `json:"box"` // [x1, y1, x2, y2]
}

// ════════════════════════════════════════════════════════════════════════
// TYPES — Skill Config
// ════════════════════════════════════════════════════════════════════════

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

// ════════════════════════════════════════════════════════════════════════
// TYPES — State & Experiment Journal
// ════════════════════════════════════════════════════════════════════════

type State struct {
	CurrentTaskID  string                 `json:"current_task_id"`
	Iteration      int                    `json:"iteration"`
	History        []string               `json:"history"`
	Metrics        map[string]string      `json:"metrics"`
	VisualTruth    string                 `json:"visual_truth"`
	CommandTruth   string                 `json:"command_truth"`
	SkillResults   map[string]interface{} `json:"skill_results"`
	RecentFailures []string               `json:"recent_failures"`
	ExperimentNum  int                    `json:"experiment_num"`
	LastTestedIdx  int                    `json:"last_tested_idx"`
}

type ExperimentEntry struct {
	ID            int               `json:"id"`
	Timestamp     string            `json:"timestamp"`
	TaskID        string            `json:"task_id"`
	TaskName      string            `json:"task_name"`
	HypothesisRef string            `json:"hypothesis_ref,omitempty"`
	MetricsBefore map[string]string `json:"metrics_before"`
	MetricsAfter  map[string]string `json:"metrics_after"`
	StepsRun      int               `json:"steps_run"`
	StepsPassed   int               `json:"steps_passed"`
	Duration      string            `json:"duration"`
	Verdict       string            `json:"verdict"` // keep, discard, partial
	Summary       string            `json:"summary"`
}

// ════════════════════════════════════════════════════════════════════════
// TYPES — MCP Protocol
// ════════════════════════════════════════════════════════════════════════

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
	InputSchema map[string]interface{} `json:"inputSchema"`
}

type MCPToolCallParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

// ════════════════════════════════════════════════════════════════════════
// SECURITY
// ════════════════════════════════════════════════════════════════════════

var dangerousWordPatterns = []string{"reboot", "poweroff", "halt", "shutdown"}
var dangerousSubstringPatterns = []string{
	"sudo ", "sudo\t", "/proc/sys", "init 0", "init 6",
	"mkfs.", "dd if=", "dd of=", "> /dev/sd", "> /dev/mmc",
	"chmod 000", "rm -rf /", "rm -rf /*", ":(){:|:&};:",
}
var obfuscationPatterns = []string{
	"base64 --decode", "base64 -d", "eval $(", "perl -e",
	"/dev/tcp/", "/dev/udp/", "nc -e", "xxd -r",
}

// engineFiles are strictly off-limits for mutation by generated tasks/skills
var engineFiles = []string{
	"main.go", "program.yaml", "state.json", "experiments.jsonl",
	"nano-os-agent",
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
		if pos < 0 {
			return false
		}
		absPos := idx + pos
		beforeOK := absPos == 0 || !isAlphanumeric(lower[absPos-1])
		afterOK := absPos+len(target) >= len(lower) || !isAlphanumeric(lower[absPos+len(target)])
		if beforeOK && afterOK {
			return true
		}
		idx = absPos + 1
	}
}

func isAlphanumeric(c byte) bool {
	return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'
}

func extractWriteTargets(cmdStr string) []string {
	var targets []string
	for _, m := range regexp.MustCompile(`>{1,2}\s*(/\S+)`).FindAllStringSubmatch(cmdStr, -1) {
		if m[1] != "/dev/null" {
			targets = append(targets, m[1])
		}
	}
	return targets
}

func (e *Engine) isApproved(cmdStr string) bool {
	lower := strings.ToLower(cmdStr)
	for _, w := range dangerousWordPatterns {
		if isWordMatch(lower, w) {
			return false
		}
	}
	for _, p := range dangerousSubstringPatterns {
		if strings.Contains(lower, strings.ToLower(p)) {
			return false
		}
	}
	for _, p := range obfuscationPatterns {
		if strings.Contains(lower, strings.ToLower(p)) {
			return false
		}
	}
	if strings.Contains(lower, "ulimit") {
		return false
	}
	for _, p := range extractWriteTargets(cmdStr) {
		if e.isReadonly(p) {
			return false
		}
	}
	for _, p := range e.Program.Constraints.RequiresApproval {
		if strings.Contains(lower, strings.ToLower(p)) {
			return false
		}
	}

	// Strictly prohibit writing to engine files
	for _, f := range engineFiles {
		if strings.Contains(cmdStr, f) && (strings.Contains(cmdStr, ">") || strings.Contains(cmdStr, "rm ")) {
			return false
		}
	}

	return true
}

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
	// Engine infrastructure is always readonly to the agent's tasks
	base := filepath.Base(path)
	for _, f := range engineFiles {
		if base == f {
			return true
		}
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
	for _, v := range values {
		if v > 0 {
			return v
		}
	}
	return 60
}

func paramInt(p map[string]interface{}, k string, d int) int {
	if v, ok := p[k].(int); ok && v > 0 {
		return v
	}
	if v, ok := p[k].(float64); ok && v > 0 {
		return int(v)
	}
	if v, ok := p[k].(string); ok {
		if n, e := strconv.Atoi(v); e == nil && n > 0 {
			return n
		}
	}
	return d
}

func paramString(p map[string]interface{}, k, d string) string {
	if v, ok := p[k].(string); ok && v != "" {
		return v
	}
	return d
}

func paramBool(p map[string]interface{}, k string, d bool) bool {
	if v, ok := p[k].(bool); ok {
		return v
	}
	if v, ok := p[k].(string); ok {
		return strings.ToLower(v) == "true"
	}
	return d
}

func truncateString(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}

// ════════════════════════════════════════════════════════════════════════
// NATIVE SKILLS
// ════════════════════════════════════════════════════════════════════════

type NativeSkillFunc func(e *Engine, params map[string]interface{}) (map[string]interface{}, error)

var nativeSkills map[string]NativeSkillFunc

func init() {
	nativeSkills = map[string]NativeSkillFunc{
		"i2c_scan":          nativeI2CScan,
		"probe_cvitek":      nativeProbeCvitek,
		"list_skills":       nativeListSkills,
		"adc_read":          nativeADCRead,
		"pwm_control":       nativePWMControl,
		"npu_inspect":       nativeNPUInspect,
		"dummy_led_verify":  nativeDummyVerify,
		"vision_state_sync": nativeVisionSync,
		"ls_models":         nativeListModels,
		"edit_program":      nativeEditProgram,
	}
}

// ════════════════════════════════════════════════════════════════════════
// AUTO-SKILL GENERATION
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) callSkillWithAutoGenerate(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	result, err := e.callSkill(name, params, timeout)
	if err == nil {
		return result, nil
	}

	// 1. If it's a native hardware skill, we NEVER auto-generate.
	if _, isNative := nativeSkills[name]; isNative {
		return nil, err
	}

	if !e.Program.SelfImprovement.EvolveSkills {
		return nil, fmt.Errorf("skill %q not found and evolution is disabled", name)
	}

	log.Printf("🧠 Skill %q not found. Waiting for picoClaw (Brain) to provide it via files...", name)
	return nil, fmt.Errorf("skill %q missing: standing by for file-driven evolution", name)
}

func (e *Engine) executeExternalSkill(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	config, err := e.loadSkillConfig(name)
	if err != nil {
		return nil, fmt.Errorf("skill %q not found: %v", name, err)
	}
	t := resolveTimeout(timeout, config.Timeout, e.Program.Constraints.MaxTimeout)
	params = e.applySkillDefaults(config, params)

	var result map[string]interface{}
	switch config.ExecType {
	case "shell":
		result, err = e.executeShellSkill(config, params, t)
	case "python":
		result, err = e.executePythonSkill(config, params, t)
	case "api":
		result, err = e.executeAPISkill(config, params, t)
	default:
		return nil, fmt.Errorf("unknown exec_type %q for skill %s", config.ExecType, name)
	}
	if result != nil {
		e.mu.Lock()
		e.State.SkillResults[name] = result
		e.mu.Unlock()
		e.markStateDirty()
	}
	return result, err
}



func (e *Engine) verifyGeneratedSkill(script string) bool {
	lower := strings.ToLower(script)
	// Block destructive patterns and engine file access
	for _, p := range dangerousSubstringPatterns {
		if strings.Contains(lower, strings.ToLower(p)) {
			return false
		}
	}
	for _, f := range engineFiles {
		if strings.Contains(lower, f) {
			return false
		}
	}
	// Must contain a JSON output pattern to be valid skill
	if !strings.Contains(script, "{") || !strings.Contains(script, "}") {
		return false
	}
	return true
}

func extractJSON(s string) string {
	start := strings.Index(s, "{")
	end := strings.LastIndex(s, "}")
	if start == -1 || end == -1 || start >= end {
		return s
	}
	return s[start : end+1]
}

// ════════════════════════════════════════════════════════════════════════
// FEDERATED SERVER
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) StartFederatedServer() {
	mux := http.NewServeMux()
	mux.HandleFunc("/federated/push", e.handleFederatedPush)
	mux.HandleFunc("/federated/pull", e.handleFederatedPull)
	mux.HandleFunc("/contagion/alert", e.handleContagionAlert)

	go func() {
		log.Printf("🌐 Starting Federated Server on %s", FederatedListenAddr)
		if err := http.ListenAndServe(FederatedListenAddr, mux); err != nil {
			log.Printf("⚠️ Federated server error: %v", err)
		}
	}()
}

func (e *Engine) handleFederatedPush(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB safety limit
	storeDir := "/tmp/federated_incoming"
	os.MkdirAll(storeDir, 0755)
	filename := filepath.Join(storeDir, fmt.Sprintf("push_%d.json", time.Now().UnixNano()))
	os.WriteFile(filename, body, 0644)
	w.WriteHeader(200)
	fmt.Fprintf(w, `{"status":"accepted"}`)
}

func (e *Engine) handleFederatedPull(w http.ResponseWriter, r *http.Request) {
	modelPath := "/root/models/residual_local.json"
	data, err := os.ReadFile(modelPath)
	if err != nil {
		w.WriteHeader(404)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(data)
}

func (e *Engine) handleContagionAlert(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB safety limit
	alertsDir := "/tmp/contagion_alerts"
	os.MkdirAll(alertsDir, 0755)
	filename := filepath.Join(alertsDir, fmt.Sprintf("alert_%d.json", time.Now().UnixNano()))
	os.WriteFile(filename, body, 0644)
	w.WriteHeader(200)
	fmt.Fprintf(w, `{"status":"stored"}`)
}

func nativeI2CScan(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	bus := paramString(params, "bus", "1")
	out, err := runCommandWithTimeout(10, "i2cdetect", "-y", bus)
	count := 0
	var addrs []string
	for _, line := range strings.Split(out, "\n") {
		for _, f := range strings.Fields(line) {
			if f != "--" && f != "UU" && len(f) == 2 {
				if _, e := strconv.ParseInt(f, 16, 64); e == nil {
					count++
					addrs = append(addrs, "0x"+f)
				}
			}
		}
	}
	return map[string]interface{}{"count": count, "addresses": addrs, "raw": out}, err
}


func (e *Engine) readAndAnalyzeImage(imagePath string, detections []RawDetection, samplingStep int) []PerceptionAtom {
	stat, err := os.Stat(imagePath)
	if err != nil {
		log.Printf("⚠️ Perception fail (stat): %v", err)
		return nil
	}
	if stat.Size() > int64(MaxImageSizeBytes) {
		log.Printf("⚠️ Perception rejected: file %s (%d bytes) exceeds MaxImageSizeBytes (%d)", imagePath, stat.Size(), MaxImageSizeBytes)
		return nil
	}

	f, err := os.Open(imagePath)
	if err != nil {
		log.Printf("⚠️ Perception fail (open): %v", err)
		return nil
	}
	defer f.Close()

	// Use LimitReader as a secondary guardrail
	lr := io.LimitReader(f, int64(MaxImageSizeBytes))
	img, _, err := image.Decode(lr)
	if err != nil {
		log.Printf("⚠️ Decode fail: %v", err)
		return nil
	}

	if ModelInputResolution <= 0 {
		log.Printf("⚠️ ModelInputResolution is invalid (0 or negative)")
		return nil
	}

	atoms := make([]PerceptionAtom, 0)
	for i, d := range detections {
		if len(d.Box) < 4 {
			log.Printf("⚠️ Malformed box in detection %d: %v", i, d.Box)
			continue
		}
		
		x1, y1, x2, y2 := int(d.Box[0]), int(d.Box[1]), int(d.Box[2]), int(d.Box[3])
		
		atom := PerceptionAtom{
			ID:         i + 1,
			Class:      d.Class,
			Confidence: d.Confidence,
			Centroid: Point{
				X: (d.Box[0] + d.Box[2]) / 2 / float64(ModelInputResolution),
				Y: (d.Box[1] + d.Box[3]) / 2 / float64(ModelInputResolution),
			},
			Area:      math.Abs((d.Box[2] - d.Box[0]) * (d.Box[3] - d.Box[1])) / float64(ModelInputResolution*ModelInputResolution),
			Perimeter: 2 * (math.Abs(d.Box[2]-d.Box[0]) + math.Abs(d.Box[3]-d.Box[1])) / float64(ModelInputResolution),
		}

		intensity, colors := analyzeRegion(img, x1, y1, x2, y2, samplingStep)
		atom.Intensity = intensity
		atom.Color = colors

		// Calculate displacement (motion vector)
		e.mu.Lock()
		if last, ok := e.lastCentroids[d.Class]; ok {
			atom.Displacement = Delta{
				DX: atom.Centroid.X - last.X,
				DY: atom.Centroid.Y - last.Y,
			}
		}
		// Update memory for next frame
		e.lastCentroids[d.Class] = atom.Centroid
		e.mu.Unlock()
		
		atoms = append(atoms, atom)
	}
	return atoms
}

func analyzeRegion(img image.Image, x1, y1, x2, y2, step int) (float64, ColorInfo) {
	bounds := img.Bounds()
	if x1 < bounds.Min.X { x1 = bounds.Min.X }
	if y1 < bounds.Min.Y { y1 = bounds.Min.Y }
	if x2 > bounds.Max.X { x2 = bounds.Max.X }
	if y2 > bounds.Max.Y { y2 = bounds.Max.Y }

	var totalI, totalR, totalG, totalB uint64
	var count uint64

	// Default step is 4 (1/16 pixels).
	if step < 1 {
		step = 1
	}
	for y := y1; y < y2; y += step {
		for x := x1; x < x2; x += step {
			r, g, b, _ := img.At(x, y).RGBA()
			r8, g8, b8 := uint8(r>>8), uint8(g>>8), uint8(b>>8)
			
			totalR += uint64(r8)
			totalG += uint64(g8)
			totalB += uint64(b8)
			totalI += uint64(r8+g8+b8) / 3
			count++
		}
	}

	if count == 0 {
		return 0, ColorInfo{}
	}

	avgR := float64(totalR) / float64(count)
	avgG := float64(totalG) / float64(count)
	avgB := float64(totalB) / float64(count)
	
	h, s, v := rgbToHsv(avgR, avgG, avgB)

	return float64(totalI) / float64(count), ColorInfo{
		RGB: RGBInfo{R: avgR, G: avgG, B: avgB},
		HSV: HSVInfo{H: h, S: s, V: v},
	}
}

func rgbToHsv(r, g, b float64) (h, s, v float64) {
	min := math.Min(math.Min(r, g), b)
	max := math.Max(math.Max(r, g), b)
	v = max / 255.0
	delta := max - min

	if max > 0 {
		s = delta / max
	} else {
		return 0, 0, 0
	}

	if delta == 0 {
		return 0, s, v
	}

	if r == max {
		h = (g - b) / delta
	} else if g == max {
		h = 2 + (b-r)/delta
	} else {
		h = 4 + (r-g)/delta
	}

	h *= 60
	if h < 0 {
		h += 360
	}
	return h, s, v
}

func nativeNPUInspect(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	requestedModel := paramString(params, "model_path", "/root/models/yolov8n_coco_320.cvimodel")
	modelPath := e.resolveModelPath(requestedModel)
	binPath := e.resolveBinaryPath("cvimodel_tool")
	
	// Format: cvimodel_tool --action <ACTION> --input <INPUT_FILE>
	args := []string{"--action", "info", "--input"}
	if modelPath != "" {
		args = append(args, modelPath)
	} else {
		return nil, fmt.Errorf("model_path required for NPU inspection")
	}

	// Model Validation (Safe)
	if info, err := os.Stat(modelPath); err != nil {
		return nil, fmt.Errorf("NPU model file %s not found. Check your board installation.", modelPath)
	} else if info.Size() < 100 {
		return nil, fmt.Errorf("NPU model file %s is invalid/too small (size: %d bytes)", modelPath, info.Size())
	}

	cmd := exec.Command(binPath, args...)
	sdkPatch := "/root/libs_patch"
	cmd.Env = append(os.Environ(), 
		"LD_LIBRARY_PATH="+sdkPatch+"/lib:"+sdkPatch+"/middleware_v2:"+sdkPatch+"/middleware_v2_3rd:"+sdkPatch+"/tpu_sdk_libs:"+sdkPatch+":"+sdkPatch+"/opencv",
	)

	out, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("cvimodel_tool failed: %v, output: %s", err, string(out))
	}

	return map[string]interface{}{
		"info": string(out),
		"bin": binPath,
	}, nil
}

func nativeProbeCvitek(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	result := make(map[string]interface{})
	
	// 1. Check VI (Video Input) - Try multiple vendor paths
	viPaths := []string{"/proc/cvitek/vi", "/proc/soph/vi", "/proc/vi"}
	for _, path := range viPaths {
		if data, err := os.ReadFile(path); err == nil {
			log.Printf("🔎 Probing %s...", path)
			result["vi_raw"] = strings.TrimSpace(string(data))
			result["sensor_bound"] = strings.Contains(string(data), "DevID") || strings.Contains(string(data), "bound")
			break
		}
	}
	if _, ok := result["sensor_bound"]; !ok {
		result["sensor_bound"] = false
		result["vi_error"] = "no VI proc file found"
	}

	// 2. Check MIPI-RX (Physical Interface)
	mipiPaths := []string{"/proc/cvitek/mipi-rx", "/proc/soph/mipi-rx", "/proc/mipi-rx"}
	for _, path := range mipiPaths {
		if data, err := os.ReadFile(path); err == nil {
			log.Printf("🔎 Probing %s...", path)
			result["mipi_raw"] = strings.TrimSpace(string(data))
			result["mipi_stable"] = strings.Contains(string(data), "stable") || strings.Contains(string(data), "OK") || strings.Contains(string(data), "YES")
			break
		}
	}

	// 3. Check TDL SDK / Native NPU Bins (v6.8.29 Dynamic Search)
	candidateBins := []string{"cvi_tdl_yolo", "sample_yolov8", "yolo_detect", "sensor_test"}
	foundBins := make(map[string]string)
	
	for _, b := range candidateBins {
		path := e.resolveBinaryPath(b)
		if path != "" {
			foundBins[b] = path
		}
	}

	if len(foundBins) > 0 {
		result["tdl_installed"] = true
		result["tdl_bins"] = foundBins
		log.Printf("🔎 Discovered Native SDK Bins: %v", foundBins)
	} else {
		result["tdl_installed"] = false
		log.Printf("⚠️ No native NPU binaries found (checked SDK paths & PATH).")
	}

	return result, nil
}

func nativeVisionSync(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	// Native implementation of vision truth loop (Search/Rescue + Vision Force)
	imagePath := paramString(params, "image_path", "/tmp/sync_frame.jpg")
	
	// 1. Capture Frame FIRST
	_, err := e.executeExternalSkill("capture_image", map[string]interface{}{"output_path": imagePath}, 30)
	if err != nil {
		return nil, fmt.Errorf("sync_truth capture failed: %v", err)
	}

	// 2. Run Analysis
	return e.callSkill("run_yolo", params, 90)
}

func nativeDummyVerify(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	log.Printf("🧪 [NATIVE] dummy_led_verify executed")
	return map[string]interface{}{"status": "ok", "led": "verified"}, nil
}

func nativeListModels(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	searchDirs := []string{"/root/models_for_benchmark", "/root/models", "."}
	found := []string{}
	for _, dir := range searchDirs {
		matches, _ := filepath.Glob(filepath.Join(dir, "*.cvimodel"))
		for _, m := range matches {
			if info, err := os.Stat(m); err == nil {
				found = append(found, fmt.Sprintf("%s (%d MB)", m, info.Size()/(1024*1024)))
			}
		}
	}
	return map[string]interface{}{"models": found}, nil
}

func (e *Engine) findADCPath(channel string) string {
	// Sophgo/LicheeRV Native Probing (v6.7.4)
	specialPaths := []string{
		"/sys/class/cvi-saradc/cvi-saradc0/device/cv_saradc",
		"/sys/devices/platform/soc/4410000.adc/cvi-adc/in_voltage" + channel + "_raw",
	}
	for _, p := range specialPaths {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}

	globs := []string{
		"/sys/class/cvi-adc/cvi-adc*/in_voltage" + channel + "_raw",
		"/sys/bus/iio/devices/iio:device*/in_voltage" + channel + "_raw",
		"/sys/class/adc/*/in_voltage" + channel + "_raw",
	}
	for _, g := range globs {
		matches, _ := filepath.Glob(g)
		if len(matches) > 0 {
			return matches[0]
		}
	}
	return "/sys/bus/iio/devices/iio:device0/in_voltage" + channel + "_raw" // Ultimate fallback
}

func nativeADCRead(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	channel := paramString(params, "channel", "0")
	path := e.findADCPath(channel)
	
	// Check if this is the special cvi-saradc device that requires the "Echo-Read" protocol
	if strings.Contains(path, "cv_saradc") {
		// Protocol: Open R/W -> Write Channel -> Sleep -> Read Value
		file, err := os.OpenFile(path, os.O_RDWR, 0)
		if err != nil {
			return nil, fmt.Errorf("ADC lock-in failed: could not open %s in R/W mode: %v", path, err)
		}
		defer file.Close()

		// Write channel (selection)
		if _, err := file.WriteString(channel + "\n"); err != nil {
			return nil, fmt.Errorf("ADC selection failed: could not write channel %s to %s: %v", channel, path, err)
		}

		// MANDATORY STABILIZATION DELAY (v6.7.5)
		// SARADC hardware needs time to switch mux and sample voltage
		time.Sleep(25 * time.Millisecond)

		// Seek back to start to read the result
		if _, err := file.Seek(0, 0); err != nil {
			return nil, fmt.Errorf("ADC read preparation failed: could not seek in %s: %v", path, err)
		}

		// Read the raw value
		data, err := io.ReadAll(file)
		if err != nil {
			return nil, fmt.Errorf("ADC fetch failed: could not read value from %s: %v", path, err)
		}
		
		val := strings.TrimSpace(string(data))
		return map[string]interface{}{
			"channel": channel,
			"raw":     val,
			"path":    path,
			"protocol": "echo-read-locked",
		}, nil
	}

	// Standard IIO Fallback
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read ADC channel %s (probed %s): %v", channel, path, err)
	}
	
	val := strings.TrimSpace(string(data))
	return map[string]interface{}{
		"channel": channel,
		"raw":     val,
		"path":    path,
		"protocol": "standard",
	}, nil
}

func nativePWMControl(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	channel := paramString(params, "channel", "0")
	duty := paramString(params, "duty", "500000") // 50% of 1ms period
	period := paramString(params, "period", "1000000") // 1ms
	enable := paramString(params, "enable", "1")

	base := fmt.Sprintf("/sys/class/pwm/pwmchip0/pwm%s", channel)
	
	// Ensure period is set first
	_ = os.WriteFile(filepath.Join(base, "period"), []byte(period), 0644)
	_ = os.WriteFile(filepath.Join(base, "duty_cycle"), []byte(duty), 0644)
	_ = os.WriteFile(filepath.Join(base, "enable"), []byte(enable), 0644)

	return map[string]interface{}{
		"channel": channel,
		"period":  period,
		"duty":    duty,
		"enable":  enable,
		"status":  "ok",
	}, nil
}

func nativeListSkills(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	seen := map[string]bool{}
	names := []string{}
	for name := range nativeSkills {
		names = append(names, name)
		seen[name] = true
	}
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

func nativeEditProgram(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	if !e.Program.SelfImprovement.EvolveProgram {
		return nil, fmt.Errorf("evolve_program is disabled in program.yaml")
	}
	path, _ := params["path"].(string)
	content, _ := params["content"].(string)
	if path == "" || content == "" {
		return nil, fmt.Errorf("missing path or content")
	}
	// Security: resolve to absolute and verify it's within SkillsDir
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("invalid path: %v", err)
	}
	absSkills, _ := filepath.Abs(SkillsDir)
	if !strings.HasPrefix(absPath, absSkills+string(filepath.Separator)) {
		return nil, fmt.Errorf("edit_program: path %s is outside skills directory %s", absPath, absSkills)
	}
	// Safety: only allow certain file extensions
	allowed := false
	for _, ext := range []string{".md", ".sh", ".py", ".yaml"} {
		if strings.HasSuffix(absPath, ext) {
			allowed = true
			break
		}
	}
	if !allowed {
		return nil, fmt.Errorf("file type not allowed for editing: %s", absPath)
	}

	err = os.WriteFile(absPath, []byte(content), 0644)
	if err != nil {
		return nil, err
	}
	return map[string]interface{}{"status": "success", "file": absPath}, nil
}



// ════════════════════════════════════════════════════════════════════════
// ENGINE
// ════════════════════════════════════════════════════════════════════════

type Engine struct {
	Program       ProgramConfig
	State         State
	shutdownFlag  int32
	skillCache    map[string]*SkillConfig
	skillMtime    map[string]time.Time // mtime of cached SKILL.md files
	lastCentroids map[string]Point
	stateDirty    bool
	flushCounter  int
	flushInterval int
	idleCount     int
	subAgentPIDs  map[int]string // pid → task file
	mu            sync.Mutex
	actingHypothesis string // ID of hypothesis currently being researched
	workingShell string // Validated path to busybox or sh
	startTime    time.Time
}

func findWorkingShell() string {
	// Priority order: LicheeRV standard BusyBox, then system sh
	candidates := []string{"/bin/busybox", "/usr/bin/busybox", "/bin/sh", "sh"}
	for _, c := range candidates {
		var cmd *exec.Cmd
		if strings.Contains(c, "busybox") {
			cmd = exec.Command(c, "sh", "-c", "echo OK")
		} else {
			cmd = exec.Command(c, "-c", "echo OK")
		}

		if out, err := cmd.CombinedOutput(); err == nil && strings.TrimSpace(string(out)) == "OK" {
			return c
		}
	}
	return "sh" // Final fallback
}

func NewEngine() *Engine {
	e := &Engine{
		skillCache:    make(map[string]*SkillConfig),
		skillMtime:    make(map[string]time.Time),
		lastCentroids: make(map[string]Point),
		flushInterval: DefaultFlushInterval,
		subAgentPIDs:  make(map[int]string),
		workingShell:  findWorkingShell(),
		startTime:     time.Now(),
	}
	e.loadEnv()
	e.loadProgram()
	e.loadState()

	if e.Program.Loop.ContextWindow <= 0 {
		e.Program.Loop.ContextWindow = DefaultContextWindow
	}
	if e.Program.Constraints.MaxMemoryMB <= 0 {
		e.Program.Constraints.MaxMemoryMB = 64
	}
	if e.Program.Loop.PollInterval <= 0 {
		e.Program.Loop.PollInterval = 5
	}
	if e.Program.Experiments.JournalPath == "" {
		e.Program.Experiments.JournalPath = "/tmp/experiments.jsonl"
	}
	if e.Program.Experiments.ArchivePath == "" {
		e.Program.Experiments.ArchivePath = "/root/.picoclaw/workspace/experiments/archive.jsonl"
	}
	if e.Program.Experiments.ArchiveInterval <= 0 {
		e.Program.Experiments.ArchiveInterval = 10
	}
	if e.Program.SubAgents.ResultDir == "" {
		e.Program.SubAgents.ResultDir = "/tmp/subagent_results"
	}
	if e.Program.SubAgents.MaxConcurrent <= 0 {
		e.Program.SubAgents.MaxConcurrent = 2
	}
	if e.Program.Loop.MetricsEveryN <= 0 {
		e.Program.Loop.MetricsEveryN = 3
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

	// Binary-Relative Discovery (Source of Truth)
	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)
	
	// Priority 1: Relative to binary
	if info, err := os.Stat(filepath.Join(exeDir, "skills")); err == nil && info.IsDir() {
		SkillsDir = filepath.Join(exeDir, "skills")
	} else if _, err := os.Stat(SkillsDir); err != nil {
		paths := []string{"skills", "/root/skills", "/usr/share/nora/skills"}
		for _, p := range paths {
			if info, err := os.Stat(p); err == nil && info.IsDir() {
				SkillsDir, _ = filepath.Abs(p)
				break
			}
		}
	}

	if info, err := os.Stat(filepath.Join(exeDir, "tasks")); err == nil && info.IsDir() {
		TasksDir = filepath.Join(exeDir, "tasks")
	} else if _, err := os.Stat(TasksDir); err != nil {
		paths := []string{"tasks", "/root/tasks"}
		for _, p := range paths {
			if info, err := os.Stat(p); err == nil && info.IsDir() {
				TasksDir, _ = filepath.Abs(p)
				break
			}
		}
	}

	// Ensure directories exist
	os.MkdirAll(TasksDir, 0755)
	os.MkdirAll(SkillsDir, 0755)
	os.MkdirAll(filepath.Dir(e.Program.Experiments.ArchivePath), 0755)
	os.MkdirAll(e.Program.SubAgents.ResultDir, 0755)

	// ═══ Structured Boot Fingerprint (v6.8.30) ═══
	log.Printf("═══ nano-os-agent v%s ═══", AgentVersion)
	log.Printf("   Build:  %s", BuildTimestamp)
	if e.workingShell != "" {
		log.Printf("   Shell:  %s", e.workingShell)
	} else {
		log.Printf("⚠️  Shell:  FAILED — using system default sh")
		e.workingShell = "sh"
	}

	e.checkVideoDevs()
	e.checkMemoryResource()
	e.checkSensorConfig()
	log.Printf("   Board: %s (%s) | RAM: %dMB | MemLimit: %dMB",
		e.Program.Metadata.Board, e.Program.Metadata.SoC,
		e.Program.Metadata.RAMMB, e.Program.Constraints.MaxMemoryMB)
	log.Printf("   Tasks dir: %s", TasksDir)
	log.Printf("   Skills dir: %s", SkillsDir)

	// Diagnostic: Count and conditionally reset tasks
	taskFiles, _ := os.ReadDir(TasksDir)
	log.Printf("   Task files found: %d", len(taskFiles))
	for _, f := range taskFiles {
		if strings.HasSuffix(f.Name(), ".yaml") || strings.HasSuffix(f.Name(), ".yml") {
			path := filepath.Join(TasksDir, f.Name())
			data, err := os.ReadFile(path)
			if err == nil {
				content := string(data)
				// Only reset if it's NOT already pending
				if strings.Contains(content, "status: completed") || strings.Contains(content, "status: failed") {
					content = regexp.MustCompile(`(?m)^(\s*)status:.*$`).ReplaceAllString(content, `${1}status: pending`)
					os.WriteFile(path, []byte(content), 0644)
					log.Printf("     - %s [RESET]", f.Name())
				}
			}
		}
	}
	log.Printf("   Hypotheses: %d", len(e.Program.ResearchAgenda.Hypotheses))
	return e
}

// ── Loading / Saving ────────────────────────────────────────────────

func (e *Engine) loadEnv() {


	for _, p := range []string{".env", "/root/.env"} {
		if err := parseEnvFile(p); err == nil {
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
	scanner.Buffer(make([]byte, 0), 4096)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
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
	if err != nil {
		log.Printf("⚠️ program.yaml missing, loading minimal fallback: %v", err)
		e.Program.Metadata.Name = "default-agent"
		e.Program.Constraints.MaxMemoryMB = 64
		e.Program.Constraints.MaxTimeout = 60
		return
	}
	if err := yaml.Unmarshal(data, &e.Program); err != nil {
		log.Printf("⚠️ program.yaml parse failed, using minimal defaults: %v", err)
	}
	// Safety: ensure a baseline memory limit if unspecified
	if e.Program.Constraints.MaxMemoryMB <= 0 {
		e.Program.Constraints.MaxMemoryMB = 64
	}
}

func (e *Engine) loadState() {
	data, err := os.ReadFile("state.json")
	if err != nil {
		e.State = State{
			Metrics: make(map[string]string), History: []string{},
			SkillResults: make(map[string]interface{}), RecentFailures: []string{},
		}
		return
	}
	if err := json.Unmarshal(data, &e.State); err != nil {
		log.Printf("⚠️ state.json corrupt, starting fresh: %v", err)
		e.State = State{
			Metrics: make(map[string]string), History: []string{},
			SkillResults: make(map[string]interface{}), RecentFailures: []string{},
		}
	}
}

func (e *Engine) saveState() {
	e.mu.Lock()
	data, err := json.MarshalIndent(e.State, "", "  ")
	e.stateDirty = false
	e.flushCounter = 0
	e.mu.Unlock()
	if err != nil {
		log.Printf("⚠️ marshal state: %v", err)
		return
	}
	tmpPath := "state.json.tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		log.Printf("⚠️ write state: %v", err)
		return
	}
	if err := os.Rename(tmpPath, "state.json"); err != nil {
		os.Remove(tmpPath)
	}
}

func (e *Engine) markStateDirty() {
	e.mu.Lock()
	e.stateDirty = true
	e.mu.Unlock()
}
func (e *Engine) flushStateIfNeeded() {
	e.mu.Lock()
	if !e.stateDirty {
		e.mu.Unlock()
		return
	}
	e.flushCounter++
	should := e.flushCounter >= e.flushInterval
	e.mu.Unlock()
	if should {
		e.saveState()
	}
}

func (e *Engine) appendResult(taskID, stepID, status, description string) {
	f, err := os.OpenFile("results.tsv", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	ts := time.Now().Format("15:04:05")
	f.WriteString(fmt.Sprintf("%s\t%s\t%s\t%s\t%s\n", ts, taskID, stepID, status, description))
}

// writeHeartbeat writes a lightweight status file for external monitoring (v6.8.30)
func (e *Engine) writeHeartbeat(lastTaskID string) {
	e.mu.Lock()
	iter := e.State.Iteration
	e.mu.Unlock()
	hb := fmt.Sprintf(`{"pid":%d,"version":"%s","iteration":%d,"last_task":"%s","uptime_s":%d,"ts":"%s"}`,
		os.Getpid(), AgentVersion, iter, lastTaskID,
		int(time.Since(e.startTime).Seconds()),
		time.Now().Format(time.RFC3339))
	os.WriteFile("/tmp/nano-os-agent.heartbeat", []byte(hb+"\n"), 0644)
}

// ════════════════════════════════════════════════════════════════════════
// EXPERIMENT JOURNAL — the core autoresearch innovation
// ════════════════════════════════════════════════════════════════════════
// Every task execution is wrapped in a before/after metrics snapshot.
// Results are written to append-only JSONL (fast, no overwrites).
// Periodically archived to SD card for persistence across reboots.

func (e *Engine) snapshotMetrics() map[string]string {
	snap := make(map[string]string)
	e.mu.Lock()
	for k, v := range e.State.Metrics {
		snap[k] = v
	}
	e.mu.Unlock()
	return snap
}

func (e *Engine) appendExperiment(entry ExperimentEntry) {
	data, err := json.Marshal(entry)
	if err != nil {
		return
	}
	data = append(data, '\n')

	// Write to tmpfs journal
	f, err := os.OpenFile(e.Program.Experiments.JournalPath,
		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		f.Write(data)
		f.Close()
	}

	// Periodic archive to SD card
	e.mu.Lock()
	num := e.State.ExperimentNum
	e.mu.Unlock()

	if num > 0 && num%e.Program.Experiments.ArchiveInterval == 0 {
		e.archiveExperiments()
	}
}

func (e *Engine) archiveExperiments() {
	srcData, err := os.ReadFile(e.Program.Experiments.JournalPath)
	if err != nil || len(srcData) == 0 {
		return
	}
	os.MkdirAll(filepath.Dir(e.Program.Experiments.ArchivePath), 0755)
	f, err := os.OpenFile(e.Program.Experiments.ArchivePath,
		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("⚠️ archive write failed: %v", err)
		return
	}
	f.Write(srcData)
	f.Close()
	log.Printf("💾 Archived %d bytes to %s", len(srcData), e.Program.Experiments.ArchivePath)
}

func (e *Engine) loadRecentExperiments(n int) []ExperimentEntry {
	var entries []ExperimentEntry
	// Try journal first, then archive
	for _, path := range []string{e.Program.Experiments.JournalPath, e.Program.Experiments.ArchivePath} {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
			if line == "" {
				continue
			}
			var entry ExperimentEntry
			if err := json.Unmarshal([]byte(line), &entry); err == nil {
				entries = append(entries, entry)
			}
		}
	}
	if len(entries) > n {
		entries = entries[len(entries)-n:]
	}
	return entries
}

func (e *Engine) scoreExperiment(before, after map[string]string) string {
	improved := 0
	degraded := 0
	for key, afterVal := range after {
		beforeVal, ok := before[key]
		if !ok || afterVal == beforeVal {
			continue
		}
		// Simple heuristic: if value changed from "error"/"false" to something else → improved
		if beforeVal == "error" && afterVal != "error" {
			improved++
		} else if afterVal == "error" && beforeVal != "error" {
			degraded++
		} else if beforeVal == "false" && afterVal == "true" {
			improved++
		} else if beforeVal == "true" && afterVal == "false" {
			degraded++
		} else {
			// Try numeric comparison
			bNum, bErr := strconv.ParseFloat(beforeVal, 64)
			aNum, aErr := strconv.ParseFloat(afterVal, 64)
			if bErr == nil && aErr == nil && aNum > bNum {
				improved++
			} else if bErr == nil && aErr == nil && aNum < bNum {
				degraded++
			}
		}
	}
	if improved > 0 && degraded == 0 {
		return "keep"
	}
	if degraded > improved {
		return "discard"
	}
	if improved > 0 {
		return "partial"
	}
	return "neutral"
}

// ════════════════════════════════════════════════════════════════════════
// RESEARCH AGENDA — hypothesis-driven exploration
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) pickNextHypothesis() *Hypothesis {
	e.mu.Lock()
	defer e.mu.Unlock()

	if e.actingHypothesis != "" {
		return nil
	}

	count := len(e.Program.ResearchAgenda.Hypotheses)
	if count == 0 {
		return nil
	}

	// Try hypotheses in a rotating sequence starting from LastTestedIdx
	for i := 0; i < count; i++ {
		idx := (e.State.LastTestedIdx + 1 + i) % count
		h := &e.Program.ResearchAgenda.Hypotheses[idx]
		if h.Status == "pending" || h.Status == "untested" || h.Status == "" {
			e.State.LastTestedIdx = idx
			return h
		}
	}
	return nil
}

func (e *Engine) updateHypothesisStatus(id, status string) {
	for i := range e.Program.ResearchAgenda.Hypotheses {
		if e.Program.ResearchAgenda.Hypotheses[i].ID == id {
			e.Program.ResearchAgenda.Hypotheses[i].Status = status
			log.Printf("🔬 Hypothesis %s → %s", id, status)
			break
		}
	}
}

// ════════════════════════════════════════════════════════════════════════
// SUB-AGENT SPAWNER
// ════════════════════════════════════════════════════════════════════════
// Sub-agents run a single task file, write results to a JSON file, exit.
// Parent polls for result files and collects them.

func (e *Engine) spawnSubAgent(taskFile string) error {
	e.mu.Lock()
	activeCount := len(e.subAgentPIDs)
	e.mu.Unlock()

	if activeCount >= e.Program.SubAgents.MaxConcurrent {
		return fmt.Errorf("max sub-agents (%d) reached", e.Program.SubAgents.MaxConcurrent)
	}

	resultFile := filepath.Join(e.Program.SubAgents.ResultDir,
		fmt.Sprintf("result_%d.json", time.Now().UnixNano()))

	// Re-exec ourselves with --sub-agent flag
	selfPath, _ := os.Executable()
	if selfPath == "" {
		selfPath = "./nano-os-agent"
	}

	cmd := exec.Command(selfPath, "--sub-agent", "--task", taskFile, "--result", resultFile)
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("sub-agent spawn failed: %v", err)
	}

	pid := cmd.Process.Pid
	e.mu.Lock()
	e.subAgentPIDs[pid] = resultFile
	e.mu.Unlock()

	log.Printf("🔀 Spawned sub-agent PID %d for %s → %s", pid, taskFile, resultFile)

	// Monitor in background
	go func() {
		timeout := time.Duration(e.Program.SubAgents.TimeoutSeconds) * time.Second
		if timeout <= 0 {
			timeout = 120 * time.Second
		}
		done := make(chan error, 1)
		go func() { done <- cmd.Wait() }()

		select {
		case err := <-done:
			if err != nil {
				log.Printf("⚠️ Sub-agent PID %d exited: %v", pid, err)
			} else {
				log.Printf("✅ Sub-agent PID %d completed", pid)
			}
		case <-time.After(timeout):
			log.Printf("⏰ Sub-agent PID %d timed out, killing", pid)
			syscall.Kill(-pid, syscall.SIGKILL)
			<-done
		}
		e.mu.Lock()
		delete(e.subAgentPIDs, pid)
		e.mu.Unlock()
		e.collectSubAgentResult(resultFile)
	}()

	return nil
}

func (e *Engine) collectSubAgentResult(resultFile string) {
	data, err := os.ReadFile(resultFile)
	if err != nil {
		return
	}
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		return
	}
	log.Printf("📬 Collected sub-agent result from %s: verdict=%v",
		resultFile, result["verdict"])
	os.Remove(resultFile)
}

// ════════════════════════════════════════════════════════════════════════
// MCP SERVER
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) StartMCPServer() {
	listener, err := net.Listen("tcp", MCPListenAddr)
	if err != nil {
		log.Fatalf("❌ MCP listen failed on %s: %v", MCPListenAddr, err)
	}
	log.Printf("🔌 MCP server listening on %s", MCPListenAddr)
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				continue
			}
			go e.handleMCPConnection(conn)
		}
	}()
}

func (e *Engine) handleMCPConnection(conn net.Conn) {
	defer conn.Close()
	// Set an idle deadline to prevent goroutine leaks from abandoned connections.
	// 10-minute timeout for interactive sessions.
	conn.SetDeadline(time.Now().Add(10 * time.Minute))

	decoder := json.NewDecoder(conn)
	encoder := json.NewEncoder(conn)
	for {
		var req MCPRequest
		if err := decoder.Decode(&req); err != nil {
			if err != io.EOF {
				log.Printf("⚠️ MCP connection error: %v", err)
			}
			return
		}
		// Reset deadline on interaction
		conn.SetDeadline(time.Now().Add(10 * time.Minute))
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
				"tools":     map[string]interface{}{"listChanged": true},
				"resources": map[string]interface{}{"listChanged": true},
			},
			"serverInfo": map[string]interface{}{
				"name": "nano-os-agent", "version": "6.0",
			},
		}
	case "notifications/initialized":
		resp.Result = map[string]interface{}{}
	case "tools/list":
		resp.Result = map[string]interface{}{"tools": e.getMCPTools()}
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
			resultJSON, _ := json.Marshal(result)
			resp.Result = map[string]interface{}{
				"content": []map[string]interface{}{
					{"type": "text", "text": string(resultJSON)},
				},
			}
		}
	case "resources/list":
		resp.Result = map[string]interface{}{
			"resources": []map[string]interface{}{
				{"uri": "nano://state", "name": "Agent State", "mimeType": "application/json"},
				{"uri": "nano://experiments", "name": "Experiment Journal", "mimeType": "application/json"},
				{"uri": "nano://hypotheses", "name": "Research Agenda", "mimeType": "application/json"},
				{"uri": "nano://metrics", "name": "Hardware Metrics", "mimeType": "application/json"},
			},
		}
	case "resources/read":
		var params struct {
			URI string `json:"uri"`
		}
		json.Unmarshal(req.Params, &params)
		resp.Result = e.readMCPResource(params.URI)
	default:
		resp.Error = &MCPError{Code: -32601, Message: "method not found: " + req.Method}
	}
	return resp
}

func (e *Engine) getMCPTools() []MCPTool {
	return []MCPTool{
		{
			Name:        "capture_image",
			Description: "Capture a frame from the CSI camera. Returns image path and metadata.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"output_path": map[string]interface{}{"type": "string", "default": "/tmp/capture.jpg"},
					"mode":        map[string]interface{}{"type": "string", "enum": []string{"none", "npu"}, "default": "none"},
				},
			},
		},
		{
			Name:        "run_yolo",
			Description: "Run YOLO object detection on NPU (1 TOPS INT8).",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"image_path": map[string]interface{}{"type": "string"},
					"model_path": map[string]interface{}{"type": "string", "default": "/root/models/yolov8n_coco_640.cvimodel"},
					"sampling_step": map[string]interface{}{"type": "integer", "default": 4, "description": "Pixel sampling step for color analysis (1=high precision, 4=high performance)"},
				},
				"required": []string{"image_path"},
			},
		},
		{
			Name:        "scan_i2c",
			Description: "Scan I2C bus for connected devices.",
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
			Name:        "run_shell",
			Description: "Execute a shell command on the board (security checked).",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"cmd":     map[string]interface{}{"type": "string"},
					"timeout": map[string]interface{}{"type": "integer", "default": 30},
				},
				"required": []string{"cmd"},
			},
		},
		{
			Name:        "list_skills",
			Description: "List all available skills (native + external).",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
		{
			Name:        "get_experiments",
			Description: "Return recent experiment journal entries with keep/discard verdicts.",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"count": map[string]interface{}{"type": "integer", "default": 10},
				},
			},
		},
		{
			Name:        "get_hypotheses",
			Description: "Return research agenda hypotheses and their status.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
		{
			Name:        "get_visual_truth",
			Description: "Return current Visual Truth and Command Truth state.",
			InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
		},
	}
}

func (e *Engine) executeMCPTool(name string, args map[string]interface{}) (map[string]interface{}, error) {
	log.Printf("🔌 MCP tool: %s", name)
	if args == nil {
		args = make(map[string]interface{})
	}

	switch name {
	case "capture_image":
		return e.executeExternalSkill("capture_image", args, resolveTimeout(30))
	case "run_yolo":
		return e.callSkill("run_yolo", args, resolveTimeout(30))
	case "scan_i2c":
		return e.callSkill("i2c_scan", args, resolveTimeout(10))
	case "probe_sensor":
		return e.callSkill("probe_cvitek", nil, resolveTimeout(10))
	case "run_shell":
		cmdStr := paramString(args, "cmd", "")
		if !e.isApproved(cmdStr) {
			return nil, fmt.Errorf("command blocked by security policy")
		}
		return e.runShellCommand(args, paramInt(args, "timeout", 30))
	case "list_skills":
		return nativeListSkills(e, nil)
	case "get_experiments":
		count := paramInt(args, "count", 10)
		entries := e.loadRecentExperiments(count)
		return map[string]interface{}{"experiments": entries, "total": len(entries)}, nil
	case "get_hypotheses":
		return map[string]interface{}{"hypotheses": e.Program.ResearchAgenda.Hypotheses}, nil
	case "get_visual_truth":
		e.mu.Lock()
		result := map[string]interface{}{
			"visual_truth":  e.State.VisualTruth,
			"command_truth": e.State.CommandTruth,
			"metrics":       e.State.Metrics,
		}
		e.mu.Unlock()
		return result, nil
	default:
		return nil, fmt.Errorf("unknown MCP tool: %s", name)
	}
}

func (e *Engine) readMCPResource(uri string) interface{} {
	var text string
	switch uri {
	case "nano://state":
		e.mu.Lock()
		data, _ := json.MarshalIndent(e.State, "", "  ")
		e.mu.Unlock()
		text = string(data)
	case "nano://experiments":
		entries := e.loadRecentExperiments(20)
		data, _ := json.MarshalIndent(entries, "", "  ")
		text = string(data)
	case "nano://hypotheses":
		data, _ := json.MarshalIndent(e.Program.ResearchAgenda.Hypotheses, "", "  ")
		text = string(data)
	case "nano://metrics":
		e.mu.Lock()
		data, _ := json.MarshalIndent(e.State.Metrics, "", "  ")
		e.mu.Unlock()
		text = string(data)
	default:
		text = "unknown resource"
	}
	return map[string]interface{}{
		"contents": []map[string]interface{}{
			{"uri": uri, "mimeType": "application/json", "text": text},
		},
	}
}




func (e *Engine) checkVideoDevs() {
	matches, _ := filepath.Glob("/dev/video*")
	if len(matches) == 0 {
		log.Printf("⚠️ No video devices found in /dev/ (Driver issue?)")
	} else {
		for _, m := range matches {
			if info, err := os.Stat(m); err == nil {
				log.Printf("📸 Found video device: %s (Perms: %v)", m, info.Mode())
			}
		}
	}
}

func (e *Engine) checkMemoryResource() {
	if data, err := os.ReadFile("/proc/meminfo"); err == nil {
		lines := strings.Split(string(data), "\n")
		for _, line := range lines {
			if strings.HasPrefix(line, "MemTotal:") || strings.HasPrefix(line, "MemAvailable:") || strings.HasPrefix(line, "CmaTotal:") || strings.HasPrefix(line, "CmaFree:") {
				log.Printf("🧠 Memory: %s", strings.TrimSpace(line))
			}
		}
	}

	// ION Heap status (Cvitek relies on ION for NPU/CSI buffers)
	if matches, _ := filepath.Glob("/sys/kernel/debug/ion/*"); len(matches) > 0 {
		log.Printf("🧠 ION Heaps detected: %v", matches)
	}
}

func (e *Engine) checkSensorConfig() {
	// 1. Check for official sensor config files
	paths := []string{"/mnt/data/sensor_cfg.ini", "/root/sensor_cfg.ini", "./sensor_cfg.ini"}
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			log.Printf("📸 Sensor config found: %s", p)
			if data, err := os.ReadFile(p); err == nil {
				lines := strings.Split(string(data), "\n")
				for _, line := range lines {
					if strings.Contains(line, "name =") {
						log.Printf("   -> Sensor: %s", strings.TrimSpace(strings.TrimPrefix(line, "name =")))
						break
					}
				}
			}
			break
		}
	}

	// 2. Check for SDR Firmware / Parameter binaries (v6.8.13)
	paramDir := "/mnt/cfg/param"
	if entries, err := os.ReadDir(paramDir); err == nil {
		log.Printf("📸 Detected Sensor Firmware in %s:", paramDir)
		for _, ent := range entries {
			if strings.Contains(ent.Name(), "cvi_sdr") || strings.HasSuffix(ent.Name(), ".bin") {
				log.Printf("   - %s", ent.Name())
			}
		}
	} else {
		log.Printf("ℹ️  Note: %s not accessible (standard sensor params missing)", paramDir)
	}
}

func fileExistsAndNotEmpty(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Size() > 0
}


// ════════════════════════════════════════════════════════════════════════
// SKILL SYSTEM
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) callSkill(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	// 1. Try External Skill FIRST (v6.8.26 — Skill-Led Architecture)
	// If a skill exists in the filesystem, it ALWAYS overrides native code.
	if _, err := e.loadSkillConfig(name); err == nil {
		return e.executeExternalSkill(name, params, timeout)
	}

	// 2. Fallback to Native Skill
	if handler, ok := nativeSkills[name]; ok {
		result, err := handler(e, params)
		if result != nil {
			e.mu.Lock()
			e.State.SkillResults[name] = result
			e.mu.Unlock()
			e.markStateDirty()
		}
		return result, err
	}
	return nil, fmt.Errorf("skill %q not found", name)
}


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

func (e *Engine) loadSkillConfig(name string) (*SkillConfig, error) {
	// Check cache with mtime validation (v6.8.30 — hot-reload)
	if config, ok := e.skillCache[name]; ok {
		if cachedTime, hasMtime := e.skillMtime[name]; hasMtime {
			// Find the SKILL.md file path from config command directory
			skillMdPath := filepath.Join(SkillsDir, name, "SKILL.md")
			if info, err := os.Stat(skillMdPath); err == nil {
				if !info.ModTime().After(cachedTime) {
					return config, nil // Cache is still fresh
				}
				log.Printf("🔄 Skill %q changed on disk — reloading...", name)
				delete(e.skillCache, name)
				delete(e.skillMtime, name)
			} else {
				return config, nil // File gone but cache is fine
			}
		} else {
			return config, nil // Legacy cache entry, serve as-is
		}
	}
	searchPaths := []string{
		filepath.Join("skills", name, "SKILL.md"),
		filepath.Join("/root/skills", name, "SKILL.md"),
		filepath.Join(SkillsDir, name, "SKILL.md"),
	}

	var data []byte
	var err error
	var abs string
	for _, p := range searchPaths {
		abs, _ = filepath.Abs(p)
		data, err = os.ReadFile(p)
		if err == nil {
			log.Printf("📂 Skill %q found at %s", name, abs)
			break
		}
	}

	if err == nil {
		// Tolerant Frontmatter parsing (v6.7.1)
		content := string(data)
		start := strings.Index(content, "---")
		if start == -1 {
			return nil, fmt.Errorf("no frontmatter start marker in %s", abs)
		}
		rest := content[start+3:]
		end := strings.Index(rest, "---")
		if end == -1 {
			return nil, fmt.Errorf("no frontmatter end marker in %s", abs)
		}
		
		var config SkillConfig
		if err := yaml.Unmarshal([]byte(rest[:end]), &config); err != nil {
			return nil, fmt.Errorf("failed to parse yaml in %s: %v", abs, err)
		}
		if config.Name == "" {
			config.Name = name
		}
		if config.Command != "" && !filepath.IsAbs(config.Command) {
			config.Command = filepath.Join(SkillsDir, name, config.Command)
		}
		
		if config.Command != "" {
			if _, err := os.Stat(config.Command); err == nil {
				os.Chmod(config.Command, 0755)
			}
		}

		e.skillCache[name] = &config
		// Store mtime for hot-reload detection
		if info, err := os.Stat(abs); err == nil {
			e.skillMtime[name] = info.ModTime()
		}
		return &config, nil
	}

	// Autonomous Fuzzy Search Solution (v6.7.1)
	log.Printf("🔍 Skill %q not found — searching for autonomous solution...", name)
	
	// Map known mismatches
	mismatches := map[string]string{
		"npu_inspect":    "npu_inspect",
		"npu_info":       "npu_inspect",
		"run_yolo":        "run_yolo",
		"vision_capture":  "run_yolo",
		"camera_capture":  "run_yolo",
	}
	if alias, ok := mismatches[name]; ok && alias != name {
		log.Printf("💡 Fuzzy match found (ALIAS): rerouting %q -> %q", name, alias)
		return e.loadSkillConfig(alias)
	}

	// Scanning sub-directories in BOTH SkillsDir and local "skills"
	scanDirs := []string{SkillsDir, "skills", "/root/skills"}
	for _, sd := range scanDirs {
		entries, _ := os.ReadDir(sd)
		for _, ent := range entries {
			if ent.IsDir() {
				// Case-insensitive fuzzy match
				if strings.Contains(strings.ToLower(ent.Name()), strings.ToLower(name)) || 
				   strings.Contains(strings.ToLower(name), strings.ToLower(ent.Name())) {
					log.Printf("💡 Fuzzy match found (SCAN): rerouting %q -> %q in %s", name, ent.Name(), sd)
					return e.loadSkillConfig(ent.Name())
				}
			}
		}
	}

	return nil, fmt.Errorf("skill %q not found in search paths %v: %v", name, searchPaths, err)
}

func (e *Engine) executeShellSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	if config.Command == "" {
		return nil, fmt.Errorf("skill %s: no command", config.Name)
	}
	inputFmt := config.InputFormat
	if inputFmt == "" {
		inputFmt = "env"
	}

	cmdStr := config.Command
	var envVars []string
	var stdinData []byte

	switch inputFmt {
	case "env":
		for k, v := range params {
			envVars = append(envVars, fmt.Sprintf("SKILL_%s=%v", strings.ToUpper(k), v))
		}
	case "stdin":
		stdinData, _ = json.Marshal(params)
	case "args":
		parts := []string{}
		for k, v := range params {
			parts = append(parts, fmt.Sprintf("--%s=%s", k, shellEscape(fmt.Sprintf("%v", v))))
		}
		cmdStr = cmdStr + " " + strings.Join(parts, " ")
	}

	// ulimit removed to allow full board RAM for tools like ffmpeg and python

	shBin := e.workingShell
	shArgs := []string{"-c", cmdStr}
	if strings.Contains(shBin, "busybox") {
		shArgs = []string{"sh", "-c", cmdStr}
	}
	cmd := exec.Command(shBin, shArgs...)
	// Environment-Safe Pathing (v6.8.16)
	cmd.Env = os.Environ()
	sdkLibs := "/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64"
	
	hasLD := false
	for i, e := range cmd.Env {
		if strings.HasPrefix(e, "LD_LIBRARY_PATH=") {
			cmd.Env[i] = "LD_LIBRARY_PATH=" + sdkLibs + ":" + strings.TrimPrefix(e, "LD_LIBRARY_PATH=")
			hasLD = true
			break
		}
	}
	if !hasLD {
		cmd.Env = append(cmd.Env, "LD_LIBRARY_PATH="+sdkLibs)
	}
	
	// Prepend SDK Toolchain to PATH
	sdkPath := "/root/licheerv-toolchain/riscv64-linux-musl-x86_64/bin"
	hasPath := false
	for i, e := range cmd.Env {
		if strings.HasPrefix(e, "PATH=") {
			cmd.Env[i] = "PATH=" + sdkPath + ":" + strings.TrimPrefix(e, "PATH=")
			hasPath = true
			break
		}
	}
	if !hasPath {
		cmd.Env = append(cmd.Env, "PATH="+sdkPath+":"+os.Getenv("PATH"))
	}

	cmd.Env = append(cmd.Env, envVars...)
	cmd.Dir = filepath.Dir(config.Command)
	if stdinData != nil {
		cmd.Stdin = bytes.NewReader(stdinData)
	}

	out, err := executeCmdWithTimeout(cmd, timeout)
	return e.parseSkillOutput(out, config.OutputFormat), err
}

func (e *Engine) executePythonSkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	if config.Command == "" {
		return nil, fmt.Errorf("skill %s: no command", config.Name)
	}
	cmdStr := fmt.Sprintf("python3 %s", config.Command)

	shBin := e.workingShell
	shArgs := []string{"-c", cmdStr}
	if strings.Contains(shBin, "busybox") {
		shArgs = []string{"sh", "-c", cmdStr}
	}
	cmd := exec.Command(shBin, shArgs...)
	cmd.Env = os.Environ()
	// Inject SDK libraries for native extensions (maix, cv2, etc.)
	sdkLibs := "/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64"
	hasLD := false
	for i, ev := range cmd.Env {
		if strings.HasPrefix(ev, "LD_LIBRARY_PATH=") {
			cmd.Env[i] = "LD_LIBRARY_PATH=" + sdkLibs + ":" + strings.TrimPrefix(ev, "LD_LIBRARY_PATH=")
			hasLD = true
			break
		}
	}
	if !hasLD {
		cmd.Env = append(cmd.Env, "LD_LIBRARY_PATH="+sdkLibs)
	}
	cmd.Dir = filepath.Dir(config.Command)
	stdinData, _ := json.Marshal(params)
	cmd.Stdin = bytes.NewReader(stdinData)

	out, err := executeCmdWithTimeout(cmd, timeout)
	return e.parseSkillOutput(out, config.OutputFormat), err
}

func (e *Engine) executeAPISkill(config *SkillConfig, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	endpoint := config.Endpoint
	for k, v := range params {
		endpoint = strings.ReplaceAll(endpoint, "{"+k+"}", fmt.Sprintf("%v", v))
	}
	bodyJSON, _ := json.Marshal(params)
	tmpFile, _ := os.CreateTemp("", "api_*.json")
	tmpFile.Write(bodyJSON)
	tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	method := strings.ToUpper(config.Method)
	if method == "" {
		method = "GET"
	}
	cmd := exec.Command("curl", "-s", "-X", method, endpoint,
		"-H", "Content-Type: application/json", "-d", "@"+tmpFile.Name(),
		"--max-time", fmt.Sprintf("%d", timeout))
	cmd.Env = os.Environ()
	out, err := executeCmdWithTimeout(cmd, timeout)
	if err != nil {
		return nil, err
	}
	return e.parseSkillOutput(out, config.OutputFormat), nil
}

func (e *Engine) parseSkillOutput(raw, format string) map[string]interface{} {
	raw = strings.TrimSpace(raw)
	switch format {
	case "json":
		// Find first { and last } to handle noisy output (e.g. combined stderr/stdout)
		start := strings.Index(raw, "{")
		end := strings.LastIndex(raw, "}")
		if start != -1 && end != -1 && end > start {
			jsonPart := raw[start : end+1]
			var r map[string]interface{}
			if err := json.Unmarshal([]byte(jsonPart), &r); err == nil {
				return r
			}
		}
		// Fallback to direct unmarshal if possible
		var r map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &r); err == nil {
			return r
		}
		return map[string]interface{}{"output": raw, "parse_error": "invalid json"}
	case "keyvalue":
		r := make(map[string]interface{})
		for _, line := range strings.Split(raw, "\n") {
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 {
				r[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
			}
		}
		if len(r) == 0 {
			r["output"] = raw
		}
		return r
	default:
		return map[string]interface{}{"output": raw}
	}
}

// ════════════════════════════════════════════════════════════════════════
// SKILL EVOLUTION — agent creates new skills from discovered patterns
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) createSkill(name, description, scriptContent string) error {
	if !e.Program.SelfImprovement.EvolveSkills {
		return fmt.Errorf("skill evolution disabled")
	}
	skillDir := filepath.Join(SkillsDir, name)
	if _, err := os.Stat(skillDir); err == nil {
		return fmt.Errorf("skill %s already exists", name)
	}
	os.MkdirAll(skillDir, 0755)

	// Write SKILL.md from template
	tmpl := e.Program.SelfImprovement.SkillTemplate
	if tmpl == "" {
		tmpl = "---\nname: {name}\nexec_type: shell\ncommand: ./run.sh\ninput_format: env\noutput_format: json\ntimeout: 30\n---\n# {name}\n{description}\n"
	}
	skillMD := strings.ReplaceAll(tmpl, "{name}", name)
	skillMD = strings.ReplaceAll(skillMD, "{description}", description)
	os.WriteFile(filepath.Join(skillDir, "SKILL.md"), []byte(skillMD), 0644)

	// Write run.sh
	os.WriteFile(filepath.Join(skillDir, "run.sh"), []byte(scriptContent), 0755)

	// Clear cache so it gets reloaded
	delete(e.skillCache, name)
	log.Printf("🔧 Created skill: %s → %s", name, skillDir)
	return nil
}

// ════════════════════════════════════════════════════════════════════════
// ACTION DISPATCHER
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) dispatchAction(action string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	t := resolveTimeout(timeout, e.Program.Constraints.MaxTimeout)
	if params == nil {
		params = make(map[string]interface{})
	}

	switch action {
	case "shell_cmd":
		return e.runShellCommand(params, t)
	case "call_skill":
		skillName := paramString(params, "skill_name", "")
		if skillName == "" {
			return nil, fmt.Errorf("call_skill requires 'skill_name'")
		}
		skillParams := make(map[string]interface{})
		for k, v := range params {
			if k != "skill_name" {
				skillParams[k] = v
			}
		}
		return e.callSkillWithAutoGenerate(skillName, skillParams, t)
	case "capture_image":
		return e.executeExternalSkill("capture_image", params, t)
	case "audio_record":
		return e.callSkillWithAutoGenerate("capture_audio_maix", params, t)
	case "audio_stop":
		return e.nativeAudioStop(params, t)
	case "i2c_scan":
		return e.callSkillWithAutoGenerate("i2c_scan", params, t)
	case "probe_cvitek":
		return e.callSkillWithAutoGenerate("camera_init", params, t)
	case "skill_list":
		return e.callSkillWithAutoGenerate("list_skills", nil, t)
	case "run_python_code":
		return e.executePythonCode(params, t)
	default:
		return e.callSkillWithAutoGenerate(action, params, t)
	}
}

func (e *Engine) findNextTask() (*Task, error) {
	files, err := os.ReadDir(TasksDir)
	if err != nil {
		return nil, err
	}
	var candidates []*Task
	for _, f := range files {
		if !strings.HasSuffix(f.Name(), ".yaml") && !strings.HasSuffix(f.Name(), ".yml") {
			continue
		}
		path := filepath.Join(TasksDir, f.Name())
		data, err := os.ReadFile(path)
		if err != nil {
			log.Printf("   ⚠️ Failed to read task file %s: %v", f.Name(), err)
			continue
		}

		// 1. Try Slice format (Standard: - id: ...)
		var taskList []Task
		if err := yaml.Unmarshal(data, &taskList); err == nil && len(taskList) > 0 {
			for i := range taskList {
				t := taskList[i] // Copy to avoid pointer reuse bug
				t.SourceFile = path
				if t.Status == "pending" || t.Status == "running" || t.Status == "" {
					candidates = append(candidates, &t)
				}
			}
			continue
		}

		// 2. Try legacy wrapped format (task: id: ...)
		var wrapper struct {
			Task Task `yaml:"task"`
		}
		if err := yaml.Unmarshal(data, &wrapper); err == nil && wrapper.Task.ID != "" {
			t := wrapper.Task
			t.SourceFile = path
			if t.Status == "pending" || t.Status == "running" || t.Status == "" {
				candidates = append(candidates, &t)
			}
		} else {
			// 3. Try flattened format (id: ...)
			var t Task
			if err := yaml.Unmarshal(data, &t); err == nil && t.ID != "" {
				t.SourceFile = path
				if t.Status == "pending" || t.Status == "running" || t.Status == "" {
					candidates = append(candidates, &t)
				}
			}
		}
	}

	if len(candidates) == 0 {
		return nil, fmt.Errorf("no pending tasks found in %s", TasksDir)
	}

	// Sort by priority (descending)
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].Priority > candidates[j].Priority
	})

	return candidates[0], nil
}

func (e *Engine) runShellCommand(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	cmdStr := paramString(params, "cmd", "")
	if !e.isApproved(cmdStr) {
		return nil, fmt.Errorf("command blocked by security policy")
	}
	// ulimit removed to prevent crashing external interpreters
	out, err := runCommandWithTimeout(timeout, "sh", "-c", cmdStr)
	e.mu.Lock()
	e.State.CommandTruth = truncateString(out, MaxStateLength)
	e.mu.Unlock()
	e.markStateDirty()
	return map[string]interface{}{"output": out}, err
}


func (e *Engine) nativeAudioStop(_ map[string]interface{}, _ int) (map[string]interface{}, error) {
	log.Printf("🎙️ Stopping all audio recording processes...")
	out, _ := exec.Command("pkill", "arecord").CombinedOutput()
	return map[string]interface{}{
		"status": "stopped",
		"output": string(out),
	}, nil
}

func (e *Engine) executePythonCode(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	code := paramString(params, "code", "")
	path := filepath.Join("/tmp", fmt.Sprintf("auto_%d.py", time.Now().UnixNano()))
	os.WriteFile(path, []byte(code), 0644)
	defer os.Remove(path)
	cmdStr := fmt.Sprintf("python3 %s", path)
	// ulimit removed to prevent crashing external interpreters
	out, err := runCommandWithTimeout(timeout, "sh", "-c", cmdStr)
	e.mu.Lock()
	e.State.CommandTruth = truncateString(out, MaxStateLength)
	e.mu.Unlock()
	e.markStateDirty()
	return map[string]interface{}{"output": out}, err
}

// ════════════════════════════════════════════════════════════════════════
// EXPECTATION VERIFICATION
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) verifyExpectations(data map[string]interface{}, expect map[string]interface{}) bool {
	if len(expect) == 0 {
		return true
	}
	if data == nil {
		return false
	}
	for k, target := range expect {
		if strings.HasSuffix(k, "_contains") {
			actualKey := strings.TrimSuffix(k, "_contains")
			actual, ok := data[actualKey]
			if !ok || !strings.Contains(strings.ToLower(fmt.Sprintf("%v", actual)), strings.ToLower(fmt.Sprintf("%v", target))) {
				return false
			}
			continue
		}
		if strings.HasSuffix(k, "_matches") {
			actualKey := strings.TrimSuffix(k, "_matches")
			actual, ok := data[actualKey]
			if !ok {
				return false
			}
			matched, err := regexp.MatchString(fmt.Sprintf("%v", target), fmt.Sprintf("%v", actual))
			if err != nil || !matched {
				return false
			}
			continue
		}
		val, ok := data[k]
		if !ok {
			return false
		}
		if !matchTarget(fmt.Sprintf("%v", val), target) {
			return false
		}
	}
	return true
}

func matchTarget(actual string, target interface{}) bool {
	tStr := fmt.Sprintf("%v", target)
	aLower := strings.ToLower(actual)
	tLower := strings.ToLower(tStr)

	if strings.HasPrefix(tLower, ">=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, ">="), func(a, b float64) bool { return a >= b })
	}
	if strings.HasPrefix(tLower, ">") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, ">"), func(a, b float64) bool { return a > b })
	}
	if strings.HasPrefix(tLower, "<=") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, "<="), func(a, b float64) bool { return a <= b })
	}
	if strings.HasPrefix(tLower, "<") {
		return compareNumeric(aLower, strings.TrimPrefix(tLower, "<"), func(a, b float64) bool { return a < b })
	}
	if aLower == "true" || aLower == "false" {
		return aLower == tLower
	}
	return actual == tStr
}

func compareNumeric(actualStr, targetStr string, cmp func(float64, float64) bool) bool {
	a, errA := strconv.ParseFloat(strings.TrimSpace(actualStr), 64)
	b, errB := strconv.ParseFloat(strings.TrimSpace(targetStr), 64)
	if errA != nil || errB != nil {
		return actualStr == targetStr
	}
	return cmp(a, b)
}

// ════════════════════════════════════════════════════════════════════════
// TASK MANAGEMENT
// ════════════════════════════════════════════════════════════════════════



func (e *Engine) executeTask(t *Task) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("🔥 CRITICAL ERROR in task [%s]: %v", t.ID, r)
			log.Printf("🛡️  Recovery triggered. Skipping task and continuing loop...")
			e.appendResult(t.ID, "engine", "error", fmt.Sprintf("Panic recovered: %v", r))
			e.mu.Lock()
			e.State.CurrentTaskID = ""
			e.mu.Unlock()
		}
	}()

	log.Printf("🚀 Task [%s] %s (priority %d)", t.ID, t.Name, t.Priority)
	startTime := time.Now()

	// Snapshot metrics BEFORE
	metricsBefore := e.snapshotMetrics()

	e.mu.Lock()
	e.State.CurrentTaskID = t.ID
	e.mu.Unlock()
	t.Status = "running"
	e.saveTaskStatus(t)

	stepsRun := 0
	stepsPassed := 0

	for _, step := range t.Steps {
		stepsRun++
		e.markStateDirty()

		var success bool
		var lastErr error
		var lastResult map[string]interface{}

		maxRetries := step.MaxRetries
		if maxRetries <= 0 {
			maxRetries = e.Program.Strategy.MaxRetries
		}

		for attempt := 0; attempt <= maxRetries; attempt++ {
			resultData, err := e.dispatchAction(step.Action, step.Parameters, step.Timeout)
			lastResult = resultData
			if err == nil && e.verifyExpectations(resultData, step.Expect) {
				success = true
				break
			}
			lastErr = err
			if attempt < maxRetries {
				backoff := time.Duration(attempt+1) * 2 * time.Second
				time.Sleep(backoff)
			}
		}

		if success {
			stepsPassed++
			e.appendResult(t.ID, step.ID, "keep", step.Action)
			log.Printf("  ✅ Step %s succeeded", step.ID)
		} else {
			errMsg := "Expectation verification failed"
			if lastErr != nil {
				errMsg = lastErr.Error()
			} else if lastResult != nil {
				if msg, ok := lastResult["message"].(string); ok {
					errMsg = msg
				} else if status, ok := lastResult["status"].(string); ok && status == "error" {
					errMsg = "Skill reported error status"
				}
			}
			failureEntry := fmt.Sprintf("%s/%s: %s (%s)", t.ID, step.ID, step.Action, errMsg)
			e.mu.Lock()
			e.State.RecentFailures = append(e.State.RecentFailures, failureEntry)
			if len(e.State.RecentFailures) > 10 {
				e.State.RecentFailures = e.State.RecentFailures[len(e.State.RecentFailures)-10:]
			}
			e.mu.Unlock()

			if step.OnFail == "block" {
				t.Status = "blocked"
				e.appendResult(t.ID, step.ID, "crash", "blocked: "+errMsg)
				log.Printf("  🛑 Step %s blocked task", step.ID)
				log.Printf("  🛑 Step %s blocked task: %s", step.ID, errMsg)

				// Try spawning sub-agent for blocked task
				if e.shouldSpawnSubAgent("blocked_task") {
					e.spawnSubAgent(t.SourceFile)
				}
				break
			}
			e.appendResult(t.ID, step.ID, "discard", errMsg)
			log.Printf("  ❌ Step %s failed: %s", step.ID, errMsg)
		}
	}

	// Refresh metrics AFTER
	e.updateMetrics()
	metricsAfter := e.snapshotMetrics()
	duration := time.Since(startTime)

	// Score the experiment
	verdict := e.scoreExperiment(metricsBefore, metricsAfter)

	// Determine completion status
	if stepsPassed == stepsRun && stepsRun > 0 {
		if e.checkSuccessCriteria(t) {
			t.Status = "completed"
		} else {
			t.Status = "pending" // Missing success criteria (e.g. file not found)
			log.Printf("  ⚠️ Task steps passed but success criteria not met yet")
		}
	} else if stepsPassed > 0 {
		t.Status = "partial"
	} else if t.Status != "blocked" {
		t.Status = "failed"
	}
	e.saveTaskStatus(t)

	log.Printf("📊 Experiment #%d: %v [%s]", e.State.Iteration, t.Name, verdict)
	e.logExperiment(*t, verdict)


	// Record experiment
	summary := fmt.Sprintf("%d/%d steps passed, verdict=%s", stepsPassed, stepsRun, verdict)
	e.mu.Lock()
	e.State.ExperimentNum++
	num := e.State.ExperimentNum
	e.mu.Unlock()

	entry := ExperimentEntry{
		ID:            num,
		Timestamp:     time.Now().Format(time.RFC3339),
		TaskID:        t.ID,
		TaskName:      t.Name,
		HypothesisRef: t.HypothesisRef,
		MetricsBefore: metricsBefore,
		MetricsAfter:  metricsAfter,
		StepsRun:      stepsRun,
		StepsPassed:   stepsPassed,
		Duration:      duration.String(),
		Verdict:       verdict,
		Summary:       summary,
	}
	e.appendExperiment(entry)

	// History
	histEntry := fmt.Sprintf("[%d] %s → %s (%s)", e.State.Iteration, t.Name, t.Status, verdict)
	e.mu.Lock()
	e.State.History = append(e.State.History, histEntry)
	if len(e.State.History) > e.Program.Loop.ContextWindow {
		e.State.History = e.State.History[len(e.State.History)-e.Program.Loop.ContextWindow:]
	}
	e.mu.Unlock()
	e.markStateDirty()

	// Spawn subtasks
	e.spawnSubtasks(t)
}

func (e *Engine) logExperiment(t Task, verdict string) {
	if t.HypothesisRef == "" {
		return
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	
	// Ensure hypothesis status is updated in the persistent agenda
	for i := range e.Program.ResearchAgenda.Hypotheses {
		h := &e.Program.ResearchAgenda.Hypotheses[i]
		if h.ID == t.HypothesisRef {
			// Refine "keep/discard" into "confirmed/refuted"
			switch verdict {
			case "keep":
				h.Status = "confirmed"
			case "discard":
				h.Status = "refuted"
			default:
				h.Status = verdict
			}
			log.Printf("🔬 Hypothesis %s final status: %s", h.ID, h.Status)
			break
		}
	}
}

func (e *Engine) spawnSubtasks(parent *Task) {
	for _, sub := range parent.Subtasks {
		targetPath := filepath.Join(TasksDir, filepath.Base(sub.File))
		if _, err := os.Stat(targetPath); err == nil {
			continue
		}
		if data, err := os.ReadFile(sub.File); err == nil {
			os.WriteFile(targetPath, data, 0644)
			log.Printf("📋 Spawned subtask: %s → %s", sub.Name, targetPath)
		}
	}
}

func (e *Engine) shouldSpawnSubAgent(trigger string) bool {
	for _, t := range e.Program.SubAgents.SpawnOn {
		if t == trigger {
			return true
		}
	}
	return false
}

func (e *Engine) checkSuccessCriteria(t *Task) bool {
	if len(t.SuccessCriteria) == 0 {
		return true // No criteria = success
	}

	for _, crit := range t.SuccessCriteria {
		if strings.HasPrefix(crit, "test -f ") {
			path := strings.TrimPrefix(crit, "test -f ")
			if _, err := os.Stat(path); err != nil {
				return false
			}
		} else if strings.HasPrefix(crit, "test ! -f ") {
			path := strings.TrimPrefix(crit, "test ! -f ")
			if _, err := os.Stat(path); err == nil {
				return false
			}
		} else if strings.HasPrefix(crit, "grep ") {
			// Format: grep <pattern> <file>
			parts := strings.SplitN(strings.TrimPrefix(crit, "grep "), " ", 2)
			if len(parts) == 2 {
				pattern, path := parts[0], parts[1]
				_, err := runCommandWithTimeout(10, "sh", "-c", "grep -q "+shellEscape(pattern)+" "+shellEscape(path))
				if err != nil {
					return false
				}
			}
		} else if crit == "successful_exit" {
			// This is implicitly handled by stepsPassed == stepsRun, 
			// but we can add more logic here if needed.
		}
	}
	return true
}

func (e *Engine) saveTaskStatus(t *Task) {
	if t.SourceFile == "" {
		return
	}
	data, err := os.ReadFile(t.SourceFile)
	if err != nil {
		return
	}

	var root interface{}
	if err := yaml.Unmarshal(data, &root); err != nil {
		log.Printf("⚠️ Failed to parse %s for update: %v", t.SourceFile, err)
		return
	}

	found := false
	switch v := root.(type) {
	case []interface{}:
		// Sequence/Array format (- id: ...)
		for _, item := range v {
			if m, ok := item.(map[string]interface{}); ok {
				if m["id"] == t.ID {
					m["status"] = t.Status
					found = true
				}
			}
		}
	case map[string]interface{}:
		// Wrapped or Flat format
		if taskMap, ok := v["task"].(map[string]interface{}); ok {
			// Wrapped: task: id: ...
			if taskMap["id"] == t.ID {
				taskMap["status"] = t.Status
				found = true
			}
		} else if v["id"] == t.ID {
			// Flat: id: ...
			v["status"] = t.Status
			found = true
		}
	}

	if found {
		updated, err := yaml.Marshal(root)
		if err == nil {
			os.WriteFile(t.SourceFile, updated, 0644)
		}
	} else {
		log.Printf("⚠️ Task %s not found in %s during status update", t.ID, t.SourceFile)
	}
}

func (e *Engine) updateMetrics() {
	for name, metric := range e.Program.Metrics {
		if !e.isApproved(metric.Check) {
			e.mu.Lock()
			e.State.Metrics[name] = "blocked"
			e.mu.Unlock()
			continue
		}
		cmdStr := metric.Check
		// ulimit removed to prevent crashing metric scripts
		out, err := runCommandWithTimeout(
			resolveTimeout(e.Program.Constraints.MaxTimeout), "sh", "-c", cmdStr)
		val := strings.TrimSpace(out)
		if err != nil {
			val = "error"
		}
		e.mu.Lock()
		e.State.Metrics[name] = val
		e.mu.Unlock()
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
	if err := cmd.Start(); err != nil {
		return "", err
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		return buf.String(), err
	case <-time.After(time.Duration(timeoutSec) * time.Second):
		if cmd.Process != nil {
			syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
			select {
			case <-done:
			case <-time.After(3 * time.Second):
				syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
				select {
				case <-done:
				case <-time.After(5 * time.Second):
				}
			}
		}
		return buf.String(), fmt.Errorf("timeout %ds", timeoutSec)
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
	// Check if running as sub-agent
	if isSubAgent() {
		e.runSubAgentMode()
		return
	}

	e.StartMCPServer()
	e.StartFederatedServer()

	shutdown := make(chan os.Signal, 1)
	signal.Notify(shutdown, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-shutdown
		log.Println("🛑 Shutdown — flushing state + archiving experiments...")
		atomic.StoreInt32(&e.shutdownFlag, 1)
		e.archiveExperiments()
		e.saveState()
		os.Exit(0)
	}()

	// Init results.tsv
	if _, err := os.Stat("results.tsv"); os.IsNotExist(err) {
		os.WriteFile("results.tsv", []byte("time\ttask\tstep\tstatus\tdescription\n"), 0644)
	}

	for {
		if atomic.LoadInt32(&e.shutdownFlag) == 1 {
			if e.stateDirty {
				e.saveState()
			}
			return
		}

		// Try to find and execute a task
		task, err := e.findNextTask()
		if err != nil {
			// No tasks found — ultra-quiet idle
			if e.idleCount%200 == 0 { // Heartbeat once every 200 cycles (~15-20 mins)
				log.Printf("💤 Standing by for tasks in %s/ (Ultra-Quiet Mode)", TasksDir)
			}
			e.idleCount++
			time.Sleep(time.Duration(e.Program.Loop.PollInterval) * time.Second)
			continue
		} 
		
		// Work found!
		e.idleCount = 0
		e.State.Iteration++
		log.Printf("🔄 ─── Iteration %d ───", e.State.Iteration)

		// Update metrics periodically during active periods
		if e.State.Iteration%e.Program.Loop.MetricsEveryN == 0 {
			e.updateMetrics()
		}

		e.executeTask(task)
		e.flushStateIfNeeded()
		e.writeHeartbeat(task.ID)

		if !e.Program.Loop.NeverStop {
			break
		}
		time.Sleep(time.Duration(e.Program.Loop.PollInterval) * time.Second)
	}
}

// Sub-agent mode: execute a single task, write result, exit
func (e *Engine) runSubAgentMode() {
	taskFile := ""
	resultFile := ""
	for i, arg := range os.Args {
		if arg == "--task" && i+1 < len(os.Args) {
			taskFile = os.Args[i+1]
		}
		if arg == "--result" && i+1 < len(os.Args) {
			resultFile = os.Args[i+1]
		}
	}
	if taskFile == "" || resultFile == "" {
		log.Fatalf("sub-agent requires --task and --result")
	}

	data, err := os.ReadFile(taskFile)
	if err != nil {
		log.Fatalf("sub-agent: %v", err)
	}
	var wrapper struct {
		Task Task `yaml:"task"`
	}
	if err := yaml.Unmarshal(data, &wrapper); err != nil {
		log.Fatalf("sub-agent: %v", err)
	}

	log.Printf("🔀 Sub-agent executing: %s", wrapper.Task.Name)
	e.executeTask(&wrapper.Task)

	result := map[string]interface{}{
		"task_id": wrapper.Task.ID,
		"status":  wrapper.Task.Status,
		"verdict": "completed",
	}
	resultJSON, _ := json.MarshalIndent(result, "", "  ")
	os.WriteFile(resultFile, resultJSON, 0644)
}

func isSubAgent() bool {
	for _, arg := range os.Args {
		if arg == "--sub-agent" {
			return true
		}
	}
	return false
}

func (e *Engine) resolveModelPath(requested string) string {
	// 1. Check if the exact requested path exists
	if _, err := os.Stat(requested); err == nil {
		return requested
	}

	// 2. Search common fallback locations for .cvimodel files
	searchDirs := []string{
		"/root/models_for_benchmark",
		"/root/models",
		filepath.Dir(requested),
		".",
	}

	// Priority Check for the known working model
	for _, dir := range searchDirs {
		p := filepath.Join(dir, "yolov8n_coco_320.cvimodel")
		if _, err := os.Stat(p); err == nil {
			log.Printf("🔎 Found fallback model (PRIORITY): %s", p)
			return p
		}
	}

	// General Glob fallback
	for _, dir := range searchDirs {
		matches, _ := filepath.Glob(filepath.Join(dir, "*.cvimodel"))
		if len(matches) > 0 {
			log.Printf("🔎 Found fallback model (GLOB): %s (Original: %s)", matches[0], requested)
			return matches[0]
		}
	}

	log.Printf("⚠️ Model Resolver failed to find any .cvimodel. Falling back to requested: %s", requested)
	return requested
}

// resolveBinaryPath searches for a binary in priority order: local root, standard bins, and PATH.
func (e *Engine) resolveBinaryPath(name string) string {
	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)

	priorities := []string{
		filepath.Join(exeDir, name),
		"/root/libs_patch/bin/" + name,
		"/root/" + name,
		"/usr/bin/" + name,
		"/usr/local/bin/" + name,
		"/mnt/system/usr/bin/" + name,
		"/opt/bin/" + name,
	}

	for _, p := range priorities {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}

	// Dynamic lookup in $PATH
	if p, err := exec.LookPath(name); err == nil {
		return p
	}

	return "" // Not found — callers must handle absence
}

// findIIODevice searches /sys/bus/iio/devices/ for a device matching the name (e.g., "adc")
func (e *Engine) findIIODevice(match string) string {
	base := "/sys/bus/iio/devices/"
	entries, err := os.ReadDir(base)
	if err != nil {
		return ""
	}

	for _, entry := range entries {
		namePath := filepath.Join(base, entry.Name(), "name")
		data, err := os.ReadFile(namePath)
		if err == nil && strings.Contains(strings.ToLower(string(data)), strings.ToLower(match)) {
			return filepath.Join(base, entry.Name())
		}
	}
	return ""
}



func main() {
	engine := NewEngine()
	log.Printf("═══ nano-os-agent v%s ═══", AgentVersion)
	engine.Run()
}
