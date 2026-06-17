#!/bin/sh
# benchmark_cpu/run.sh — Simple integer benchmark for RISC-V
# Environment inputs: SKILL_ITERATIONS

ITERS="${SKILL_ITERATIONS:-100000}"

# Use shell arithmetic as benchmark (available everywhere)
START=$(date +%s%N 2>/dev/null || date +%s)

i=0
sum=0
while [ $i -lt "$ITERS" ]; do
    sum=$((sum + i * 3 + 17))
    i=$((i + 1))
done

END=$(date +%s%N 2>/dev/null || date +%s)

# Calculate elapsed (handle both nanosecond and second precision)
if [ ${#START} -gt 10 ]; then
    ELAPSED_NS=$((END - START))
    ELAPSED_MS=$((ELAPSED_NS / 1000000))
else
    ELAPSED_MS=$(( (END - START) * 1000 ))
fi

if [ "$ELAPSED_MS" -gt 0 ]; then
    OPS_PER_SEC=$(( ITERS * 1000 / ELAPSED_MS ))
else
    OPS_PER_SEC=$ITERS
fi

cat <<EOF
{
  "ops_per_second": ${OPS_PER_SEC},
  "elapsed_ms": ${ELAPSED_MS},
  "iterations": ${ITERS},
  "checksum": ${sum}
}
EOF
