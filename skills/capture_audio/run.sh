#!/bin/sh
# capture_audio - Record audio via maix Python library
# IMPORTANT: PicoClaw (PID 550) holds the ALSA device hw:0,0 in non-blocking mode.
# So we MUST use the maix.audio.Recorder API to avoid conflicts.
#
# Environment inputs: SKILL_DURATION, SKILL_OUTPUT_PATH, SKILL_SAMPLE_RATE

DURATION="${SKILL_DURATION:-5}"
OUTPUT_PATH="${SKILL_OUTPUT_PATH:-/tmp/record.wav}"
SAMPLE_RATE="${SKILL_SAMPLE_RATE:-16000}"

python3 << 'PYEOF'
import sys
import json
import gc
import os
import signal

def sigsegv_handler(sig, frame):
    print(json.dumps({"status": "error", "code": "SIGSEGV", "message": "Audio driver crash"}))
    sys.exit(1)

signal.signal(signal.SIGSEGV, sigsegv_handler)

duration = int(os.environ.get("SKILL_DURATION", "5"))
output_path = os.environ.get("SKILL_OUTPUT_PATH", "/tmp/record.wav")
sample_rate = int(os.environ.get("SKILL_SAMPLE_RATE", "16000"))

# Cap duration to prevent disk exhaustion
if duration <= 0 or duration > 60:
    duration = 5

result = {"status": "error", "message": ""}
rec = None
frames = []

try:
    from maix import audio, app
    import numpy as np

    # Use blocking mode for nano-os-agent (PicoClaw uses non-blocking)
    rec = audio.Recorder(sample_rate=sample_rate, channel=1, block=False)
    rec.volume(24)
    rec.reset(True)

    total_samples = int(sample_rate * duration)
    chunk_size = 4096
    collected = 0

    while collected < total_samples:
        frame = rec.record(chunk_size, format="s16")
        if frame is not None and len(frame) > 0:
            frames.append(np.asarray(frame, dtype=np.int16))
            collected += len(frame)
        if app.get_exit_flag():
            break

    del rec
    gc.collect()

    if len(frames) == 0:
        result["message"] = "No audio frames captured"
        print(json.dumps(result))
        sys.exit(1)

    # Save as WAV using numpy + wave
    import numpy as np
    import wave

    audio_data = np.concatenate(frames)
    with wave.open(output_path, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

    file_size = os.path.getsize(output_path)
    result = {
        "status": "success",
        "path": output_path,
        "duration": duration,
        "sample_rate": sample_rate,
        "channels": 1,
        "format": "WAV",
        "size": file_size,
        "samples": int(collected)
    }
    print(json.dumps(result))

except Exception as e:
    result["message"] = str(e)
    print(json.dumps(result))
finally:
    del rec
    gc.collect()
PYEOF
