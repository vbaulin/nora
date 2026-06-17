---
name: tpu_fft
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 10
---
# TPU-Accelerated FFT
Performs a Fast Fourier Transform on input signal data using `libcvimath.so`.

### Inputs
*   `SKILL_INPUT_FILE`: Path to raw signal data (binary or JSON)
*   `SKILL_N`: FFT size (e.g., 1024, 2048)

### Use Case
Audio spectrum analysis, motor vibration monitoring, or real-time signal filtering.
Offloading FFT to the TPU frees up the RISC-V core for logic and control.
