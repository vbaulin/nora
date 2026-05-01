#!/usr/bin/env python3
import json
import os
import sys


def get_path(dct, path):
    cur = dct
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def numeric(v):
    try:
        return float(v)
    except Exception:
        return None


def main():
    try:
        params = json.load(sys.stdin)
    except Exception:
        params = {}
    journal_path = params.get("journal_path", "/tmp/monitors/grape_growth.jsonl")
    tail = int(params.get("tail", 200))

    if not os.path.exists(journal_path):
        print(json.dumps({"status": "error", "message": "journal not found", "journal_path": journal_path}))
        sys.exit(1)

    rows = []
    with open(journal_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    rows = rows[-tail:]

    fields = {
        "object_count": "result.object_count",
        "green_ratio": "result.color.green_ratio",
        "purple_ratio": "result.color.purple_ratio",
        "yellow_ratio": "result.color.yellow_ratio",
        "brown_ratio": "result.color.brown_ratio",
        "ripeness_estimate": "result.color.ripeness_estimate",
        "stress_estimate": "result.color.stress_estimate",
    }
    trends = {}
    for name, path in fields.items():
        series = [numeric(get_path(row, path)) for row in rows]
        series = [v for v in series if v is not None]
        if not series:
            continue
        trends[name] = {
            "first": series[0],
            "last": series[-1],
            "min": min(series),
            "max": max(series),
            "delta": series[-1] - series[0],
            "samples": len(series),
        }

    print(json.dumps({
        "status": "success",
        "journal_path": journal_path,
        "count": len(rows),
        "first_timestamp": rows[0].get("timestamp") if rows else None,
        "last_timestamp": rows[-1].get("timestamp") if rows else None,
        "trends": trends,
    }))


if __name__ == "__main__":
    main()
