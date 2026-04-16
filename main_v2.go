package main

// ════════════════════════════════════════════════════════════════════════
// nano-os-agent v6.0 — Self-Improving Autonomous Research Engine
// ════════════════════════════════════════════════════════════════════════
// Target:  LicheeRV Nano (SG2002, 256MB DDR3, RISC-V C906, NPU 1TOPS)
// Build:   GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-os-agent
//
// Architecture (Karpathy autoresearch pattern for embedded hardware):
//   program.yaml = the human-editable "program.md"
//   tasks/*.yaml = experiments the agent generates and executes
//   skills/      = reusable capabilities (shell/python scripts)
//   experiments.jsonl = the "val_bpb" — keep/discard history
//
// Relationship to picoClaw:
//   picoClaw = AI Assistant (chat, LLM providers, channels, MCP client)
//   nano-os-agent = Hardware Orchestrator + MCP server
//   When nano-os-agent needs LLM reasoning → calls picoClaw Gateway API
//   picoClaw calls nano-os-agent via MCP for hardware tools
// ════════════════════════════════════════════════════════════════════════

import (
	"bufio"
	"bytes"
	"encoding/base64"
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

// ════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ════════════════════════════════════════════════════════════════════════

const (
	SkillsDir            = "/root/.picoclaw/workspace/skills"
	TasksDir             = "tasks"
	DefaultCapturePath   = "/tmp/capture.jpg"
	DefaultFlushInterval = 50
	DefaultContextWindow = 20
	MaxIdleBackoffSecs   = 300
	MaxStateLength       = 300
	MaxImageSizeBytes    = 4 * 1024 * 1024 // 4MB for 640x640+ assets
	ModelInputResolution = 640             // Standard YOLOv8n resolution
	MaxExperimentContext = 5               // last N experiments to include in LLM prompt

	MCPListenAddr      = "0.0.0.0:9600"
	PicoClawGatewayURL = "http://127.0.0.1:18790"
	FederatedPort      = ":9601"
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
	Color        map[string]float64  `json:"color"`
	Displacement Delta               `json:"displacement,omitempty"`
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
		"i2c_scan":     nativeI2CScan,
		"probe_cvitek": nativeProbeCvitek,
		"list_skills":  nativeListSkills,
		"run_yolo":     nativeRunYolo,
		"npu_inspect":  nativeNPUInspect,
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

	// Only attempt generation if skill is truly missing
	if !strings.Contains(err.Error(), "not found") {
		return nil, err
	}

	if !e.Program.SelfImprovement.EvolveSkills {
		return nil, fmt.Errorf("skill %q not found and evolution is disabled", name)
	}

	log.Printf("🧠 Skill %q not found — asking picoClaw to generate it...", name)
	_, genErr := e.requestPicoClawSkillGeneration(name, params)
	if genErr != nil {
		return nil, fmt.Errorf("skill %q generation failed: %v", name, genErr)
	}

	// Refresh cache and retry
	e.mu.Lock()
	e.skillCache = make(map[string]*SkillConfig)
	e.mu.Unlock()

	time.Sleep(1 * time.Second)
	log.Printf("🔄 Retrying skill %q after generation...", name)
	return e.callSkill(name, params, timeout)
}

func (e *Engine) requestPicoClawSkillGeneration(skillName string, params map[string]interface{}) (map[string]interface{}, error) {
	paramsJSON, _ := json.Marshal(params)
	prompt := fmt.Sprintf(
		"Generate a new hardware skill '%s' for LicheeRV Nano (SG2002, RISC-V).\n"+
			"Task parameters: %s\n\n"+
			"Requirements:\n"+
			"1. Input via SKILL_* environment variables.\n"+
			"2. Output strictly as JSON to stdout.\n"+
			"3. Use only standard tools (curl, python3, i2cget, etc.).\n\n"+
			"Respond with exactly two blocks:\n"+
			"```yaml\n(SKILL.md frontmatter)\n```\n"+
			"```bash\n(run.sh script)\n```",
		skillName, string(paramsJSON))

	payload := map[string]interface{}{
		"message": prompt,
		"model":   "auto",
	}
	pJSON, _ := json.Marshal(payload)

	tmpFile, _ := os.CreateTemp("", "skill_gen_*.json")
	tmpFile.Write(pJSON)
	tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	out, err := runCommandWithTimeout(120, "curl", "-s", "-X", "POST",
		PicoClawGatewayURL+"/api/chat",
		"-H", "Content-Type: application/json",
		"-d", "@"+tmpFile.Name())
	if err != nil {
		return nil, err
	}

	var resp struct{ Response string `json:"response"` }
	if err := json.Unmarshal([]byte(out), &resp); err != nil {
		return nil, err
	}

	yamlRe := regexp.MustCompile("(?s)```(?:yaml)?\n(.*?)\n```")
	bashRe := regexp.MustCompile("(?s)```(?:bash|sh)?\n(.*?)\n```")

	yamlMatch := yamlRe.FindStringSubmatch(resp.Response)
	bashMatch := bashRe.FindStringSubmatch(resp.Response)
	if len(yamlMatch) < 2 || len(bashMatch) < 2 {
		return nil, fmt.Errorf("failed to parse generated code blocks from picoClaw")
	}

	skillDir := filepath.Join(SkillsDir, skillName)
	os.MkdirAll(skillDir, 0755)

	skillMD := "---\n" + strings.TrimSpace(yamlMatch[1]) + "\n---\n\n# Auto-generated skill\n"
	os.WriteFile(filepath.Join(skillDir, "SKILL.md"), []byte(skillMD), 0644)
	os.WriteFile(filepath.Join(skillDir, "run.sh"), []byte(strings.TrimSpace(bashMatch[1])), 0755)

	return map[string]interface{}{"status": "generated", "path": skillDir}, nil
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
		log.Printf("🌐 Starting Federated Server on :9601")
		if err := http.ListenAndServe(":9601", mux); err != nil {
			log.Printf("⚠️ Federated server error: %v", err)
		}
	}()
}

func (e *Engine) handleFederatedPush(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	body, _ := io.ReadAll(r.Body)
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
	body, _ := io.ReadAll(r.Body)
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

func nativeRunYolo(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	modelPath := paramString(params, "model_path", "/root/models/yolov8n.cvimodel")
	imagePath := paramString(params, "image_path", "/tmp/capture.jpg")
	
	// Autodiscovery of binary (Search SDK samples for both Detection and Segmentation)
	searchPaths := []string{
		"/usr/bin/cvi_tdl_yolo",
		"/root/libs_patch/bin/cvi_tdl_yolo",
		"/usr/bin/sample_vi_od",
		"/root/libs_patch/bin/sample_vi_od",
		"/usr/bin/sample_vi_seg",
		"/root/libs_patch/bin/sample_vi_seg",
		"./vision_npu",
	}
	
	var binPath string
	for _, p := range searchPaths {
		if _, err := os.Stat(p); err == nil {
			binPath = p
			break
		}
	}
	
	if binPath == "" {
		return nil, fmt.Errorf("Universal Vision Binary not found. Search paths were: %v", searchPaths)
	}

	threshold := paramString(params, "threshold", "0.5")

	// Hardened SDK Environment (Universal)
	cmd := exec.Command(binPath, modelPath, imagePath, threshold)
	sdkPatch := "/root/libs_patch"
	cmd.Env = append(os.Environ(), 
		"LD_LIBRARY_PATH="+sdkPatch+"/lib:"+sdkPatch+"/middleware_v2:"+sdkPatch+"/middleware_v2_3rd:"+sdkPatch+"/tpu_sdk_libs:"+sdkPatch+":"+sdkPatch+"/opencv",
	)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	
	err := cmd.Run()
	if err != nil {
		return map[string]interface{}{
			"status": "error", 
			"message": err.Error(),
			"stderr": stderr.String(),
			"bin": binPath,
		}, nil
	}

	// Try to parse JSON from stdout
	var rawDets []RawDetection
	if err := json.Unmarshal(stdout.Bytes(), &rawDets); err != nil {
		// Fallback to raw output if not valid JSON
		return map[string]interface{}{
			"status": "ok",
			"raw_detections": stdout.String(),
			"bin": binPath,
		}, nil
	}

	atoms := e.readAndAnalyzeImage(imagePath, rawDets)

	return map[string]interface{}{
		"status": "ok",
		"atoms":  atoms,
		"bin":    binPath,
	}, nil
}

func (e *Engine) readAndAnalyzeImage(imagePath string, detections []RawDetection) []PerceptionAtom {
	f, err := os.Open(imagePath)
	if err != nil {
		log.Printf("⚠️ Perception fail: %v", err)
		return nil
	}
	defer f.Close()

	img, _, err := image.Decode(f)
	if err != nil {
		log.Printf("⚠️ Decode fail: %v", err)
		return nil
	}

	atoms := make([]PerceptionAtom, 0)
	for i, d := range detections {
		if len(d.Box) < 4 {
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
			Area:      math.Abs((d.Box[2] - d.Box[0]) * (d.Box[3] - d.Box[1])) / (ModelInputResolution * ModelInputResolution),
			Perimeter: 2 * (math.Abs(d.Box[2]-d.Box[0]) + math.Abs(d.Box[3]-d.Box[1])) / float64(ModelInputResolution),
		}

		intensity, colors := analyzeRegion(img, x1, y1, x2, y2)
		atom.Intensity = intensity
		atom.Color = colors
		
		atoms = append(atoms, atom)
	}
	return atoms
}

func analyzeRegion(img image.Image, x1, y1, x2, y2 int) (float64, map[string]float64) {
	bounds := img.Bounds()
	if x1 < bounds.Min.X { x1 = bounds.Min.X }
	if y1 < bounds.Min.Y { y1 = bounds.Min.Y }
	if x2 > bounds.Max.X { x2 = bounds.Max.X }
	if y2 > bounds.Max.Y { y2 = bounds.Max.Y }

	var totalI, totalR, totalG, totalB uint64
	var count uint64

	for y := y1; y < y2; y++ {
		for x := x1; x < x2; x++ {
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
		return 0, map[string]float64{"r": 0, "g": 0, "b": 0}
	}

	return float64(totalI) / float64(count), map[string]float64{
		"r": float64(totalR) / float64(count),
		"g": float64(totalG) / float64(count),
		"b": float64(totalB) / float64(count),
	}
}

func nativeNPUInspect(e *Engine, params map[string]interface{}) (map[string]interface{}, error) {
	modelPath := paramString(params, "model_path", "")
	binPath := "/usr/bin/cvimodel_tool"
	
	args := []string{"-i"}
	if modelPath != "" {
		args = append(args, modelPath)
	} else {
		return nil, fmt.Errorf("model_path required for NPU inspection")
	}

	cmd := exec.Command(binPath, args...)
	cmd.Env = append(os.Environ(), 
		"LD_LIBRARY_PATH=/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/tpu_sdk_libs:/root/libs_patch",
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
	data, err := os.ReadFile("/proc/cvitek/vi")
	if err != nil {
		return map[string]interface{}{"sensor_bound": false, "error": err.Error()}, nil
	}
	return map[string]interface{}{
		"sensor_bound": strings.Contains(string(data), "DevID"),
		"raw":          strings.TrimSpace(string(data)),
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
	subAgentPIDs  map[int]string // pid → task file
	mu            sync.Mutex
}

func NewEngine() *Engine {
	e := &Engine{
		skillCache:    make(map[string]*SkillConfig),
		flushInterval: DefaultFlushInterval,
		subAgentPIDs:  make(map[int]string),
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

	// Ensure directories exist
	os.MkdirAll(TasksDir, 0755)
	os.MkdirAll(SkillsDir, 0755)
	os.MkdirAll(filepath.Dir(e.Program.Experiments.ArchivePath), 0755)
	os.MkdirAll(e.Program.SubAgents.ResultDir, 0755)

	log.Printf("🤖 nano-os-agent v6.0 — Self-Improving Research Engine")
	log.Printf("   Board: %s (%s) | RAM: %dMB | MemLimit: %dMB",
		e.Program.Metadata.Board, e.Program.Metadata.SoC,
		e.Program.Metadata.RAMMB, e.Program.Constraints.MaxMemoryMB)
	log.Printf("   MCP: %s | Gateway: %s", MCPListenAddr, PicoClawGatewayURL)
	log.Printf("   Hypotheses: %d | Skills dir: %s",
		len(e.Program.ResearchAgenda.Hypotheses), SkillsDir)
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
	e.stateDirty = false
	e.flushCounter = 0
}

func (e *Engine) markStateDirty()    { e.stateDirty = true }
func (e *Engine) flushStateIfNeeded() {
	if !e.stateDirty {
		return
	}
	e.flushCounter++
	if e.flushCounter >= e.flushInterval {
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
	e.State.ExperimentNum++
	num := e.State.ExperimentNum
	e.mu.Unlock()

	if num%e.Program.Experiments.ArchiveInterval == 0 {
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
	// Sort by priority, pick first untested
	var candidates []Hypothesis
	for _, h := range e.Program.ResearchAgenda.Hypotheses {
		if h.Status == "untested" {
			candidates = append(candidates, h)
		}
	}
	if len(candidates) == 0 {
		return nil
	}
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].Priority < candidates[j].Priority
	})
	return &candidates[0]
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
	decoder := json.NewDecoder(conn)
	encoder := json.NewEncoder(conn)
	for {
		var req MCPRequest
		if err := decoder.Decode(&req); err != nil {
			return
		}
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
		return e.captureImage(args, resolveTimeout(30))
	case "run_yolo":
		return e.callSkill("vision_npu", args, resolveTimeout(30))
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
	e.mu.Lock()
	defer e.mu.Unlock()

	var text string
	switch uri {
	case "nano://state":
		data, _ := json.MarshalIndent(e.State, "", "  ")
		text = string(data)
	case "nano://experiments":
		entries := e.loadRecentExperiments(20)
		data, _ := json.MarshalIndent(entries, "", "  ")
		text = string(data)
	case "nano://hypotheses":
		data, _ := json.MarshalIndent(e.Program.ResearchAgenda.Hypotheses, "", "  ")
		text = string(data)
	case "nano://metrics":
		data, _ := json.MarshalIndent(e.State.Metrics, "", "  ")
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

// ════════════════════════════════════════════════════════════════════════
// PICOCLAW GATEWAY CLIENT
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) askPicoClawForTask() {
	if !e.Program.Strategy.UseLLM {
		return
	}

	prompt := e.buildTaskGenerationPrompt()
	payload := map[string]interface{}{
		"message": prompt,
		"model":   "auto",
	}
	pJSON, _ := json.Marshal(payload)

	tmpFile, err := os.CreateTemp("", "picoclaw_task_*.json")
	if err != nil {
		return
	}
	tmpFile.Write(pJSON)
	tmpFile.Close()
	defer os.Remove(tmpFile.Name())

	out, err := runCommandWithTimeout(90, "curl", "-s", "-X", "POST",
		PicoClawGatewayURL+"/api/chat",
		"-H", "Content-Type: application/json",
		"-d", "@"+tmpFile.Name())
	if err != nil {
		log.Printf("⚠️ Gateway call failed: %v", err)
		return
	}

	var resp struct {
		Response string `json:"response"`
	}
	if err := json.Unmarshal([]byte(out), &resp); err != nil {
		return
	}

	yamlContent := resp.Response
	re := regexp.MustCompile("(?s)```(?:ya?ml)?\\s*\n(.*?)\n```")
	if matches := re.FindStringSubmatch(yamlContent); len(matches) > 1 {
		yamlContent = strings.TrimSpace(matches[1])
	}

	var wrapper struct {
		Task Task `yaml:"task"`
	}
	if err := yaml.Unmarshal([]byte(yamlContent), &wrapper); err != nil {
		return
	}
	if wrapper.Task.ID == "" {
		return
	}
	if wrapper.Task.Status == "" {
		wrapper.Task.Status = "pending"
	}

	filename := fmt.Sprintf("%s/%d_llm.yaml", TasksDir, time.Now().Unix())
	taskData, _ := yaml.Marshal(map[string]interface{}{"task": wrapper.Task})
	os.WriteFile(filename, taskData, 0644)
	log.Printf("🧠 LLM generated task: %s (id: %s)", filename, wrapper.Task.ID)
}

func (e *Engine) buildTaskGenerationPrompt() string {
	skillResult, _ := nativeListSkills(e, nil)
	skillsJSON, _ := json.Marshal(skillResult)

	// Include recent experiments for context
	recentExps := e.loadRecentExperiments(MaxExperimentContext)
	expSummary := ""
	for _, exp := range recentExps {
		expSummary += fmt.Sprintf("  - [%s] %s: %s → %s\n",
			exp.Verdict, exp.TaskName, exp.TaskID, exp.Summary)
	}
	if expSummary == "" {
		expSummary = "  (no experiments yet)\n"
	}

	// Include untested hypotheses
	hypothesis := e.pickNextHypothesis()
	hypothesisCtx := ""
	if hypothesis != nil {
		hypothesisCtx = fmt.Sprintf(
			"PRIORITY HYPOTHESIS to test:\n  ID: %s\n  Claim: %s\n  Experiment: %s\n  Metric: %s\n\n",
			hypothesis.ID, hypothesis.Claim, hypothesis.Experiment, hypothesis.Metric)
	}

	// Recovery context
	recoveryCtx := ""
	if len(e.State.RecentFailures) > 0 {
		recoveryCtx = "Recent failures (avoid repeating):\n"
		for _, f := range e.State.RecentFailures {
			recoveryCtx += fmt.Sprintf("  - %s\n", f)
		}
		if len(e.Program.Strategy.Recovery) > 0 {
			recoveryCtx += "Recovery strategies:\n"
			for _, r := range e.Program.Strategy.Recovery {
				recoveryCtx += fmt.Sprintf("  - %s\n", r)
			}
		}
		recoveryCtx += "\n"
	}

	simplicity := ""
	if e.Program.Strategy.SimplicityBias {
		simplicity = "CONSTRAINT: Prefer simplest possible shell commands. One-liners are preferred over scripts.\n\n"
	}

	return fmt.Sprintf(
		"You are an autonomous hardware research agent on a LicheeRV Nano (SG2002, RISC-V, 1TOPS NPU, 256MB RAM).\n"+
			"Primary Goal: %s\n"+
			"Current Metrics: %v\n"+
			"Visual Truth: %s\n"+
			"Command Truth: %s\n"+
			"Available Skills: %s\n\n"+
			"Recent Experiment History:\n%s\n"+
			"%s"+ // hypothesis
			"%s"+ // recovery
			"%s"+ // simplicity
			"Suggest ONE new task in YAML format. Use actions: call_skill, shell_cmd, capture_image.\n"+
			"Include hypothesis_ref if testing a hypothesis.\n"+
			"```yaml\ntask:\n  id: <unique_id>\n  name: <name>\n  priority: <1-10>\n  status: pending\n"+
			"  hypothesis_ref: <optional>\n  success_criteria: []\n  steps:\n    - id: step1\n"+
			"      action: <action>\n      parameters: {}\n      expect: {}\n      timeout: 30\n      max_retries: 1\n```\n",
		e.Program.Goals.Primary,
		e.State.Metrics,
		e.State.VisualTruth, e.State.CommandTruth,
		string(skillsJSON),
		expSummary,
		hypothesisCtx,
		recoveryCtx,
		simplicity)
}

func (e *Engine) notifyPicoClaw(message string) {
	payload := map[string]interface{}{
		"message": message, "source": "nano-os-agent",
	}
	pJSON, _ := json.Marshal(payload)
	go func() {
		runCommandWithTimeout(10, "curl", "-s", "-X", "POST",
			PicoClawGatewayURL+"/api/notify",
			"-H", "Content-Type: application/json",
			"-d", string(pJSON))
	}()
}

// ════════════════════════════════════════════════════════════════════════
// VISION SYSTEM
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) captureImage(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	outputPath := paramString(params, "output_path", DefaultCapturePath)
	mode := paramString(params, "mode", "none")

	log.Printf("📸 Capturing → %s (mode=%s)", outputPath, mode)

	// Try vision_capture skill first, then fallback
	captureResult, err := e.callSkill("vision_capture", map[string]interface{}{
		"output_path": outputPath,
	}, timeout)
	if err != nil {
		// Fallback: try direct capture methods
		err = e.directCaptureFallback(outputPath, timeout)
		if err != nil {
			return nil, fmt.Errorf("capture failed: %v", err)
		}
		captureResult = map[string]interface{}{"method": "fallback"}
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
		if _, exists := result[k]; !exists {
			result[k] = v
		}
	}

	// NPU analysis if requested
	if mode == "npu" {
		npuResult, npuErr := e.callSkill("vision_npu",
			map[string]interface{}{"image_path": outputPath}, resolveTimeout(30))
		if npuErr != nil {
			result["npu_error"] = npuErr.Error()
		} else {
			for k, v := range npuResult {
				result["npu_"+k] = v
			}
		}
	}

	e.mu.Lock()
	e.State.CommandTruth = fmt.Sprintf("captured %s (%d bytes)", outputPath, info.Size())
	e.mu.Unlock()
	e.markStateDirty()
	return result, nil
}

func (e *Engine) directCaptureFallback(outputPath string, timeout int) error {
	log.Printf("📸 Direct capture fallback")
	// Method 1: ffmpeg + v4l2
	_, err := runCommandWithTimeout(timeout, "ffmpeg", "-y",
		"-f", "v4l2", "-i", "/dev/video0",
		"-frames:v", "1", "-q:v", "2", outputPath)
	if err == nil {
		if info, e := os.Stat(outputPath); e == nil && info.Size() > 0 {
			return nil
		}
	}
	// Method 2: v4l2-ctl
	_, err = runCommandWithTimeout(timeout, "v4l2-ctl",
		"--device=/dev/video0",
		"--set-fmt-video=width=640,height=480,pixelformat=MJPG",
		"--stream-mmap=3", "--stream-to="+outputPath, "--stream-count=1")
	if err == nil {
		if info, e := os.Stat(outputPath); e == nil && info.Size() > 0 {
			return nil
		}
	}
	return fmt.Errorf("all capture methods failed")
}

// ════════════════════════════════════════════════════════════════════════
// SKILL SYSTEM
// ════════════════════════════════════════════════════════════════════════

func (e *Engine) callSkill(name string, params map[string]interface{}, timeout int) (map[string]interface{}, error) {
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
	if config, ok := e.skillCache[name]; ok {
		return config, nil
	}
	skillMD := filepath.Join(SkillsDir, name, "SKILL.md")
	data, err := os.ReadFile(skillMD)
	if err != nil {
		return nil, err
	}
	re := regexp.MustCompile(`(?s)^---\s*\n(.*?)\n---`)
	matches := re.FindStringSubmatch(string(data))
	if len(matches) < 2 {
		return nil, fmt.Errorf("no frontmatter")
	}
	var config SkillConfig
	if err := yaml.Unmarshal([]byte(matches[1]), &config); err != nil {
		return nil, err
	}
	if config.Name == "" {
		config.Name = name
	}
	if config.Command != "" && !filepath.IsAbs(config.Command) {
		config.Command = filepath.Join(SkillsDir, name, config.Command)
	}
	e.skillCache[name] = &config
	return &config, nil
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

	memMB := e.Program.Constraints.MaxMemoryMB
	if memMB <= 0 {
		memMB = 64
	}
	if memMB > 0 {
		memKB := memMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s", memKB, cmdStr)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = append(os.Environ(), envVars...)
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
	if e.Program.Constraints.MaxMemoryMB > 0 {
		memKB := e.Program.Constraints.MaxMemoryMB * 1024
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; python3 %s", memKB, config.Command)
	}

	cmd := exec.Command("sh", "-c", cmdStr)
	cmd.Env = os.Environ()
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
		return e.captureImage(params, t)
	case "i2c_scan":
		return e.callSkillWithAutoGenerate("i2c_scan", params, t)
	case "probe_cvitek":
		return e.callSkillWithAutoGenerate("probe_cvitek", params, t)
	case "skill_list":
		return e.callSkillWithAutoGenerate("list_skills", nil, t)
	case "run_python_code":
		return e.executePythonCode(params, t)
	default:
		return e.callSkillWithAutoGenerate(action, params, t)
	}
}

func (e *Engine) runShellCommand(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	cmdStr := paramString(params, "cmd", "")
	if !e.isApproved(cmdStr) {
		return nil, fmt.Errorf("command blocked by security policy")
	}
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

func (e *Engine) executePythonCode(params map[string]interface{}, timeout int) (map[string]interface{}, error) {
	code := paramString(params, "code", "")
	path := filepath.Join("/tmp", fmt.Sprintf("auto_%d.py", time.Now().UnixNano()))
	os.WriteFile(path, []byte(code), 0644)
	defer os.Remove(path)
	cmdStr := fmt.Sprintf("python3 %s", path)
	if e.Program.Constraints.MaxMemoryMB > 0 {
		cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; python3 %s",
			e.Program.Constraints.MaxMemoryMB*1024, path)
	}
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
			continue
		}
		var t Task
		// 1. Try Slice format (IDE standard: - id: ...)
		var tasks []Task
		if err := yaml.Unmarshal(data, &tasks); err == nil && len(tasks) > 0 {
			for i := range tasks {
				tasks[i].SourceFile = path
				if tasks[i].Status == "pending" || tasks[i].Status == "running" {
					candidates = append(candidates, &tasks[i])
				}
			}
			continue
		}

		// 2. Try legacy wrapped format (task: id: ...)
		var wrapper struct {
			Task Task `yaml:"task"`
		}
		if err := yaml.Unmarshal(data, &wrapper); err == nil && wrapper.Task.ID != "" {
			t = wrapper.Task
		} else {
			// 3. Try flattened format (id: ...)
			if err := yaml.Unmarshal(data, &t); err != nil {
				continue
			}
		}

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

func (e *Engine) executeTask(t *Task) {
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

		maxRetries := step.MaxRetries
		if maxRetries <= 0 {
			maxRetries = e.Program.Strategy.MaxRetries
		}

		for attempt := 0; attempt <= maxRetries; attempt++ {
			resultData, err := e.dispatchAction(step.Action, step.Parameters, step.Timeout)
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
			errMsg := "unknown"
			if lastErr != nil {
				errMsg = lastErr.Error()
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
				e.saveTaskStatus(t)
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
	if stepsPassed == stepsRun && stepsRun > 0 {
		t.Status = "completed"
	} else if stepsPassed > 0 {
		t.Status = "partial"
	} else if t.Status != "blocked" {
		t.Status = "failed"
	}
	e.saveTaskStatus(t)

	// Update hypothesis if linked
	if t.HypothesisRef != "" {
		status := "inconclusive"
		switch verdict {
		case "keep":
			status = "confirmed"
		case "discard":
			status = "refuted"
		}
		e.updateHypothesisStatus(t.HypothesisRef, status)
	}

	// Record experiment
	summary := fmt.Sprintf("%d/%d steps passed, verdict=%s", stepsPassed, stepsRun, verdict)
	entry := ExperimentEntry{
		ID:            e.State.ExperimentNum + 1,
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

	log.Printf("📊 Experiment #%d: %s [%s]", entry.ID, t.Name, verdict)

	// Spawn subtasks
	e.spawnSubtasks(t)
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

func (e *Engine) saveTaskStatus(t *Task) {
	if t.SourceFile == "" {
		return
	}
	data, err := os.ReadFile(t.SourceFile)
	if err != nil {
		return
	}
	var wrapper map[string]interface{}
	if err := yaml.Unmarshal(data, &wrapper); err != nil {
		return
	}
	if taskMap, ok := wrapper["task"].(map[string]interface{}); ok {
		taskMap["status"] = t.Status
		updated, _ := yaml.Marshal(wrapper)
		os.WriteFile(t.SourceFile, updated, 0644)
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
		if e.Program.Constraints.MaxMemoryMB > 0 {
			cmdStr = fmt.Sprintf("ulimit -v %d 2>/dev/null; %s",
				e.Program.Constraints.MaxMemoryMB*1024, cmdStr)
		}
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
			e.saveState()
			return
		}

		e.State.Iteration++
		log.Printf("🔄 ─── Iteration %d ───", e.State.Iteration)

		// Update metrics periodically (not every iteration to save resources)
		if e.State.Iteration%e.Program.Loop.MetricsEveryN == 0 {
			e.updateMetrics()
		}

		// Try to find and execute a task
		task, err := e.findNextTask()
		if err != nil {
			// No tasks — try research agenda
			h := e.pickNextHypothesis()
			if h != nil {
				log.Printf("🔬 Testing hypothesis %s: %s", h.ID, h.Claim)
				e.askPicoClawForTask() // LLM will see the hypothesis in the prompt
			} else {
				// Fully idle — ask LLM for ideas with exponential backoff
				e.idleCount++
				backoff := e.idleCount * e.Program.Loop.PollInterval
				if backoff > e.Program.Loop.IdleBackoffMax {
					backoff = e.Program.Loop.IdleBackoffMax
				}
				if e.idleCount%3 == 1 { // Only ask every 3rd idle cycle
					e.askPicoClawForTask()
				}
				log.Printf("💤 Idle (backoff %ds)", backoff)
				time.Sleep(time.Duration(backoff) * time.Second)
				continue
			}
		} else {
			e.idleCount = 0
			e.executeTask(task)
		}

		e.flushStateIfNeeded()

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

// Unused import guard
var _ = base64.StdEncoding

func main() {
	engine := NewEngine()
	log.Println("═══════════════════════════════════════════")
	log.Println("  nano-os-agent v6.0")
	log.Println("  Self-Improving Autonomous Research Engine")
	log.Println("═══════════════════════════════════════════")
	engine.Run()
}
