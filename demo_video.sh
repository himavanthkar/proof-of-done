#!/usr/bin/env bash
# One-take demo for the video: title card -> live solo-vs-Proof-of-Done inside NVIDIA OpenShell -> results chart.
#   ./demo_video.sh            live run (about 30-60 s)
#   ./demo_video.sh --cached   replay the last cached run (Wi-Fi fallback)
cd "$(dirname "$0")" || exit 1
clear
printf '\n\n   \033[1mProof of Done\033[0m: an agent team that has to earn "done"\n'
printf '   \033[2mCrusoe Managed Inference · NVIDIA Nemotron verifier · NVIDIA OpenShell sandbox\033[0m\n\n'
sleep 3
SANDBOX=openshell .venv/bin/python demo.py --compare "$@" \
  "Return the business-day count between two ISO dates (YYYY-MM-DD), excluding weekends"
[ -z "$NO_OPEN" ] && open runs/eval/chart.png
