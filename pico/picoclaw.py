import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import websockets

logger = logging.getLogger(__name__)

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 18790
GATEWAY_CMD = os.environ.get("PICOCLAW_GATEWAY_CMD", "/opt/picoclaw/picoclaw gateway -E")
GATEWAY_LOG_PATH = Path(os.environ.get("PICOCLAW_GATEWAY_LOG", "/tmp/picoclaw_gateway.log"))
SECURITY_YML_PATH = Path(os.environ.get("PICOCLAW_SECURITY_YML", "/root/.picoclaw/.security.yml"))
PID_FILE_PATH = Path(os.environ.get("PICOCLAW_PID_FILE", "/root/.picoclaw/.picoclaw.pid"))
CONTRACT_PATHS = [
    Path(p) for p in os.environ.get(
        "PICOCLAW_CONTRACT_PATHS",
        "/root/.picoclaw/AGENTS.md:"
        "/root/.picoclaw/PICOCLAW_ORCHESTRATOR_PROMPT.md:"
        "/root/.picoclaw/AGENT.md:"
        "/root/.picoclaw/USER.md:"
        "/root/.picoclaw/SOUL.md",
    ).split(":") if p
]
SKILL_DIRS = [
    Path(p) for p in os.environ.get(
        "PICOCLAW_SKILL_DIRS",
        "/root/.picoclaw/workspace/general:"
        "/root/.picoclaw/workspace/skills:"
        "/root/.picoclaw/workplace/general:"
        "/root/.picoclaw/workplace/skills:"
        "/root/.picoclaw/general:"
        "/root/.picoclaw/skills:"
        "/root/nano-os-agent/skills",
    ).split(":") if p
]
CONTEXT_MAX_CHARS = int(os.environ.get("PICOCLAW_CONTEXT_MAX_CHARS", "22000"))
DEBUG_CONTEXT_PATH = Path(os.environ.get("PICOCLAW_DEBUG_CONTEXT", "/tmp/picoclaw_loaded_context.md"))
DEBUG_STARTUP_PATH = Path(os.environ.get("PICOCLAW_DEBUG_STARTUP", "/tmp/picoclaw_startup_diagnostics.json"))
MAX_TOOL_CALLS = int(os.environ.get("PICOCLAW_MAX_TOOL_CALLS", "8"))
GOIDANICH_REPO_PATH = Path(os.environ.get("PICOCLAW_GOIDANICH_REPO", "/root/.picoclaw/workspace/goidanich"))
PLOT_REQUEST_TERMS = (
    "plot", "plots", "graph", "graphs", "dashboard", "dashboards",
    "grafico", "graficos", "grafica", "graficas", "grafic", "grafics",
    "grafiques", "panel", "panell", "tauler",
)
PLOT_REQUEST_VERBS = (
    "show", "send", "display", "open", "view", "give", "make", "generate",
    "mostrar", "muestra", "muestrame", "ensena", "ensename", "ver", "veure",
    "mostra", "envia", "enviar", "manda", "mandar", "dame", "dona",
)


def _load_pid_token() -> str:
    try:
        if not PID_FILE_PATH.exists():
            return ""
        data = json.loads(PID_FILE_PATH.read_text(encoding="utf-8"))
        return str(data.get("token", "")).strip()
    except Exception:
        return ""


def _load_pico_token_from_yml() -> str:
    env_token = os.environ.get("PICO_TOKEN", "").strip()
    if env_token:
        return env_token

    try:
        if not SECURITY_YML_PATH.exists():
            return ""

        lines = SECURITY_YML_PATH.read_text(encoding="utf-8").splitlines()
        in_channels = False
        in_pico = False

        for raw in lines:
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip(" "))

            if not in_channels:
                if indent == 0 and stripped == "channels:":
                    in_channels = True
                continue

            if in_channels and indent == 0 and stripped != "channels:":
                break

            if not in_pico:
                if indent == 2 and stripped == "pico:":
                    in_pico = True
                continue

            if in_pico and indent <= 2:
                in_pico = False
                continue

            if in_pico and indent >= 4 and stripped.startswith("token:"):
                token = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                return token
    except Exception:
        pass

    return ""


def _load_pico_token() -> str:
    pid_token = _load_pid_token()
    pico_token = _load_pico_token_from_yml()
    if not pid_token and not pico_token:
        return ""
    return f"pico-{pid_token}{pico_token}"


@dataclass
class ToolCall:
    name: str
    args: str


@dataclass
class PicoResponse:
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    payload: dict | None = None


# Parse tool call format: 🔧 `tool_name`\n```\nargs\n```
_TOOL_RE = re.compile(r'^🔧\s*`([^`]+)`\s*\n```\n(.*?)\n```\s*$', re.DOTALL)


def _parse_message(content: str) -> ToolCall | None:
    m = _TOOL_RE.match(content.strip())
    if m:
        return ToolCall(name=m.group(1), args=m.group(2).strip())
    return None


def _normalize_intent_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _plot_delivery_intent(question: str) -> bool:
    lower = _normalize_intent_text(question).strip()
    if not lower:
        return False
    if not any(term in lower for term in PLOT_REQUEST_TERMS):
        return False

    vineyard_context_terms = (
        "vineyard", "goidanich", "mildew", "mildiu", "oidi", "oïdi",
        "oidium", "disease", "risk", "risc", "forecast", "pmi", "rossi",
        "downy", "powdery", "vinya", "vina", "vinedo", "enfermedad",
        "malaltia", "riesgo",
    )
    has_request_verb = any(term in lower for term in PLOT_REQUEST_VERBS)
    if any(term in lower for term in vineyard_context_terms):
        return has_request_verb or lower in PLOT_REQUEST_TERMS

    simple_plot_terms = (
        "plot", "plots", "dashboard", "dashboards", "grafica", "graficas",
        "grafic", "grafics", "grafiques", "panel", "panell", "tauler",
    )
    if not any(term in lower for term in simple_plot_terms):
        return False

    tokens = re.findall(r"\w+", lower)
    allowed_simple_terms = {
        "show", "send", "display", "open", "view", "give", "make", "generate",
        "plot", "plots", "graph", "graphs", "dashboard", "dashboards",
        "mostrar", "muestra", "muestrame", "ensena", "ensename", "ver", "veure",
        "mostra", "envia", "enviar", "manda", "mandar", "dame", "dona",
        "grafico", "graficos", "grafica", "graficas", "grafic", "grafics",
        "grafiques", "panel", "panell", "tauler",
        "the", "me", "my", "current", "latest", "last", "please", "pls",
        "can", "could", "you",
        "el", "la", "los", "las", "les", "els", "un", "una", "mis", "meus",
        "meves", "por", "favor", "si", "us", "plau",
    }
    return bool(tokens) and has_request_verb and all(token in allowed_simple_terms for token in tokens)


def _read_text(path: Path, limit: int = 8000) -> str:
    try:
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > limit:
            return text[:limit] + "\n...[truncated]\n"
        return text
    except Exception:
        return ""


def _contract_candidates(path: Path) -> list[Path]:
    here = Path(__file__).resolve()
    return [
        path,
        Path("/root/.picoclaw") / path.name,
        Path("/root/.picoclaw/workplace") / path.name,
        Path("/root/.picoclaw/workspace") / path.name,
        Path.cwd() / path.name,
        here.parent / path.name,
        here.parent.parent / path.name,
    ]


def _extract_frontmatter_value(text: str, key: str) -> str:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    values: dict[str, str] = {}
    for raw in parts[1].splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _skill_markdown_files(skills_dir: Path) -> list[Path]:
    if not skills_dir.exists():
        return []
    files = []
    direct = skills_dir / "SKILL.md"
    if direct.exists():
        files.append(direct)
    files.extend(sorted(skills_dir.glob("*/SKILL.md")))
    return files


def _load_skill_index(limit: int = 12000) -> str:
    entries = []
    seen = set()
    for skills_dir in SKILL_DIRS:
        if not skills_dir.exists():
            entries.append(f"## Skill directory missing: {skills_dir}")
            continue
        group = "picoClaw/orchestrator skills" if ".picoclaw" in str(skills_dir) else "nano-os-agent executor skills"
        entries.append(f"## {group}: {skills_dir}")
        for skill_md in _skill_markdown_files(skills_dir):
            text = _read_text(skill_md, 2500)
            name = _extract_frontmatter_value(text, "name") or skill_md.parent.name
            key = (name, str(skill_md.parent))
            if key in seen:
                continue
            seen.add(key)
            command = _extract_frontmatter_value(text, "command")
            input_format = _extract_frontmatter_value(text, "input_format")
            lines = []
            in_frontmatter = False
            for line in text.splitlines():
                if line.strip() == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter:
                    continue
                if line.strip():
                    lines.append(line.strip())
                if len(" ".join(lines)) > 350:
                    break
            summary = " ".join(lines)[:450]
            entries.append(f"- {name}: command={command or '?'} input={input_format or '?'} path={skill_md.parent}\n  {summary}")
    result = "\n".join(entries)
    if len(result) > limit:
        return result[:limit] + "\n...[skills truncated]\n"
    return result


def _find_skill_dir(name: str) -> Path | None:
    normalized = name.strip()
    if not normalized:
        return None
    for skills_dir in SKILL_DIRS:
        direct = skills_dir / normalized
        if (direct / "SKILL.md").exists():
            return direct
        if not skills_dir.exists():
            continue
        for skill_md in _skill_markdown_files(skills_dir):
            text = _read_text(skill_md, 3000)
            skill_name = _extract_frontmatter_value(text, "name") or skill_md.parent.name
            if skill_name == normalized or skill_md.parent.name == normalized:
                return skill_md.parent
    return None


def _json_or_text(raw: str) -> dict:
    stripped = (raw or "").strip()
    if not stripped:
        return {}
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
        return {"value": value}
    except Exception:
        return {"text": stripped}


def _skill_env(params: dict) -> dict:
    env = os.environ.copy()
    for key, value in params.items():
        env_key = "SKILL_" + re.sub(r"[^A-Za-z0-9]+", "_", str(key)).upper().strip("_")
        if isinstance(value, (dict, list)):
            env[env_key] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            env[env_key] = ""
        else:
            env[env_key] = str(value)
    return env


def _decode_skill_output(output: str) -> object:
    stripped = (output or "").strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except Exception:
        return stripped


def _run_skill(skill_name: str, params: dict | None = None) -> dict:
    params = params or {}
    skill_dir = _find_skill_dir(skill_name)
    if not skill_dir:
        return {
            "status": "error",
            "error": f"skill not found: {skill_name}",
            "searched_dirs": [str(path) for path in SKILL_DIRS],
        }

    skill_md = skill_dir / "SKILL.md"
    metadata = _parse_frontmatter(_read_text(skill_md, 12000))
    command = metadata.get("command") or "./run.sh"
    input_format = (metadata.get("input_format") or "stdin").lower()
    timeout_raw = metadata.get("timeout") or "60"
    try:
        timeout = max(1, int(float(timeout_raw)))
    except Exception:
        timeout = 60

    command_parts = command.split() if command else ["./run.sh"]
    command_path = command_parts[0]
    if command_path.startswith("./"):
        executable = skill_dir / command_path[2:]
    elif command_path.startswith("/"):
        executable = Path(command_path)
    else:
        executable = skill_dir / command_path
    if not executable.exists():
        if (skill_dir / "run.sh").exists():
            command = "./run.sh"
            command_parts = ["./run.sh"]
        elif (skill_dir / "run.py").exists():
            command = "python3 ./run.py"
            command_parts = ["python3", "./run.py"]
        else:
            return {"status": "error", "error": "skill command missing", "skill": skill_name, "path": str(skill_dir)}
    elif executable.suffix == ".py" and command_parts[0] != "python3":
        command_parts = ["python3", f"./{executable.name}", *command_parts[1:]]
    elif not command_parts[0].startswith(("/", "./")) and (skill_dir / command_parts[0]).exists():
        command_parts[0] = f"./{command_parts[0]}"

    stdin = None
    env = os.environ.copy()
    if input_format == "env":
        env = _skill_env(params)
    else:
        stdin = json.dumps(params, ensure_ascii=False)

    try:
        completed = subprocess.run(
            command_parts,
            cwd=str(skill_dir),
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "error",
            "error": "skill timeout",
            "skill": skill_name,
            "timeout": timeout,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "skill": skill_name, "path": str(skill_dir)}

    result = {
        "status": "success" if completed.returncode == 0 else "error",
        "skill": skill_name,
        "path": str(skill_dir),
        "returncode": completed.returncode,
        "stdout": _decode_skill_output(completed.stdout),
        "stderr": completed.stderr.strip(),
    }
    if isinstance(result["stdout"], dict):
        result.update(result["stdout"])
    return result


def _list_local_skills() -> dict:
    skills = []
    seen = set()
    for skills_dir in SKILL_DIRS:
        for skill_md in _skill_markdown_files(skills_dir):
            text = _read_text(skill_md, 4000)
            metadata = _parse_frontmatter(text)
            name = metadata.get("name") or skill_md.parent.name
            if (name, str(skill_md.parent)) in seen:
                continue
            seen.add((name, str(skill_md.parent)))
            skills.append({
                "name": name,
                "path": str(skill_md.parent),
                "command": metadata.get("command") or "",
                "input_format": metadata.get("input_format") or "",
            })
    return {"status": "success", "skills": skills, "skill_dirs": [str(path) for path in SKILL_DIRS]}


def execute_local_tool(name: str, args: str) -> dict:
    tool_name = name.strip()
    params = _json_or_text(args)
    if tool_name in {"list_skills", "skills.list"}:
        return _list_local_skills()

    if tool_name in {"call_skill", "run_skill", "skill"}:
        skill_name = (
            params.pop("skill_name", None)
            or params.pop("skill", None)
            or params.pop("name", None)
        )
        nested = params.pop("parameters", None)
        if isinstance(nested, dict):
            params.update(nested)
        if not skill_name:
            return {"status": "error", "error": "call_skill requires skill_name", "args": params}
        return _run_skill(str(skill_name), params)

    return _run_skill(tool_name, params)


def _load_contract_context() -> str:
    chunks = []
    loaded_paths = []
    for path in CONTRACT_PATHS:
        for candidate in _contract_candidates(path):
            text = _read_text(candidate, 7000)
            if text:
                loaded_paths.append(str(candidate))
                chunks.append(f"## Loaded Contract: {candidate}\n{text}")
                break
    chunks.insert(0, (
        "## Runtime Identity Audit\n"
        "Resolved identity: PicoClaw 🍇.\n"
        "Forbidden identity: lobster / 🦞.\n"
        "Loaded contract files:\n"
        + "\n".join(f"- {path}" for path in loaded_paths)
    ))
    chunks.append(f"## Loaded Skill Index\n{_load_skill_index()}")
    context = "\n\n".join(chunks)
    if len(context) > CONTEXT_MAX_CHARS:
        return context[:CONTEXT_MAX_CHARS] + "\n...[context truncated]\n"
    return context


def write_startup_diagnostics() -> None:
    loaded_contracts = []
    for path in CONTRACT_PATHS:
        resolved = ""
        for candidate in _contract_candidates(path):
            if candidate.exists():
                resolved = str(candidate)
                break
        loaded_contracts.append({"requested": str(path), "resolved": resolved})
    diagnostics = {
        "status": "ok",
        "module_file": __file__,
        "cwd": str(Path.cwd()),
        "identity": "PicoClaw 🍇",
        "forbidden_identity": "🦞",
        "contract_paths": loaded_contracts,
        "skill_dirs": [
            {
                "path": str(path),
                "exists": path.exists(),
                "skill_count": len(_skill_markdown_files(path)),
            }
            for path in SKILL_DIRS
        ],
        "goidanich_repo_path": str(GOIDANICH_REPO_PATH),
        "goidanich_agent_config_exists": (GOIDANICH_REPO_PATH / "agent_config.yaml").exists(),
        "default_field_id": _default_goidanich_field_id(),
        "gateway_running": gateway_running(),
        "gateway_cmd": GATEWAY_CMD,
    }
    try:
        DEBUG_STARTUP_PATH.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _default_goidanich_field_id() -> str:
    config_path = GOIDANICH_REPO_PATH / "agent_config.yaml"
    text = _read_text(config_path, 12000)
    if not text:
        return ""
    in_fields = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "fields:":
            in_fields = True
            continue
        if in_fields:
            m = re.match(r"-\s+id:\s*['\"]?([^'\"]+)['\"]?\s*$", stripped)
            if m:
                return m.group(1).strip()
            if stripped and not line.startswith(" ") and not stripped.startswith("-"):
                break
    m = re.search(r"(?ms)^local_agent:\s+.*?^\s+id:\s*['\"]?([^'\"\n]+)['\"]?", text)
    return m.group(1).strip() if m else ""


def _build_orchestrated_question(question: str) -> str:
    lower = question.lower()
    report_terms = (
        "vineyard", "goidanich", "mildew", "mildiu", "oidi", "oïdi",
        "oidium", "disease model", "disease report", "risk report",
        "risc", "forecast", "pmi", "rossi",
    )
    action_terms = (
        "risk", "alert", "warning", "status", "today", "now", "plot",
        "graph", "dashboard", "report", "summary", "update", "check",
        "predict", "prediction", "spray", "treat", "treatment",
        "feedback", "inspection", "detected", "clean", "false alarm",
    )
    product_or_treatment_advice = (
        any(term in lower for term in (
            "what product", "which product", "product should", "need to apply",
            "should i apply", "should i spray", "what should i spray",
            "i applied", "i have applied", "i sprayed", "we applied", "we sprayed",
            "used product", "applied product", "spray applied",
            "recommend product", "recommend treatment", "prescribe",
            "what product do i need", "what do i need to apply",
            "producto", "producte", "aplicar", "aplico", "aplicar", "tractament",
            "tractat", "he aplicat", "he tratado", "apliqué", "aplique",
            "tratamiento", "traté", "trate", "qué producto", "que producto", "quin producte",
            "pulverizar", "sulfatar",
        ))
        and not any(term in lower for term in ("plot", "graph", "dashboard", "report", "risc", "risk report"))
    )
    plot_intent = _plot_delivery_intent(question)
    vineyard_intent = (
        (
            any(term in lower for term in report_terms)
            and any(term in lower for term in action_terms)
        )
        or plot_intent
    )
    explicit_powdery = any(term in lower for term in ("powdery", "oidium", "oïdium"))
    explicit_downy = "downy" in lower
    deterministic_route = ""
    weather_intent = any(term in lower for term in (
        "weather", "forecast", "temperature", "rain", "humidity", "meteo",
        "wind", "heatwave", "hot", "cold",
    ))
    if product_or_treatment_advice:
        field_id = _default_goidanich_field_id() or "<field id from agent_config.yaml>"
        deterministic_route = (
            "\n\n## Deterministic Treatment/Product Advice Route\n"
            "This is a product/treatment advice question, not a report-delivery request. "
            "Do not send plots, media groups, dashboard paths, raw JSON, or the full "
            "`daily-vineyard-briefing` payload unless the user explicitly asks for a plot/report. "
            "Do not say you are unable to retrieve data unless an actual skill call failed.\n"
            "First call `list_skills`. Then call nano-os-agent skill `daily-vineyard-briefing` "
            "once with:\n"
            f"{{\"mode\":\"both_disease_report\",\"field\":\"{field_id}\","
            "\"days\":31,\"notify\":false,\"board_only\":true,\"channel\":\"picoclaw_telegram\"}\n"
            "Use the returned current risk/treatment-signal fields only as evidence. "
            "If a specific product name/code is mentioned, call `farmer-feedback-capture` "
            "with `confirmed=false` to resolve it against product_catalog and ask confirmation. "
            "Answer with ONE concise human text message in the user's language: current "
            "disease signal, whether field inspection/protection decision is due, and what "
            "information is needed before choosing/recording a product. Never attach images "
            "or forward `telegram.media` for this intent. If a skill payload contains media "
            "because of defaults, ignore media for this specific product/advice answer."
        )
    elif vineyard_intent:
        field_id = _default_goidanich_field_id() or "<field id from agent_config.yaml>"
        if explicit_powdery and not explicit_downy:
            route_body = (
                "Call nano-os-agent skill `daily-vineyard-briefing` once with:\n"
                f"{{\"mode\":\"standard_report\",\"field\":\"{field_id}\","
                "\"disease\":\"powdery_mildew\",\"days\":31,\"notify\":false,\"board_only\":true}\n"
            )
        elif explicit_downy and not explicit_powdery:
            route_body = (
                "Call nano-os-agent skill `daily-vineyard-briefing` once with:\n"
                f"{{\"mode\":\"standard_report\",\"field\":\"{field_id}\","
                "\"disease\":\"downy_mildew\",\"days\":31,\"notify\":false,\"board_only\":true}\n"
            )
        else:
            route_body = (
                "Generic vineyard report means BOTH diseases. Call nano-os-agent skill "
                "`daily-vineyard-briefing` once with:\n"
                f"{{\"mode\":\"both_disease_report\",\"field\":\"{field_id}\","
                "\"days\":31,\"notify\":false,\"board_only\":true,\"channel\":\"picoclaw_telegram\"}\n"
            )
        deterministic_route = (
            "\n\n## Deterministic Vineyard Route\n"
            "This user request is a vineyard/Goidanich report intent. Do not answer from memory. "
            f"{route_body}"
            "Use agent/orchestrator skills for Telegram and user-facing behavior; use "
            "nano-os-agent executor skills for board execution. Use the returned structured "
            "payload exactly. Send/return top-level `send_text` and `send_photo_path`. If only "
            "a photo caption is possible, use `telegram.caption` for the photo. "
            "Do not also send `telegram.text_after_photo` if it duplicates `send_text`. "
            "If `attachments` or `telegram.media` contains multiple photos, send each "
            "unique attachment once. "
            "Never replace this with a six-line prose summary. Generic reports must "
            "include both disease images and both full texts."
        )
    elif weather_intent:
        deterministic_route = (
            "\n\n## Deterministic Weather Route\n"
            "This is a weather/forecast intent. Do not answer from memory and do not infer a country. "
            "First call `list_skills` and choose the existing general weather/forecast skill from "
            "the loaded skill directories. Resolve place/coordinates from Goidanich "
            "`agent_config.yaml` or from that skill's config, then call that skill. If no weather "
            "skill is listed, say exactly that the weather skill is not loaded and include the "
            "searched skill directories. Never invent Italy, heatwave, temperatures, rain, or "
            "forecast values without a skill result."
        )
    outbound = (
        "SYSTEM OVERRIDE: discard any previous default PicoClaw persona, greeting, "
        "emoji, memory, or app demo behavior. The local contracts below are the "
        "current truth. Never use 🦞 or lobster identity. Use 🍇. If asked who you "
        "are, say you are PicoClaw 🍇, the board orchestrator that loads local "
        "skills/contracts and routes hardware through nano-os-agent. "
        "Do not answer weather, vineyard, camera, Telegram, or hardware questions "
        "from memory when a skill/config/tool route exists.\n\n"
        "You are PicoClaw, the orchestrator for nano-os-agent. "
        "Follow the loaded contracts and skill index below. For reports or Telegram output, "
        "preserve structured skill fields exactly. If a skill returns send_text, send_photo_path, "
        "must_send_exactly, or telegram.method=sendPhoto, do not summarize or replace them with prose. "
        "Return or forward the exact payload fields.\n\n"
        f"{_load_contract_context()}\n\n"
        f"{deterministic_route}\n\n"
        "## User Request\n"
        f"{question}"
    )
    try:
        DEBUG_CONTEXT_PATH.write_text(outbound, encoding="utf-8")
    except Exception:
        pass
    return outbound


def _balanced_json_candidates(content: str) -> list[str]:
    candidates = []
    for start, char in enumerate(content):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(content)):
            current = content[idx]
            if in_string:
                if escape:
                    escape = False
                elif current == "\\":
                    escape = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(content[start:idx + 1])
                    break
    return candidates


def _json_from_text(content: str) -> dict | None:
    stripped = content.strip()
    candidates = [stripped]
    candidates.extend(m.group(1).strip() for m in re.finditer(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL))
    candidates.extend(_balanced_json_candidates(content))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return None


def _payload_from_content(content: str) -> dict | None:
    payload = _json_from_text(content)
    if not isinstance(payload, dict):
        return None
    markers = {
        "send_text", "send_image_path", "send_photo_path", "must_send_exactly",
        "must_attach_image", "telegram", "notification", "telegram_payload",
        "report_guard",
    }
    if markers.intersection(payload.keys()):
        return payload
    return None


def _vineyard_risk_intent_text(content: str) -> bool:
    lower = (content or "").lower()
    vineyard_terms = (
        "vineyard", "goidanich", "avgvstvs", "station d9", "cabernet franc",
        "downy", "powdery", "mildew", "mildiu", "oidi", "oïdi", "oidium",
        "fungal", "pmi", "rossi", "treatment", "risk", "risc",
    )
    return any(term in lower for term in vineyard_terms)


def _product_or_treatment_advice_text(content: str) -> bool:
    lower = (content or "").lower()
    return any(term in lower for term in (
        "what product", "which product", "product should", "need to apply",
        "should i apply", "should i spray", "what should i spray",
        "i applied", "i have applied", "i sprayed", "we applied", "we sprayed",
        "used product", "applied product", "spray applied",
        "recommend product", "recommend treatment", "prescribe",
        "what product do i need", "what do i need to apply",
        "producto", "producte", "qué producto", "que producto", "quin producte",
        "aplicar", "aplico", "tractament", "tractat", "he aplicat",
        "tratamiento", "traté", "trate", "he tratado", "apliqué", "aplique",
        "pulverizar", "sulfatar",
    ))


def _has_current_vineyard_skill_call(response: PicoResponse) -> bool:
    for tool_call in response.tool_calls:
        name = (tool_call.name or "").strip()
        args = tool_call.args or ""
        if name in {"daily-vineyard-briefing", "vineyard-disease-risk", "daily_vineyard_briefing", "vineyard_disease_risk"}:
            return True
        if name in {"call_skill", "run_skill", "skill"} and (
            "daily-vineyard-briefing" in args or "vineyard-disease-risk" in args
            or "daily_vineyard_briefing" in args or "vineyard_disease_risk" in args
        ):
            return True
    return False


def _blocked_vineyard_memory_answer() -> str:
    return (
        "Blocked stale vineyard answer: session memory is not a truth source. "
        "I must call `daily-vineyard-briefing` with "
        '{"mode":"both_disease_report","days":31,"notify":false,"board_only":true,"channel":"picoclaw_telegram"} '
        "and return its structured text plus attachments."
    )


def _looks_like_bad_vineyard_summary(text: str) -> bool:
    lower = (text or "").lower()
    if not _vineyard_risk_intent_text(lower):
        return False
    bad_markers = (
        "general personalized risk",
        "generic personalized risk",
        "both diseases is low",
        "overall, the current risk for both diseases is low",
        "overall, the disease pressure is currently low",
        "please remember to monitor the specific powdery risk indicators",
        "refer to the specific powdery risk indicators",
        "historically been higher",
    )
    if any(marker in lower for marker in bad_markers):
        return True
    powdery_low_generic = (
        ("powdery mildew" in lower or "powdery" in lower or "oidi" in lower or "oïdi" in lower)
        and "15.0%" in lower
        and ("general" in lower or "personalized" in lower)
    )
    path_without_payload = (
        ("/root/.picoclaw/workspace/goidanich/results/" in lower or "dashboard_latest" in lower)
        and "send_text" not in lower
        and "send_photo_path" not in lower
    )
    short_summary = (
        ("downy mildew" in lower and "powdery mildew" in lower)
        and "## risk today" not in lower
        and "weather-based prediction" not in lower
        and "fungal pressure" not in lower
    )
    return powdery_low_generic or path_without_payload or short_summary


def _contract_safe_text(content: str) -> str:
    text = (content or "").strip()
    lower = text.lower()
    old_identity = (
        "🦞" in text
        or "lobster" in lower
        or "hello! i am picoclaw" in lower
        or "i am picoclaw 🦞" in lower
        or "i'm picoclaw 🦞" in lower
    )
    if old_identity:
        return (
            "PicoClaw 🍇 is online. I am the board orchestrator: I read local "
            "contracts and skills first, use nano-os-agent for hardware, and "
            "ground vineyard answers in Goidanich/Vineyard Guard outputs."
        )
    unsupported_weather_guess = (
        "weather" in lower
        and not any(marker in lower for marker in ("skill", "json", "forecast_rows", "open-meteo", "meteo_raw"))
        and any(place in lower for place in ("italy", "summer heatwave", "high pressure", "sunny"))
    )
    if unsupported_weather_guess:
        return (
            "Weather answer blocked: no weather skill result was provided. I must "
            "load/call the existing general weather or forecast skill and use the "
            "field coordinates from config instead of inventing a forecast."
        )
    unsupported_vineyard_fallback = (
        any(marker in lower for marker in (
            "unable to retrieve the latest data",
            "unable to retrieve latest data",
            "technical issue retrieving the latest risk data",
            "experiencing a technical issue retrieving",
            "cannot recommend a specific product or treatment without first verifying",
            "please give me a moment to resolve this",
            "please wait a moment while i attempt",
            "attempt to refresh the board status",
        ))
        and any(term in lower for term in ("vineyard", "board", "guard", "treatment", "product", "risk", "mildew", "pmi"))
    )
    if unsupported_vineyard_fallback:
        return (
            "Blocked unsupported Vineyard Guard fallback: I must call the relevant "
            "local skill and answer from its structured result. For product/treatment "
            "questions, use the treatment/product advice route and send one concise "
            "text message without plots unless explicitly requested."
        )
    if _looks_like_bad_vineyard_summary(text):
        return _blocked_vineyard_memory_answer()
    return text.replace("🦞", "🍇")


def _direct_vineyard_plot_response(question: str) -> PicoResponse | None:
    if not _plot_delivery_intent(question):
        return None

    params = {
        "mode": "both_disease_report",
        "repo_path": str(GOIDANICH_REPO_PATH),
        "days": 31,
        "notify": False,
        "board_only": True,
        "channel": "picoclaw_telegram",
    }
    field_id = _default_goidanich_field_id()
    if field_id:
        params["field"] = field_id

    response = PicoResponse()
    response.tool_calls.append(ToolCall(
        name="daily-vineyard-briefing",
        args=json.dumps(params, ensure_ascii=False),
    ))
    result = _run_skill("daily-vineyard-briefing", params)
    payload = result if isinstance(result, dict) else {
        "status": "error",
        "error": str(result),
    }

    telegram = payload.get("telegram") if isinstance(payload.get("telegram"), dict) else {}
    text = (
        payload.get("send_text")
        or telegram.get("caption")
        or payload.get("message")
        or ""
    )
    if not text:
        if payload.get("status") == "success":
            text = "Vineyard plots are ready."
        else:
            detail = payload.get("error") or payload.get("stderr") or "unknown error"
            text = f"Could not generate vineyard plots: {detail}"
        payload = dict(payload)
        payload["send_text"] = text
        payload["telegram"] = {**telegram, "method": "sendMessage", "text": text}

    response.payload = payload
    response.text = text
    return response


# ─────────────────────────────────────────────────────────────────────────────


class PicoclawAgent:
    def __init__(
        self,
        host: str = GATEWAY_HOST,
        port: int = GATEWAY_PORT,
        token: str | None = None,
        timeout: float = 120.0,
    ):
        self.ws_base   = f"ws://{host}:{port}/pico/ws"
        self._token    = token
        self.timeout   = timeout
        self._ws       = None
        self._session_id = None
        self._lock     = asyncio.Lock()

    @property
    def token(self) -> str:
        if self._token is not None:
            return self._token
        return _load_pico_token()

    async def _ensure_connected(self):
        if self._ws is not None and not self._ws.closed:
            return
        await ensure_gateway_running()
        self._session_id = str(uuid.uuid4())
        url     = f"{self.ws_base}?session_id={self._session_id}"
        headers = {"Authorization": f"Bearer {self.token}"}
        self._ws = await websockets.connect(url, extra_headers=headers)
        logger.info("Connected session=%s", self._session_id)

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    async def _do_ask(self, question: str, on_tool_call=None) -> PicoResponse:
        ws         = self._ws
        session_id = self._session_id
        response   = PicoResponse()

        outbound = _build_orchestrated_question(question)
        logger.debug("Send: %s", question)

        await ws.send(json.dumps({
            "type":       "message.send",
            "id":         str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp":  int(time.time() * 1000),
            "payload":    {"content": outbound},
        }, ensure_ascii=False))

        async def _recv_loop():
            tool_count = 0
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                ev_type = msg.get("type", "")
                payload = msg.get("payload") or {}

                if ev_type == "message.create":
                    content = payload.get("content", "")
                    tool_call = _parse_message(content)
                    if tool_call:
                        response.tool_calls.append(tool_call)
                        tool_count += 1
                        logger.debug("Tool: %s(%s)", tool_call.name, tool_call.args)
                        if on_tool_call:
                            await on_tool_call(tool_call)
                        if tool_count > MAX_TOOL_CALLS:
                            response.text = "Tool-call limit reached before a final answer."
                            break
                        tool_result = execute_local_tool(tool_call.name, tool_call.args)
                        tool_result_text = json.dumps(tool_result, ensure_ascii=False, indent=2)
                        logger.info("Tool result %s: %s", tool_call.name, tool_result_text[:400])
                        await ws.send(json.dumps({
                            "type":       "message.send",
                            "id":         str(uuid.uuid4()),
                            "session_id": session_id,
                            "timestamp":  int(time.time() * 1000),
                            "payload": {
                                "content": (
                                    f"Tool result for `{tool_call.name}`.\n"
                                    "Use this exact structured result. If it contains "
                                    "`send_text`, `send_photo_path`, `telegram`, or "
                                    "`must_send_exactly`, return those fields unchanged.\n"
                                    "```json\n"
                                    f"{tool_result_text}\n"
                                    "```"
                                )
                            },
                        }, ensure_ascii=False))
                    else:
                        response.payload = _payload_from_content(content)
                        if response.payload:
                            response.text = (
                                response.payload.get("send_text")
                                or (response.payload.get("telegram") or {}).get("caption")
                                or response.payload.get("message")
                                or _contract_safe_text(content)
                            )
                        else:
                            response.text = _contract_safe_text(content)
                            if (
                                _vineyard_risk_intent_text(question)
                                and _vineyard_risk_intent_text(response.text)
                                and not _has_current_vineyard_skill_call(response)
                            ):
                                response.text = _blocked_vineyard_memory_answer()
                        logger.info("Response: %s%s", response.text[:80],
                                     '...' if len(response.text) > 80 else '')
                        break

                elif ev_type == "error":
                    logger.error("Error: %s – %s", payload.get('code'),
                                 payload.get('message'))
                    break

        await asyncio.wait_for(_recv_loop(), timeout=self.timeout)
        return response

    async def ask(
        self,
        question: str,
        on_tool_call=None,  # async callable(ToolCall)
    ) -> PicoResponse:
        async with self._lock:
            direct_response = _direct_vineyard_plot_response(question)
            if direct_response:
                if on_tool_call:
                    for tool_call in direct_response.tool_calls:
                        await on_tool_call(tool_call)
                return direct_response

            for attempt in range(2):
                try:
                    await self._ensure_connected()
                    return await self._do_ask(question, on_tool_call)
                except asyncio.TimeoutError:
                    logger.warning("Timeout (%ss)", self.timeout)
                    return PicoResponse()
                except (
                    websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.ConnectionClosedError,
                    OSError,
                ) as e:
                    logger.warning("Connection closed (%s): %s",
                                   'reconnecting' if attempt == 0 else 'give up', e)
                    self._ws = None
                    if attempt > 0:
                        return PicoResponse()
                except Exception as e:
                    logger.error("Exception: %s", e)
                    self._ws = None
                    return PicoResponse()
        return PicoResponse()


def gateway_running(host: str = GATEWAY_HOST, port: int = GATEWAY_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


async def ensure_gateway_running(host: str = GATEWAY_HOST, port: int = GATEWAY_PORT) -> bool:
    if gateway_running(host, port):
        return True
    cmd = GATEWAY_CMD.split()
    if not cmd:
        return False
    try:
        GATEWAY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = open(GATEWAY_LOG_PATH, "ab", buffering=0)
        subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd="/root" if Path("/root").exists() else None,
            close_fds=True,
        )
    except Exception as exc:
        logger.error("Failed to start picoClaw gateway: %s", exc)
        return False
    for _ in range(20):
        await asyncio.sleep(0.25)
        if gateway_running(host, port):
            return True
    logger.error("picoClaw gateway did not open %s:%s", host, port)
    return False


def get_picoclaw_model() -> str:
    try:
        env = dict(os.environ)
        env["HOME"] = "/root"
        result = subprocess.run(
            ["picoclaw", "status"],
            capture_output=True, text=True, timeout=5,
            env=env, cwd="/root",
        )
        for line in result.stdout.splitlines():
            if line.startswith("Model:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    from config import setup_logging
    setup_logging()

    async def _test():
        agent = PicoclawAgent()

        async def _on_tool(tc: ToolCall):
            logger.info("Tool: %s args=%s", tc.name, tc.args)

        for q in ["Hello, introduce yourself.", "What's the weather in Shenzhen today?"]:
            resp = await agent.ask(q, on_tool_call=_on_tool)
            logger.info("=" * 60)
            if resp.tool_calls:
                logger.info("Tool calls: %s", ", ".join(tc.name for tc in resp.tool_calls))
            logger.info("Answer:\n%s", resp.text)
            logger.info("=" * 60)
            await asyncio.sleep(1)
        await agent.close()

    asyncio.run(_test())
