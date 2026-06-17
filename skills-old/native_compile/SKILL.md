---
name: native_compile
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 120
---
# Native C++ Compiler Skill
Compiles C++ source code directly on the LicheeRV Nano using the verified SDK toolchain.

### Inputs
*   `SKILL_SOURCE_FILE`: Path to the .cpp source (Default: /tmp/skill.cpp)
*   `SKILL_OUTPUT_BIN`: Path for the resulting binary (Default: /tmp/skill.bin)
*   `SKILL_LIBS`: Additional libraries to link (e.g., -lcvitdl -lopencv_core)

### Use Case
Allows the autonomous agent to "learn" new hardware capabilities by compiling C++ SDK examples on-the-fly.
