#!/usr/bin/env python3
import json
import os
import stat
import sys


ALLOWED_EXEC_TYPES = {"shell", "python", "api", "native"}
ALLOWED_EXTENSIONS = {".md", ".sh", ".py", ".yaml", ".yml", ".json", ".txt"}
BLOCKED_SNIPPETS = ["rm -rf /", "mkfs.", "dd if=", "dd of=", "reboot", "poweroff", "shutdown", "LD_PRELOAD"]


def parse_frontmatter(path):
    text = open(path).read()
    if not text.startswith("---"):
        raise ValueError("SKILL.md missing frontmatter")
    end = text.find("---", 3)
    if end < 0:
        raise ValueError("SKILL.md missing closing frontmatter")
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def main():
    try:
        params = json.load(sys.stdin)
    except Exception:
        params = {}
    candidate = params.get("candidate_path", "")
    require_command = bool(params.get("require_command", True))
    checks = {}

    try:
        if not candidate:
            raise ValueError("candidate_path is required")
        candidate = os.path.abspath(candidate)
        if not os.path.isdir(candidate):
            raise ValueError("candidate_path is not a directory")

        skill_md = os.path.join(candidate, "SKILL.md")
        checks["skill_md_exists"] = os.path.exists(skill_md)
        if not checks["skill_md_exists"]:
            raise ValueError("SKILL.md missing")

        meta = parse_frontmatter(skill_md)
        checks["name_present"] = bool(meta.get("name"))
        checks["exec_type_allowed"] = meta.get("exec_type") in ALLOWED_EXEC_TYPES
        checks["output_json"] = meta.get("output_format", "json") == "json"

        command = meta.get("command", "")
        if meta.get("exec_type") != "native" and require_command:
            command_path = os.path.abspath(os.path.join(candidate, command))
            checks["command_inside_candidate"] = command_path.startswith(candidate + os.sep)
            checks["command_exists"] = os.path.exists(command_path)
            if checks["command_exists"]:
                mode = os.stat(command_path).st_mode
                checks["command_executable_or_python"] = command.endswith(".py") or bool(mode & stat.S_IXUSR)

        scanned = 0
        blocked = []
        bad_ext = []
        for root, _, files in os.walk(candidate):
            for name in files:
                scanned += 1
                path = os.path.join(root, name)
                ext = os.path.splitext(name)[1]
                if ext and ext not in ALLOWED_EXTENSIONS:
                    bad_ext.append(os.path.relpath(path, candidate))
                try:
                    text = open(path, errors="ignore").read()
                except Exception:
                    continue
                for snippet in BLOCKED_SNIPPETS:
                    if snippet in text:
                        blocked.append({"file": os.path.relpath(path, candidate), "snippet": snippet})
        checks["files_scanned"] = scanned
        checks["blocked_snippets"] = blocked
        checks["bad_extensions"] = bad_ext

        failed = [k for k, v in checks.items() if v is False]
        if blocked or bad_ext:
            failed.append("content_policy")
        print(json.dumps({
            "status": "success" if not failed else "error",
            "candidate_path": candidate,
            "checks": checks,
            "failed_checks": failed,
        }))
        if failed:
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({"status": "error", "candidate_path": candidate, "message": str(exc), "checks": checks}))
        sys.exit(1)


if __name__ == "__main__":
    main()
