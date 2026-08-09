#!/bin/sh
# Deterministic Vineyard Guard scheduler tick.
# Run from BusyBox crond every few minutes. It executes local skills directly
# and never asks the LLM to interpret a scheduled job.

set -eu

export HOME=/root
export USER=root
export PICOCLAW_HOME=/root/.picoclaw
export TZ='CET-1CEST,M3.5.0,M10.5.0/3'

BASE=/root/.picoclaw/workspace
SCRIPT="$BASE/scripts/vineyard_guard_cron.py"
STATE_DIR="$BASE/goidanich/results"
LOG=/tmp/vineyard_guard_cron.log
SENDER="$BASE/scripts/telegram_outbox_sender.py"
TELEGRAM_ENV=/root/.picoclaw/telegram.env
OUTBOX=/tmp/picoclaw_outbox

mkdir -p "$STATE_DIR"

local_date="$(date +%Y-%m-%d)"
local_hm="$(date +%H%M)"

acquire_lock() {
    lock="$1"
    if mkdir "$lock" 2>/dev/null; then
        echo "$$" > "$lock/pid"
        return 0
    fi

    # Recover only locks whose owner no longer exists. This handles a prior
    # interrupted tick without allowing two live schedulers into one task.
    owner="$(cat "$lock/pid" 2>/dev/null || true)"
    case "$owner" in
        ''|*[!0-9]*) owner=0 ;;
    esac
    if [ "$owner" -gt 0 ] && kill -0 "$owner" 2>/dev/null; then
        return 1
    fi
    rm -f "$lock/pid"
    rmdir "$lock" 2>/dev/null || return 1
    mkdir "$lock" 2>/dev/null || return 1
    echo "$$" > "$lock/pid"
}

release_lock() {
    lock="$1"
    rm -f "$lock/pid"
    rmdir "$lock" 2>/dev/null || true
}

run_once() {
    task="$1"
    shift
    stamp="$STATE_DIR/.cron_${task}_${local_date}.done"
    lock="$STATE_DIR/.cron_${task}.lock"
    if [ -f "$stamp" ]; then
        return 0
    fi
    if ! acquire_lock "$lock"; then
        return 0
    fi
    {
        echo "=== $(date -Iseconds) ${task} start ==="
        if "$@"; then
            rc=0
        else
            rc=$?
        fi
        echo "=== $(date -Iseconds) ${task} exit=${rc} ==="
        if [ "$rc" -eq 0 ]; then
            date -Iseconds > "$stamp"
        fi
        release_lock "$lock"
        exit "$rc"
    } >> "$LOG" 2>&1
}

done_stamp() {
    task="$1"
    [ -f "$STATE_DIR/.cron_${task}_${local_date}.done" ]
}

# Duties above happen once a day at a fixed time. run_interval is for work that
# should simply repeat while the board is otherwise idle: it keeps one marker
# holding the epoch of the last successful run, so no stamp files accumulate.
run_interval() {
    task="$1"
    interval="$2"
    shift 2
    marker="$STATE_DIR/.cron_${task}.last"
    lock="$STATE_DIR/.cron_${task}.lock"
    now="$(date +%s)"
    if [ -f "$marker" ]; then
        last="$(cat "$marker" 2>/dev/null || echo 0)"
        case "$last" in
            ''|*[!0-9]*) last=0 ;;
        esac
        if [ "$((now - last))" -lt "$interval" ]; then
            return 0
        fi
    fi
    if ! acquire_lock "$lock"; then
        return 0
    fi
    {
        echo "=== $(date -Iseconds) ${task} start ==="
        if "$@"; then
            rc=0
        else
            rc=$?
        fi
        echo "=== $(date -Iseconds) ${task} exit=${rc} ==="
        if [ "$rc" -eq 0 ]; then
            date +%s > "$marker"
        fi
        release_lock "$lock"
        exit "$rc"
    } >> "$LOG" 2>&1
}

task_locked() {
    task="$1"
    [ -d "$STATE_DIR/.cron_${task}.lock" ]
}

send_pending() {
    if [ ! -f "$TELEGRAM_ENV" ] || [ ! -x "$SENDER" ]; then
        return 0
    fi
    if ! ls "$OUTBOX"/*.json >/dev/null 2>&1; then
        return 0
    fi
    if ! grep -l '"status": "pending"' "$OUTBOX"/*.json >/dev/null 2>&1; then
        return 0
    fi
    # shellcheck disable=SC1090
    . "$TELEGRAM_ENV"
    export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_CHAT_IDS
    export PICOCLAW_CONFIG PICOCLAW_TELEGRAM_INCLUDE_ALLOW_FROM
    "$SENDER" --once >> "$LOG" 2>&1 || true
}

case "$local_hm" in
    075[5-9])
        run_once supabase "$SCRIPT" supabase
        ;;
    080[0-9]|081[0-4])
        run_once refresh "$SCRIPT" refresh
        ;;
    081[5-9]|082[0-9]|083[0-4])
        if done_stamp refresh && ! task_locked refresh; then
            run_once alert "$SCRIPT" alert
        else
            echo "=== $(date -Iseconds) alert deferred: refresh not complete ===" >> "$LOG"
        fi
        ;;
    083[5-9]|084[0-9])
        if done_stamp alert && ! task_locked alert; then
            run_once proactive "$SCRIPT" proactive --research
        else
            echo "=== $(date -Iseconds) proactive deferred: alert evaluation not complete ===" >> "$LOG"
        fi
        ;;
    170[0-9]|171[0-4])
        run_once proactive_evening "$SCRIPT" proactive
        ;;
esac

# The scheduled duties occupy about an hour of the day. The rest of it is spent
# researching evidence the board already holds: one budgeted cycle per hour,
# never inside a duty window, and never sending anything itself.
case "$local_hm" in
    075[0-9]|08[0-4][0-9]|170[0-9]|171[0-4])
        :
        ;;
    *)
        run_interval research 3600 "$SCRIPT" research
        ;;
esac

send_pending

exit 0
