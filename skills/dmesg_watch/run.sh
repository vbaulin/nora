#!/bin/sh
# dmesg_watch/run.sh — Parse kernel messages for hardware diagnostics
# Environment inputs: SKILL_LINES, SKILL_FILTER

LINES="${SKILL_LINES:-30}"
FILTER="${SKILL_FILTER:-error|fail|warn|cvi|sensor}"

# Collect filtered lines
ALL=$(dmesg 2>/dev/null | tail -n "${LINES}")
MATCHED=$(echo "$ALL" | grep -iE "$FILTER" 2>/dev/null || true)

ERRORS=$(echo "$MATCHED" | grep -ic 'error' 2>/dev/null || echo 0)
WARNINGS=$(echo "$MATCHED" | grep -ic 'warn' 2>/dev/null || echo 0)
CVI_MSGS=$(echo "$MATCHED" | grep -ic 'cvi' 2>/dev/null || echo 0)
TOTAL=$(echo "$MATCHED" | grep -c '.' 2>/dev/null || echo 0)

# Escape quotes in output for JSON safety
RECENT=$(echo "$MATCHED" | tail -5 | sed 's/"/\\"/g' | tr '\n' '|' | sed 's/|$//')

cat <<EOF
{
  "total_matches": ${TOTAL},
  "errors": ${ERRORS},
  "warnings": ${WARNINGS},
  "cvitek_messages": ${CVI_MSGS},
  "recent_lines": "${RECENT}"
}
EOF
