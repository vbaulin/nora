#!/bin/sh
python3 - <<'PY'
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import math


def env(name, default=""):
    return os.environ.get("SKILL_" + name, default)


def repo_path():
    configured = env("REPO_PATH", "/root/.picoclaw/workspace/goidanich")
    if os.path.isdir(configured):
        return configured
    legacy_path = "/root/goidanich"
    if os.path.isdir(legacy_path):
        return legacy_path
    dev_path = "/Users/vbaulin/antigr/goidanich"
    if os.path.isdir(dev_path):
        return dev_path
    return configured


def parse_json_maybe(raw):
    raw = raw.strip()
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    try:
        return json.loads(raw)
    except Exception:
        return raw[-4000:]


def run(repo, cmd, timeout=300):
    proc = subprocess.run(
        cmd,
        cwd=repo,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "cmd": cmd,
        "stdout": parse_json_maybe(proc.stdout),
        "stderr": proc.stderr.strip()[-2000:],
    }


def file_summary(path, preview_bytes=1200):
    if not os.path.exists(path):
        return {"exists": False, "path": path}
    stat = os.stat(path)
    preview = ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            preview = handle.read(preview_bytes)
    except UnicodeDecodeError:
        preview = ""
    return {
        "exists": True,
        "path": path,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "mtime_iso": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "preview": preview,
    }


def sync_command(mode):
    action_map = {
        "register_agent": "--register",
        "push_events": "--push-events",
        "pull_events": "--pull-events",
        "sync_neighbours": "--pull-neighbours",
        "push_model_deltas": "--push-model-deltas",
        "pull_model_deltas": "--pull-model-deltas",
        "pull_model_version": "--pull-model-version",
        "push_training_policy": "--push-training-policy",
        "pull_training_policy": "--pull-training-policy",
        "push_product_catalog": "--push-product-catalog",
        "pull_product_catalog": "--pull-product-catalog",
        "sync_product_catalog": "--sync-product-catalog",
        "sync_all": "--all",
    }
    flag = action_map[mode]
    cmd = ["python3", "supabase_sync.py", flag]
    if mode in (
        "pull_events",
        "push_events",
        "push_model_deltas",
        "pull_model_deltas",
        "pull_model_version",
        "push_training_policy",
        "pull_training_policy",
        "sync_all",
    ):
        cmd += ["--disease", env("DISEASE", "downy_mildew")]
    if mode in ("push_training_policy", "pull_training_policy"):
        scope = env("TRAINING_POLICY_SCOPE", "")
        if scope:
            cmd += ["--training-policy-scope", scope]
    if mode == "sync_neighbours":
        neighbours_file = env("NEIGHBOURS_FILE", "neighbours.yaml")
        radius = env("NEIGHBOUR_RADIUS_KM")
        cmd += ["--neighbours-file", neighbours_file]
        if radius:
            cmd += ["--neighbour-radius-km", radius]
        if env("ALL_NEIGHBOURS", "").lower() == "true":
            cmd.append("--all-neighbours")
    if mode in ("push_product_catalog", "sync_product_catalog"):
        csv_path = env("PRODUCT_CATALOG_CSV", "unique_products.csv")
        if csv_path:
            cmd.append(csv_path)
    if mode == "sync_all":
        csv_path = env("PRODUCT_CATALOG_CSV", "unique_products.csv")
        cmd.append("--sync-product-catalog")
        if csv_path:
            cmd.append(csv_path)
    return cmd


def refresh_topology(repo):
    return run(repo, ["python3", "stations.py"], timeout=120)


def locked_daily_update(repo, disease, field, today):
    results_dir = os.path.join(repo, "results")
    os.makedirs(results_dir, exist_ok=True)
    lock_path = os.path.join(results_dir, ".vineyard_disease_daily.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {
            "ok": False,
            "already_running": True,
            "lock_path": lock_path,
            "message": "daily update is already running",
        }
    try:
        os.write(lock_fd, f"{os.getpid()} {int(time.time())}\n".encode("utf-8"))
        os.close(lock_fd)
        cmd = ["python3", "daily_update.py", "--date", env("DATE", today), "--disease", disease]
        if field:
            cmd += ["--field", field]
        if env("SKIP_SUPABASE", "").lower() == "true":
            cmd.append("--skip-supabase")
        update = run(repo, cmd, timeout=int(env("TIMEOUT", "900")))
        status = latest_status(repo, disease)
        return {
            "ok": update["ok"] and status["ok"],
            "update": update,
            "current_status": status,
            "lock_path": lock_path,
        }
    finally:
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


def latest_status(repo, disease=None):
    db = env("DB_PATH", os.path.join(repo, "goidanich.db"))
    disease = disease or env("DISEASE", "downy_mildew")
    if not os.path.exists(db):
        return {"ok": False, "error": "database missing", "db": db}
    rows = []
    field = env("FIELD")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        try:
            has_rossi = table_exists(conn, "rossi_daily_predictions")
            where = ""
            params = []
            if field:
                where = "where field_id = ?"
                params.append(field)
            if has_rossi:
                query = """
                    select field_id, day,
                           round(baseline_risk, 1) as baseline_risk,
                           case when trained = 1 then round(personalized_risk, 1) else null end as personalized_risk,
                           trained as personalized_model_trained,
                           case when trained = 1 then null else 'untrained fallback hidden' end as personalized_model_status,
                           round(coalesce(neighbor_alert_risk, 0), 1) as neighbor_alert_risk,
                           model_version,
                           case when rossi_present = 1 then round(coalesce(rossi_risk, 0), 1) else null end as rossi_risk,
                           case when rossi_present = 1 then coalesce(cohort_count, 0) else null end as rossi_cohort_count,
                           case when rossi_present = 1 then coalesce(primary_infection_events, 0) else null end as rossi_primary_events,
                           case when rossi_present = 1 then coalesce(oilspot_events, 0) else null end as rossi_oilspot_events,
                           rossi_present as rossi_available
                    from (
                        select g.*,
                               coalesce(d.trained, 0) as trained,
                               r.rossi_risk,
                               r.cohort_count,
                               r.primary_infection_events,
                               r.oilspot_events,
                               case when r.field_id is null then 0 else 1 end as rossi_present
                        from goidanich_daily_predictions g
                        left join disease_daily_predictions d
                          on d.field_id = g.field_id
                         and d.day = g.day
                         and d.station = g.station
                         and d.disease_id = ?
                        left join rossi_daily_predictions r
                          on r.field_id = g.field_id
                         and r.day = g.day
                         and r.station = g.station
                    )
                    {where}
                    order by day desc
                    limit 10
                """.format(where=where)
                params = [disease] + params
            else:
                query = """
                    select field_id, day,
                           round(baseline_risk, 1) as baseline_risk,
                           case when trained = 1 then round(personalized_risk, 1) else null end as personalized_risk,
                           trained as personalized_model_trained,
                           case when trained = 1 then null else 'untrained fallback hidden' end as personalized_model_status,
                           round(coalesce(neighbor_alert_risk, 0), 1) as neighbor_alert_risk,
                           model_version,
                           null as rossi_risk,
                           null as rossi_cohort_count,
                           null as rossi_primary_events,
                           null as rossi_oilspot_events,
                           0 as rossi_available
                    from (
                        select g.*, coalesce(d.trained, 0) as trained
                        from goidanich_daily_predictions g
                        left join disease_daily_predictions d
                          on d.field_id = g.field_id
                         and d.day = g.day
                         and d.station = g.station
                         and d.disease_id = ?
                    )
                    {where}
                    order by day desc
                    limit 10
                """.format(where=where)
                params = [disease] + params
            rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        except sqlite3.Error as exc:
            return {"ok": False, "error": str(exc), "db": db}
    return {"ok": True, "db": db, "rows": rows}


def table_exists(conn, name):
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (name,),
    ).fetchone()
    return row is not None


def safe_slug(value):
    return "".join(char if char.isalnum() or char in "_.-" else "_" for char in (value or "")) or "all"


def season_start_for(end):
    return f"{str(end)[:4]}-04-01"


def load_personalized_model(repo, field, disease):
    explicit_path = env("MODEL_PATH")
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    if field:
        candidates.append(os.path.join(repo, "models", f"{safe_slug(disease)}_personalized_{safe_slug(field)}.json"))
        candidates.append(os.path.join(repo, "models", f"personalized_{safe_slug(field)}.json"))
    candidates.append(os.path.join(repo, "models", f"{safe_slug(disease)}_shared_personalized_model.json"))
    candidates.append(os.path.join(repo, "models", f"{safe_slug(disease)}_personalized_all.json"))
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as handle:
                model = json.load(handle)
            if model.get("disease_id", disease) != disease:
                continue
            model["_path"] = candidate
            return model
    return None


def sigmoid(value):
    if value < -60:
        return 0.0
    if value > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-value))


def score_model(model, features):
    eta = float(model.get("intercept", 0.0))
    missing = []
    for spec in model.get("features", []):
        name = spec.get("name")
        mean = float(spec.get("mean", 0.0))
        scale = float(spec.get("scale", 1.0) or 1.0)
        weight = float(spec.get("weight", 0.0))
        raw = features.get(name, mean)
        if name not in features:
            missing.append(name)
        try:
            raw = float(raw)
        except Exception:
            raw = mean
        eta += weight * ((raw - mean) / scale)
    probability = sigmoid(eta)
    return {
        "risk": max(0.0, min(100.0, probability * 100.0)),
        "probability": probability,
        "score": eta,
        "model_version": model.get("model_version", "personalized_logistic_v1"),
        "model_id": model.get("model_id"),
        "trained": bool(model.get("training", {}).get("trained")),
        "missing_features": missing,
    }


def ensure_prediction_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS disease_daily_predictions (
            field_id TEXT,
            disease_id TEXT,
            day TEXT,
            station TEXT,
            risk REAL,
            probability REAL,
            score REAL,
            model_version TEXT,
            model_id TEXT,
            trained INTEGER,
            season_active INTEGER,
            season_reason TEXT,
            PRIMARY KEY (field_id, disease_id, day, station)
        )
    """)


def board_feature_rows(conn, field, disease, start, end):
    filters = ["COALESCE(g.season_active, 1) = 1"]
    params = []
    if field:
        filters.append("g.field_id = ?")
        params.append(field)
    if start:
        filters.append("g.day >= ?")
        params.append(start)
    if end:
        filters.append("g.day <= ?")
        params.append(end)
    query = f"""
        WITH weather AS (
            SELECT
                codi_estacio AS station,
                strftime('%Y-%m-%d', data_lectura) AS day,
                SUM(CASE WHEN codi_variable = 35 THEN valor_lectura ELSE 0 END) AS rain,
                AVG(CASE WHEN codi_variable = 32 THEN valor_lectura END) AS temp,
                AVG(CASE WHEN codi_variable = 33 THEN valor_lectura END) AS humi
            FROM meteo_raw
            GROUP BY codi_estacio, strftime('%Y-%m-%d', data_lectura)
        )
        SELECT
            g.field_id,
            g.day,
            g.station,
            COALESCE(g.baseline_risk, 0.0) AS baseline_risk,
            COALESCE(g.neighbor_alert_risk, 0.0) AS neighbor_pressure,
            COALESCE(g.local_feedback_bias, 0.0) AS local_feedback_bias,
            COALESCE(g.season_active, 1) AS season_active,
            COALESCE(g.season_reason, 'active season') AS season_reason,
            COALESCE(r.rossi_risk, 0.0) AS rossi_risk,
            COALESCE(r.cohort_count, 0) AS rossi_cohort_count,
            COALESCE(r.primary_infection_events, 0) AS rossi_primary_events,
            COALESCE(r.oilspot_events, 0) AS rossi_oilspot_events,
            COALESCE(w.rain, 0.0) AS rain_1d,
            COALESCE(w.temp, 0.0) AS temp_c,
            COALESCE(w.humi, 0.0) AS humidity_pct,
            COALESCE((
                SELECT COUNT(*)
                FROM farmer_feedback f
                WHERE COALESCE(f.field_id, '') = g.field_id
                  AND COALESCE(f.disease_id, ?) = ?
                  AND f.feedback_type = 'treatment'
                  AND date(f.timestamp) BETWEEN date(g.day, '-6 days') AND date(g.day)
            ), 0) AS treatment_7d,
            COALESCE((
                SELECT COUNT(*)
                FROM farmer_feedback f
                WHERE COALESCE(f.field_id, '') = g.field_id
                  AND COALESCE(f.disease_id, ?) = ?
                  AND f.feedback_type = 'treatment'
                  AND date(f.timestamp) BETWEEN date(g.day, '-13 days') AND date(g.day)
            ), 0) AS treatment_14d,
            COALESCE((
                SELECT MIN(julianday(g.day) - julianday(date(f.timestamp)))
                FROM farmer_feedback f
                WHERE COALESCE(f.field_id, '') = g.field_id
                  AND COALESCE(f.disease_id, ?) = ?
                  AND f.feedback_type = 'treatment'
                  AND date(f.timestamp) <= date(g.day)
            ), 999.0) AS days_since_treatment
        FROM goidanich_daily_predictions g
        LEFT JOIN rossi_daily_predictions r
          ON r.field_id = g.field_id AND r.day = g.day AND r.station = g.station
        LEFT JOIN weather w
          ON w.station = g.station AND w.day = g.day
        WHERE {" AND ".join(filters)}
        ORDER BY g.field_id, g.station, g.day
    """
    cursor = conn.execute(query, [disease, disease, disease, disease, disease, disease] + params)
    columns = [item[0] for item in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    grouped = {}
    for row in rows:
        grouped.setdefault((row["field_id"], row["station"]), []).append(row)
    output = []
    for group in grouped.values():
        group.sort(key=lambda item: item["day"])
        for idx, row in enumerate(group):
            previous3 = group[max(0, idx - 2):idx + 1]
            previous7 = group[max(0, idx - 6):idx + 1]
            features = dict(row)
            features["rain_3d"] = sum(float(item.get("rain_1d") or 0.0) for item in previous3)
            features["rain_7d"] = sum(float(item.get("rain_1d") or 0.0) for item in previous7)
            features["humidity_3d"] = sum(float(item.get("humidity_pct") or 0.0) for item in previous3) / len(previous3)
            features["baseline_3d"] = sum(float(item.get("baseline_risk") or 0.0) for item in previous3) / len(previous3)
            features["rossi_7d"] = max(float(item.get("rossi_risk") or 0.0) for item in previous7)
            day = dt.date.fromisoformat(str(row["day"])[:10])
            angle = 2.0 * math.pi * day.timetuple().tm_yday / 366.0
            features["day_sin"] = math.sin(angle)
            features["day_cos"] = math.cos(angle)
            row["features"] = features
            output.append(row)
    return output


def board_predict(repo, disease, field):
    script = os.path.join(repo, "board_predict.py")
    if os.path.exists(script):
        cmd = ["python3", "board_predict.py", "--disease", disease]
        if field:
            cmd += ["--field", field]
        if env("DB_PATH"):
            cmd += ["--db", env("DB_PATH")]
        if env("START"):
            cmd += ["--start", env("START")]
        if env("END"):
            cmd += ["--end", env("END")]
        if env("DATE"):
            cmd += ["--date", env("DATE")]
        if env("DAYS"):
            cmd += ["--days", env("DAYS")]
        if env("MODEL_PATH"):
            cmd += ["--model", env("MODEL_PATH")]
        output = run(repo, cmd, timeout=int(env("TIMEOUT", "120")))
        return {
            "ok": output["ok"],
            "backend": "goidanich_board_predict",
            "command": output,
        }

    db = env("DB_PATH", os.path.join(repo, "goidanich.db"))
    model = load_personalized_model(repo, field, disease)
    if not model:
        return {"ok": False, "error": "no personalized model found", "field": field or "all", "disease": disease}
    end = env("END") or env("DATE") or dt.date.today().isoformat()
    start = env("START")
    if not start and env("DAYS"):
        start = (dt.date.fromisoformat(end) - dt.timedelta(days=int(env("DAYS")) - 1)).isoformat()
    with sqlite3.connect(db) as conn:
        ensure_prediction_table(conn)
        rows = board_feature_rows(conn, field, disease, start, end)
        scored = []
        for row in rows:
            score = score_model(model, row["features"])
            conn.execute(
                """
                INSERT OR REPLACE INTO disease_daily_predictions
                    (field_id, disease_id, day, station, risk, probability, score,
                     model_version, model_id, trained, season_active, season_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["field_id"], disease, row["day"], row["station"],
                    score["risk"], score["probability"], score["score"],
                    score["model_version"], score.get("model_id"),
                    1 if score.get("trained") else 0,
                    int(row.get("season_active", 1)), row.get("season_reason", "active season"),
                ),
            )
            if disease == "downy_mildew":
                conn.execute(
                    """
                    UPDATE goidanich_daily_predictions
                    SET personalized_risk = ?, model_version = ?
                    WHERE field_id = ? AND day = ? AND station = ?
                    """,
                    (score["risk"], score["model_version"], row["field_id"], row["day"], row["station"]),
                )
            scored.append({
                "field_id": row["field_id"],
                "day": row["day"],
                "station": row["station"],
                "risk": round(score["risk"], 2),
                "probability": round(score["probability"], 4),
                "model_version": score["model_version"],
                "model_id": score.get("model_id"),
                "trained": score.get("trained"),
                "missing_features": score.get("missing_features", []),
            })
    return {
        "ok": True,
        "db": db,
        "model": model.get("_path"),
        "field": field or "all",
        "disease": disease,
        "start": start,
        "end": end,
        "rows": len(scored),
        "predictions": scored[-10:],
    }


def board_plot(repo, disease, field):
    db = env("DB_PATH", os.path.join(repo, "goidanich.db"))
    end = env("END") or env("DATE") or dt.date.today().isoformat()
    start = env("START")
    if not start:
        days = int(env("DAYS", "365"))
        start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()
    output_dir = env("OUTPUT_DIR", "results")
    os.makedirs(os.path.join(repo, output_dir), exist_ok=True)
    safe_field = safe_slug(field or "all")
    out_path = os.path.join(repo, output_dir, f"board_risk_{safe_field}_{end}.svg")
    params = [disease, start, end]
    filters = ["d.disease_id = ?", "d.day >= ?", "d.day <= ?"]
    if field:
        filters.append("d.field_id = ?")
        params.append(field)
    query = f"""
        SELECT
            d.field_id,
            d.day,
            d.station,
            d.risk,
            g.baseline_risk,
            g.neighbor_alert_risk,
            g.model_version
        FROM disease_daily_predictions d
        LEFT JOIN goidanich_daily_predictions g
          ON g.field_id = d.field_id AND g.day = d.day AND g.station = d.station
        WHERE {" AND ".join(filters)}
        ORDER BY d.day
    """
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    if not rows:
        return {"ok": False, "error": "no prediction rows to plot", "db": db, "field": field or "all", "start": start, "end": end}
    width, height = 900, 420
    left, right, top, bottom = 70, 25, 35, 55
    plot_w = width - left - right
    plot_h = height - top - bottom
    days = [row["day"] for row in rows]
    n = max(1, len(rows) - 1)

    def point(idx, value):
        x = left + (idx / n) * plot_w
        y = top + (1 - max(0.0, min(100.0, float(value or 0))) / 100.0) * plot_h
        return x, y

    risk_points = " ".join(f"{point(idx, row.get('risk'))[0]:.1f},{point(idx, row.get('risk'))[1]:.1f}" for idx, row in enumerate(rows))
    baseline_rows = [row for row in rows if row.get("baseline_risk") is not None]
    baseline_points = " ".join(
        f"{point(idx, row.get('baseline_risk'))[0]:.1f},{point(idx, row.get('baseline_risk'))[1]:.1f}"
        for idx, row in enumerate(rows)
        if row.get("baseline_risk") is not None
    )
    latest = rows[-1]
    title = f"Vineyard risk {field or latest.get('field_id', 'field')} ({start} to {end})"
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{left}" y="24" font-family="sans-serif" font-size="18" font-weight="700">{title}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>',
    ]
    for value in (0, 25, 50, 70, 100):
        _, y = point(0, value)
        color = "#ddd" if value not in (50, 70) else "#c9a227"
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="{color}" stroke-dasharray="4 4"/>')
        svg.append(f'<text x="20" y="{y + 4:.1f}" font-family="sans-serif" font-size="12">{value}%</text>')
    if baseline_points:
        svg.append(f'<polyline points="{baseline_points}" fill="none" stroke="#777" stroke-width="2" stroke-dasharray="6 5"/>')
    svg.append(f'<polyline points="{risk_points}" fill="none" stroke="#b42318" stroke-width="3"/>')
    svg.append(f'<text x="{left}" y="{height - 24}" font-family="sans-serif" font-size="12">{days[0]} -> {days[-1]}</text>')
    svg.append(f'<text x="{left + 220}" y="{height - 24}" font-family="sans-serif" font-size="12" fill="#b42318">personalized risk</text>')
    svg.append(f'<text x="{left + 370}" y="{height - 24}" font-family="sans-serif" font-size="12" fill="#777">baseline</text>')
    svg.append(f'<text x="{left + 520}" y="{height - 24}" font-family="sans-serif" font-size="12">latest: {float(latest.get("risk") or 0):.1f}%</text>')
    svg.append("</svg>")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(svg))
    return {
        "ok": True,
        "db": db,
        "field": field or "all",
        "disease": disease,
        "start": start,
        "end": end,
        "rows": len(rows),
        "plot": out_path,
        "latest": latest,
    }


def health(repo):
    required = [
        "agent_config.yaml",
        "network_config.yaml",
        "disease_tasks.yaml",
        "daily_update.py",
        "black_rot.py",
        "predict_period.py",
        "record_feedback.py",
        "personalized_predict.py",
        "goidanich.db",
    ]
    checks = {path: os.path.exists(os.path.join(repo, path)) for path in required}
    return {
        "ok": os.path.isdir(repo) and all(checks.values()),
        "repo_path": repo,
        "checks": checks,
    }


def main():
    repo = repo_path()
    mode = env("MODE", "current_status")
    disease = env("DISEASE", "downy_mildew")
    field = env("FIELD")
    today = dt.date.today().isoformat()

    try:
        if not os.path.isdir(repo):
            raise FileNotFoundError(f"goidanich repo not found: {repo}")

        if mode == "health":
            result = health(repo)
            status = "success" if result["ok"] else "error"

        elif mode == "daily_update":
            cmd = ["python3", "daily_update.py", "--date", env("DATE", today), "--disease", disease]
            if field:
                cmd += ["--field", field]
            if env("SKIP_SUPABASE", "").lower() == "true":
                cmd.append("--skip-supabase")
            result = run(repo, cmd)
            status = "success" if result["ok"] else "error"

        elif mode == "current_status":
            result = latest_status(repo, disease)
            status = "success" if result["ok"] else "error"

        elif mode in ("board_predict", "predict_personalized_sqlite"):
            result = board_predict(repo, disease, field)
            status = "success" if result["ok"] else "error"

        elif mode in ("board_plot", "plot_board_risk"):
            result = board_plot(repo, disease, field)
            status = "success" if result["ok"] else "error"

        elif mode in ("board_fill_gaps", "fill_gaps"):
            script = os.path.join(repo, "board_fill_gaps.py")
            if not os.path.exists(script):
                raise FileNotFoundError(f"board_fill_gaps.py missing in {repo}")
            cmd = [
                "python3", "board_fill_gaps.py",
                "--field", field,
                "--start", env("START"),
                "--end", env("END") or env("DATE", today),
                "--disease", disease,
                "--retry-attempts", env("RETRY_ATTEMPTS", "0"),
                "--retry-delay-minutes", env("RETRY_DELAY_MINUTES", "0"),
            ]
            if env("DB_PATH"):
                cmd += ["--db", env("DB_PATH")]
            result = run(repo, cmd, timeout=int(env("TIMEOUT", "300")))
            status = "success" if result["ok"] and isinstance(result.get("stdout"), dict) and result["stdout"].get("ok") else "error"

        elif mode in ("board_update_dashboard", "update_dashboard_files"):
            script = os.path.join(repo, "board_update_dashboard.py")
            if not os.path.exists(script):
                raise FileNotFoundError(f"board_update_dashboard.py missing in {repo}")
            end = env("END") or today
            start = env("START")
            if not start:
                days = int(env("DAYS", "31"))
                start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()
            cmd = [
                "python3", "board_update_dashboard.py",
                "--field", field,
                "--disease", disease,
                "--start", start,
                "--end", end,
                "--days", env("DAYS", "31"),
                "--warm-start", env("WARM_START", season_start_for(end)),
            ]
            if env("DB_PATH"):
                cmd += ["--db", env("DB_PATH")]
            if env("OUTPUT_DIR"):
                cmd += ["--output-dir", env("OUTPUT_DIR")]
            if env("SKIP_PREDICT", "").lower() == "true":
                cmd.append("--skip-predict")
            if env("SKIP_MODEL_REFRESH", "").lower() == "true":
                cmd.append("--skip-model-refresh")
            if env("SKIP_FILL_GAPS", "").lower() == "true":
                cmd.append("--skip-fill-gaps")
            if env("SKIP_FORECAST", "").lower() == "true":
                cmd.append("--skip-forecast")
            if env("ALLOW_FALLBACK_PLOT", "").lower() == "true":
                cmd.append("--allow-fallback-plot")
            result = run(repo, cmd, timeout=int(env("TIMEOUT", "900")))
            if isinstance(result.get("stdout"), dict) and isinstance(result["stdout"].get("plot"), str):
                plot = result["stdout"]["plot"]
                if plot and not os.path.isabs(plot):
                    result["stdout"]["plot"] = os.path.join(repo, plot)
            status = "success" if result["ok"] and isinstance(result.get("stdout"), dict) and result["stdout"].get("ok") else "error"

        elif mode == "cron_daily":
            result = locked_daily_update(repo, disease, field, today)
            status = "success" if result["ok"] else "error"

        elif mode in (
            "register_agent",
            "push_events",
            "pull_events",
            "sync_neighbours",
            "push_model_deltas",
            "pull_model_version",
            "push_product_catalog",
            "pull_product_catalog",
            "sync_product_catalog",
            "sync_all",
            "supabase_sync",
        ):
            sync_mode = "sync_all" if mode == "supabase_sync" else mode
            sync = run(repo, sync_command(sync_mode), timeout=int(env("TIMEOUT", "300")))
            result = {"sync": sync}
            if sync_mode in ("sync_neighbours", "sync_all"):
                result["topology"] = refresh_topology(repo)
                result["topology_optional"] = True
                result["neighbours"] = file_summary(os.path.join(repo, env("NEIGHBOURS_FILE", "neighbours.yaml")))
            status = "success" if sync["ok"] else "error"

        elif mode == "latest_neighbours":
            neighbours_path = os.path.join(repo, env("NEIGHBOURS_FILE", "neighbours.yaml"))
            result = file_summary(neighbours_path)
            status = "success" if result["exists"] else "error"

        elif mode == "predict_period":
            key = env("KEY", "board_report")
            cmd = [
                "python3", "predict_period.py",
                "--start", env("START"),
                "--end", env("END"),
                "--key", key,
                "--disease", disease,
            ]
            if field:
                cmd += ["--field", field]
            if env("OUTPUT_DIR"):
                cmd += ["--output-dir", env("OUTPUT_DIR")]
            if env("NO_PLOT", "").lower() == "true":
                cmd.append("--no-plot")
            result = run(repo, cmd)
            status = "success" if result["ok"] else "error"

        elif mode == "record_feedback":
            feedback = env("FEEDBACK_TYPE")
            if not feedback:
                raise ValueError("feedback_type is required")
            cmd = ["python3", "record_feedback.py", "--disease", disease]
            if field:
                cmd += ["--field", field]
            if feedback == "grade":
                cmd += ["grade", "--grade", env("GRADE")]
            else:
                cmd.append(feedback)
            if env("SEVERITY"):
                cmd += ["--severity", env("SEVERITY")]
            if env("NOTES"):
                cmd += ["--notes", env("NOTES")]
            if env("OBSERVED_AT"):
                cmd += ["--observed-at", env("OBSERVED_AT")]
            if env("PRODUCT"):
                cmd += ["--product", env("PRODUCT")]
            if env("PRODUCT_NUMBER"):
                cmd += ["--product-number", env("PRODUCT_NUMBER")]
            if env("LOT"):
                cmd += ["--lot", env("LOT")]
            if env("DOSE"):
                cmd += ["--dose", env("DOSE")]
            if env("WATER_VOLUME"):
                cmd += ["--water-volume", env("WATER_VOLUME")]
            if env("AREA"):
                cmd += ["--area", env("AREA")]
            if env("METHOD"):
                cmd += ["--method", env("METHOD")]
            if env("TARGET"):
                cmd += ["--target", env("TARGET")]
            if env("TREATMENT_TYPE"):
                cmd += ["--treatment-type", env("TREATMENT_TYPE")]
            if env("PRODUCTS_JSON"):
                cmd += ["--products-json", env("PRODUCTS_JSON")]
            if env("DB_PATH"):
                cmd += ["--db", env("DB_PATH")]
            recorded = run(repo, cmd)
            dashboard = {"ok": True, "skipped": True}
            if recorded["ok"] and env("SKIP_DASHBOARD_UPDATE", "").lower() != "true":
                end = (recorded.get("stdout") or {}).get("timestamp", today)[:10] if isinstance(recorded.get("stdout"), dict) else today
                start = (dt.date.fromisoformat(end) - dt.timedelta(days=int(env("DAYS", "31")) - 1)).isoformat()
                dashboard_cmd = [
                    "python3", "board_update_dashboard.py",
                    "--field", field,
                    "--disease", disease,
                    "--start", start,
                    "--end", end,
                    "--days", env("DAYS", "31"),
                    "--warm-start", env("WARM_START", season_start_for(end)),
                ]
                if env("DB_PATH"):
                    dashboard_cmd += ["--db", env("DB_PATH")]
                dashboard = run(repo, dashboard_cmd, timeout=int(env("TIMEOUT", "900")))
            sync = {"ok": True, "skipped": True}
            if recorded["ok"] and env("SKIP_SUPABASE", "").lower() != "true":
                sync = run(repo, ["python3", "supabase_sync.py", "--push-events", "--disease", disease], timeout=int(env("SYNC_TIMEOUT", "300")))
            result = {"recorded": recorded, "dashboard": dashboard, "sync": sync}
            status = "success" if recorded["ok"] and dashboard.get("ok", False) and sync.get("ok", False) else "error"

        elif mode == "score_features":
            model_path = env("MODEL_PATH")
            features_json = env("FEATURES_JSON")
            if not model_path or not features_json:
                raise ValueError("model_path and features_json are required")
            binary_candidates = [
                os.path.join(repo, "personalized_score"),
                os.path.join(repo, "cmd", "personalized_score", "personalized_score"),
            ]
            binary = next((path for path in binary_candidates if os.path.exists(path) and os.access(path, os.X_OK)), "")
            if binary:
                cmd = [binary, "--model", model_path, "--features", features_json]
            elif shutil.which("go"):
                cmd = ["go", "run", "./cmd/personalized_score", "--model", model_path, "--features", features_json]
            else:
                raise RuntimeError("no personalized_score binary and go is not installed")
            result = run(repo, cmd)
            status = "success" if result["ok"] else "error"

        else:
            raise ValueError(f"unknown mode: {mode}")

        payload = {
            "status": status,
            "mode": mode,
            "repo_path": repo,
            "disease": disease,
            "field": field or "all",
            "result": result,
        }
        print(json.dumps(payload))
        if status != "success":
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "mode": mode,
            "repo_path": repo,
            "message": str(exc),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
PY
