#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Webcam → RTSP publisher for MediaMTX
#
# Env vars:
#   RTSP_TARGET   – e.g. rtsp://mediamtx:8554/webcam  (required)
#   INPUT_DEVICE  – e.g. /dev/video0                   (default)
#   FALLBACK_MODE – "testsrc" | "mp4"                  (default: testsrc)
#   FALLBACK_MP4  – path to mp4 for mp4 fallback mode
# ──────────────────────────────────────────────────────────────
set -euo pipefail

RTSP_TARGET="${RTSP_TARGET:-rtsp://mediamtx:8554/webcam}"
INPUT_DEVICE="${INPUT_DEVICE:-/dev/video0}"
FALLBACK_MODE="${FALLBACK_MODE:-testsrc}"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  VigilZone Webcam → RTSP Publisher                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "  RTSP target : $RTSP_TARGET"
echo "  Input device: $INPUT_DEVICE"
echo "  Fallback    : $FALLBACK_MODE"
echo ""

# Give MediaMTX a moment to start
sleep 3

# ── Try real webcam first (Linux v4l2) ────────────────────────
if [ -e "$INPUT_DEVICE" ]; then
    echo "✓ Webcam found at $INPUT_DEVICE — publishing live feed..."
    exec ffmpeg -re \
        -f v4l2 \
        -framerate 15 \
        -video_size 640x480 \
        -i "$INPUT_DEVICE" \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -g 30 \
        -f rtsp \
        -rtsp_transport tcp \
        "$RTSP_TARGET"
fi

# ── Fallback: generate test content ───────────────────────────
echo "⚠ No webcam at $INPUT_DEVICE — using fallback mode: $FALLBACK_MODE"

if [ "$FALLBACK_MODE" = "mp4" ] && [ -n "${FALLBACK_MP4:-}" ] && [ -f "$FALLBACK_MP4" ]; then
    echo "  Looping MP4: $FALLBACK_MP4"
    exec ffmpeg -re \
        -stream_loop -1 \
        -i "$FALLBACK_MP4" \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -g 30 \
        -f rtsp \
        -rtsp_transport tcp \
        "$RTSP_TARGET"
else
    # SMPTE colour bars + timestamp overlay — looks like a real camera feed
    echo "  Generating SMPTE test pattern with timestamp..."
    exec ffmpeg -re \
        -f lavfi \
        -i "smptebars=size=640x480:rate=15" \
        -f lavfi \
        -i "sine=frequency=1000:sample_rate=44100" \
        -vf "drawtext=fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=h-40:text='%{localtime\:%Y-%m-%d %H\\\\\:%M\\\\\:%S} | VigilZone Test Feed'" \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -g 30 \
        -t 86400 \
        -f rtsp \
        -rtsp_transport tcp \
        "$RTSP_TARGET"
fi
