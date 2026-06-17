import os
import time
import json
import wave
from maix import audio

def capture_audio():
    duration = int(os.environ.get("SKILL_DURATION", 5))
    output_path = os.environ.get("SKILL_OUTPUT_PATH", "/tmp/audio.wav")
    
    sample_rate = 16000
    channels = 1
    
    try:
        # Use block=False to avoid resource contention with PicoClaw
        recorder = audio.Recorder(sample_rate=sample_rate, channel=channels, block=False)
        recorder.volume(80)
        recorder.reset(True)
        
        frames = []
        start_time = time.time()
        
        # Collect frames
        while time.time() - start_time < duration:
            # Read PCM data
            pcm = recorder.read()
            if pcm and len(pcm) > 0:
                frames.append(pcm)
            time.sleep(0.1) # Don't hog CPU
            
        # Save to WAV
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2) # S16_LE is 2 bytes
            wf.setframerate(sample_rate)
            wf.writeframes(b''.join(frames))
            
        size = os.path.getsize(output_path)
        print(json.dumps({
            "status": "success",
            "path": output_path,
            "duration": duration,
            "size": size,
            "method": "maix.audio (non-blocking)"
        }))
        
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "message": str(e)
        }))
        exit(1)

if __name__ == "__main__":
    capture_audio()
