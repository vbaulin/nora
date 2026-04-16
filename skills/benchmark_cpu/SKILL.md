---
name: benchmark_cpu
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
parameters:
  - name: iterations
    type: string
    default: "100000"
returns:
  - ops_per_second
  - elapsed_ms
  - iterations
---
# CPU Benchmark
Simple integer arithmetic benchmark for RISC-V C906 core.
Measure baseline compute performance and detect frequency throttling.
