"""Cut the 1:28 PM screen recording into the final demo and lay the 4 voiceover clips on it (original audio dropped).

  python3 cut_demo_video.py                                   silent draft with default timings
  python3 cut_demo_video.py --clips c1.mp3 c2.mp3 c3.mp3 c4.mp3 final video, segments timed to the clips

Segments: A = live run cropped to the terminal window (clips 1+2), B = final terminal screen held (clip 3),
C = results chart (clip 4). If clips 1+2 run longer than A, A's last frame is held.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REC = sorted(glob.glob(os.path.expanduser("~/Desktop/Screen Recording 2026-10-17 at 1.28.16*.mov")))
A_START, A_END = 12.8, 34.0        # enlarged window with title card -> just before the chart window opens
TITLE_HOLD = 2.5                   # extra seconds on the title card
B_FRAME = 45.0                     # terminal over the chart: receipt tail + solo vs Proof of Done panels
CROP = "crop=1784:1232:784:128"    # the Terminal window (no title bar) in the 3024x1964 recording
W, H, BG = 1920, 1080, "white"
FIT = f"scale=-2:{H},pad={W}:{H}:(ow-iw)/2:0:{BG},setsar=1,fps=30,format=yuv420p"


def dur(p: str) -> float:
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p],
                       capture_output=True, text=True, check=True).stdout
    return float(json.loads(o)["format"]["duration"])


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=REC[-1] if REC else None)
    ap.add_argument("--clips", nargs=4, metavar=("C1", "C2", "C3", "C4"))
    ap.add_argument("--out", default=os.path.expanduser("~/Desktop/proof_of_done_demo.mp4"))
    a = ap.parse_args()
    if not a.video:
        print("screen recording not found on the Desktop; pass --video")
        return 1
    gap = 0.4
    if a.clips:
        c = [dur(x) for x in a.clips]
        a_len = max(A_END - A_START + TITLE_HOLD, c[0] + gap + c[1] + 0.6)
        b_len, c_len = c[2] + 0.8, c[3] + 1.2
        starts = [0.0, c[0] + gap, a_len, a_len + b_len]
    else:
        a_len, b_len, c_len = A_END - A_START + TITLE_HOLD, 18.0, 14.0
    hold_a = max(0.0, a_len - (A_END - A_START) - TITLE_HOLD)
    with tempfile.TemporaryDirectory() as d:
        sa, sb, sc = (os.path.join(d, f"{x}.mp4") for x in "abc")
        ff("-ss", f"{A_START}", "-to", f"{A_END}", "-i", a.video, "-an",
           "-vf", f"{CROP},tpad=start_mode=clone:start_duration={TITLE_HOLD}:stop_mode=clone:stop_duration={hold_a:.2f},{FIT}",
           "-c:v", "libx264", "-crf", "18", sa)
        frame = os.path.join(d, "b.png")
        ff("-ss", f"{B_FRAME}", "-i", a.video, "-frames:v", "1", "-vf", CROP, frame)
        ff("-loop", "1", "-t", f"{b_len:.2f}", "-i", frame, "-vf", FIT, "-c:v", "libx264", "-crf", "18", sb)
        chart = os.path.join(HERE, "runs", "eval", "chart.png")
        ff("-loop", "1", "-t", f"{c_len:.2f}", "-i", chart, "-vf",
           f"scale={W}:-2,pad={W}:{H}:0:(oh-ih)/2:{BG},setsar=1,fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "18", sc)
        silent = os.path.join(d, "silent.mp4")  # re-encoded join (stream-copy concat of mixed segments glitches)
        ff("-i", sa, "-i", sb, "-i", sc, "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]",
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", silent)
        if not a.clips:
            ff("-i", silent, "-c", "copy", "-movflags", "+faststart", a.out)
        else:
            inputs, chains = ["-i", silent], []
            for i, (clip, st) in enumerate(zip(a.clips, starts)):
                inputs += ["-i", clip]
                chains.append(f"[{i + 1}:a]aresample=48000,adelay={int(st * 1000)}|{int(st * 1000)}[a{i}]")
            mix = ";".join(chains) + ";" + "".join(f"[a{i}]" for i in range(4)) + "amix=inputs=4:normalize=0[a]"
            ff(*inputs, "-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
               "-b:a", "192k", "-shortest", "-movflags", "+faststart", a.out)
    print(f"A {a_len:.1f}s (run, held {hold_a:.1f}s) + B {b_len:.1f}s (final screen) + C {c_len:.1f}s (chart)"
          f" -> {a.out} ({dur(a.out):.1f}s){'' if a.clips else ' [silent draft]'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
