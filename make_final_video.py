"""Lay a narration track (e.g. a NotebookLM Audio Overview) over the terminal screen recording.

  python3 make_final_video.py <terminal_video> <narration_audio> [--max 75] [--fit] [--out ~/Desktop/proof_of_done_demo.mp4]

The narration sets the length. If it is longer than the video, the last video frame (the results chart) is held.
--max N   cap the final length at N seconds (audio fades out over the last 2 s)
--fit     speed the narration up (at most 1.3x) to fit --max instead of cutting it
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("audio")
    ap.add_argument("--max", type=float, default=0)
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--out", default=os.path.expanduser("~/Desktop/proof_of_done_demo.mp4"))
    a = ap.parse_args()
    vd, ad = duration(a.video), duration(a.audio)
    speed = 1.0
    if a.max and a.fit and ad > a.max:
        speed = min(1.3, ad / a.max)
    length = ad / speed
    if a.max:
        length = min(length, a.max)
    pad = max(0.0, length - vd)
    afilters = []
    if speed != 1.0:
        afilters.append(f"atempo={speed:.3f}")
    if a.max and ad / speed > a.max:
        afilters.append(f"afade=t=out:st={max(0.0, length - 2):.2f}:d=2")
    vf = (f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.2f},"
          f"scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[v]")
    af = f"[1:a]{','.join(afilters) or 'anull'}[a]"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", a.video, "-i", a.audio,
           "-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", f"{length:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", a.out]
    print(f"video {vd:.1f}s, narration {ad:.1f}s, speed x{speed:.2f}, held last frame {pad:.1f}s -> {length:.1f}s")
    subprocess.run(cmd, check=True)
    print(f"wrote {a.out} ({duration(a.out):.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
