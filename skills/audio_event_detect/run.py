#!/usr/bin/env python3
import audioop
import json
import sys
import wave


def main():
    try:
        params = json.load(sys.stdin)
    except Exception:
        params = {}
    path = params.get("audio_path", "/tmp/capture.wav")
    threshold = float(params.get("threshold_rms", 600))

    try:
        with wave.open(path, "rb") as wf:
            width = wf.getsampwidth()
            rate = wf.getframerate()
            channels = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())
        rms = audioop.rms(frames, width) if frames else 0
        peak = audioop.max(frames, width) if frames else 0
        print(json.dumps({
            "status": "success",
            "audio_path": path,
            "sample_rate": rate,
            "channels": channels,
            "rms": rms,
            "peak": peak,
            "event_detected": rms >= threshold,
            "threshold_rms": threshold,
        }))
    except Exception as exc:
        print(json.dumps({"status": "error", "audio_path": path, "message": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
