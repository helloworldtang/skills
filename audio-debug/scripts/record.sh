#!/bin/bash
# 录制麦克风并(可选)播放参考音，供 analyze.py 做模板匹配。
# 用法: record.sh <秒数> [输出wav] [参考音aiff ...]
#   record.sh 20                 # 录 20s（等用户复现）
#   record.sh 8 rec.wav /System/Library/Sounds/Pop.aiff   # 录音并先放参考音
set -euo pipefail

DUR="${1:-15}"
OUT="${2:-/tmp/audio_debug_rec.wav}"
shift 2 2>/dev/null || true

# 麦克风设备 ":0"（avfoundation 默认输入）；首次运行会触发授权弹窗，全静音=未授权
ffmpeg -hide_banner -loglevel error -f avfoundation -i ":0" \
    -t "$DUR" -ar 44100 -ac 1 "$OUT" -y < /dev/null > /dev/null 2>&1 &
FFPID=$!
sleep 1.5   # 等 ffmpeg 初始化完成，避免掐头

# 依次播放参考音（间隔 1.5s），录进同一环境做模板
for ref in "$@"; do
    afplay "$ref"
    sleep 1.5
done

echo "recording ${DUR}s -> $OUT (waiting for ffmpeg to finish...)"
wait $FFPID

# 快速体检：全静音说明麦克风未授权
ffmpeg -hide_banner -i "$OUT" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
