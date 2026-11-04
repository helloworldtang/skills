#!/usr/bin/env python3
"""build.py — 把一条录屏编码成某个平台可直发的成片。

固定住的东西（都是踩过的坑）：
  · 统一转 CFR（VFR 上传会音画不同步）
  · 两遍响度归一化（先量后算，线性，不压动态）
  · H.264 level 按分辨率/帧率自动选（选低了部分播放器不认）
  · 开场卡与正片一次性重编码（用 -c copy 拼会让 AAC priming 把声音提前半秒）

用法:
    # 视频号 3:4，带 3 秒开场卡
    python3 build.py SRC.mov -o out.mp4 --start 3.8 --end 157.0 \
        --crop 1360:1722:820:242 --fit 3:4 --height 1440 \
        --card card_3x4.png --card-dur 3

    # B站 16:9
    python3 build.py SRC.mov -o out.mp4 --start 3.8 --end 157.0 \
        --crop 3024:1701:0:242 --fit 16:9 --height 1080

加 --dry-run 只打印命令不执行。加 --no-verify 跳过成片校验。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import subprocess
import sys

# (level, 最大宏块数, 最大宏块/秒) —— 只保留会用到的几档
LEVELS = [
    ("4.1", 8192, 245760),
    ("4.2", 8704, 522240),
    ("5.0", 22080, 589824),
    ("5.1", 36864, 983040),
    ("5.2", 36864, 2073600),
]


def pick_level(w: int, h: int, fps: float) -> str:
    mbs = math.ceil(w / 16) * math.ceil(h / 16)
    mbps = mbs * fps
    for name, max_frame, max_rate in LEVELS:
        if mbs <= max_frame and mbps <= max_rate:
            return name
    return "5.2"


def measure_loudness(src: str, start: float | None, end: float | None) -> dict:
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", f"{start}"]
    if end is not None:
        cmd += ["-to", f"{end}"]
    cmd += ["-i", src, "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    i, j = out.rfind("{"), out.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(out[i:j + 1])
    except json.JSONDecodeError:
        return {}


def parse_crop(s: str | None, src_w: int, src_h: int, ratio: float | None):
    if not s or s == "none":
        return None
    if s == "auto":
        if ratio is None:
            return None
        # 居中裁到目标比例，尽量保住高度
        cw = min(src_w, int(round(src_h * ratio)))
        ch = int(round(cw / ratio))
        if ch > src_h:
            ch = src_h
            cw = int(round(ch * ratio))
        x = (src_w - cw) // 2
        y = (src_h - ch) // 2
        return f"{cw}:{ch}:{x}:{y}"
    parts = s.split(":")
    if len(parts) != 4:
        raise SystemExit(f"--crop 需要 W:H:X:Y，收到 {s!r}")
    return s


def build(args) -> list[str]:
    rw, rh = (float(x) for x in args.fit.split(":")) if args.fit else (None, None)
    height = args.height
    if rw and rh and height:
        out_w = int(round(height * rw / rh / 2) * 2)
        out_h = int(height / 2) * 2
    elif args.size:
        out_w, out_h = (int(x) for x in args.size.split(":"))
    else:
        raise SystemExit("需要 --fit 16:9 --height 1080 或 --size 1920:1080")

    ratio = out_w / out_h
    crop = parse_crop(args.crop, args.src_w, args.src_h, ratio)
    level = args.level or pick_level(out_w, out_h, args.fps)

    # ---- 画幅链 ----
    # 先裁（去掉空区/事故），再等比缩放并居中补边（crop 比例与目标不一致时）
    vparts = []
    if crop:
        vparts.append(f"crop={crop}")
    vparts += [
        f"fps={args.fps}",
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos",
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}",
        "setsar=1",
        "format=yuv420p",
    ]
    main_v = ",".join(vparts)

    ln = "loudnorm=I={}:TP={}:LRA=11".format(args.loudness, args.true_peak)
    m = args.measured
    if m:
        # loudnorm 的 JSON 里所有数值都是字符串，必须显式转浮点
        mi, mtp = float(m["input_i"]), float(m["input_tp"])
        mlra, mth = float(m["input_lra"]), float(m["input_thresh"])
        moff = float(m.get("target_offset", 0) or 0)
        ln += (f":measured_I={mi:.2f}:measured_TP={mtp:.2f}"
               f":measured_LRA={mlra:.2f}:measured_thresh={mth:.2f}"
               f":offset={moff:.2f}:linear=true")
    main_a = f"{ln},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    # 录屏素材的第一个采样点往往是突变的（解码器从波形中间开始），直接编码会有一声"咔"。
    # 加上 50ms 淡入就够了，而且源片开头本来就有静音，代价为零。
    main_a += ",afade=t=in:st=0:d=0.05"
    if args.end is not None and args.start is not None:
        tail = max(0.0, (args.end - args.start) - 0.05)
        main_a += f",afade=t=out:st={tail:.3f}:d=0.05"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"]

    # ---- 输入：必须全部在 -filter_complex / -map 之前 ----
    if args.card:
        cmd += ["-loop", "1", "-framerate", str(args.fps), "-t", str(args.card_dur),
                "-i", args.card]
        cmd += ["-f", "lavfi", "-t", str(args.card_dur), "-i",
                "anullsrc=r=48000:cl=stereo"]
        main_idx = 2
    else:
        main_idx = 0
    if args.start is not None:
        cmd += ["-ss", str(args.start)]
    if args.end is not None:
        cmd += ["-to", str(args.end)]
    cmd += ["-i", args.src]

    # ---- 滤镜 ----
    if args.card:
        card_v = (f"[0:v]fps={args.fps},scale={out_w}:{out_h}:force_original_aspect_ratio=decrease"
                  f":flags=lanczos,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color},"
                  f"setsar=1,format=yuv420p[cv]")
        card_a = "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[sa]"
        main_vf = f"[{main_idx}:v]{main_v}[mv]"
        main_af = f"[{main_idx}:a]{main_a}[ma]"
        fc = ";".join([
            card_v, main_vf, card_a, main_af,
            "[cv][mv]concat=n=2:v=1:a=0[v]",
            "[sa][ma]concat=n=2:v=0:a=1[a]",
        ])
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]
    else:
        fc = f"[0:v]{main_v}[v];[0:a]{main_a}[a]"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]

    cmd += [
        "-c:v", "libx264", "-profile:v", "high", "-level", level,
        "-preset", args.preset, "-crf", str(args.crf),
        "-maxrate", args.maxrate, "-bufsize", args.bufsize,
        "-x264-params", "aq-mode=3", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", args.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        args.out,
    ]
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--start", type=float, help="起点秒（截掉开头静音）")
    ap.add_argument("--end", type=float, help="终点秒（截掉结尾事故）")
    ap.add_argument("--crop", help="W:H:X:Y，或 auto（居中裁到目标比例），或 none")
    ap.add_argument("--fit", help="目标画幅，如 16:9 / 9:16 / 3:4")
    ap.add_argument("--height", type=int, help="目标高度，配 --fit 用")
    ap.add_argument("--size", help="直接指定 WxH，如 1920:1080")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--crf", default=15)
    ap.add_argument("--maxrate", default="8M")
    ap.add_argument("--bufsize", default="16M")
    ap.add_argument("--preset", default="slow")
    ap.add_argument("--level", help="强制 H.264 level，默认自动")
    ap.add_argument("--audio-bitrate", default="192k")
    ap.add_argument("--loudness", default=-16.0)
    ap.add_argument("--true-peak", default=-1.5)
    ap.add_argument("--pad-color", default="0x111317")
    ap.add_argument("--card", help="开场卡图片（会前置静音）")
    ap.add_argument("--card-dur", type=float, default=3.0)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print(f"源文件不存在: {a.src}", file=sys.stderr)
        return 2
    if os.path.abspath(a.src) == os.path.abspath(a.out):
        print("拒绝执行：输出路径与源文件相同（源文件必须保持原样）", file=sys.stderr)
        return 2

    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", a.src],
        capture_output=True, text=True).stdout or "{}")
    st = (info.get("streams") or [{}])[0]
    a.src_w, a.src_h = st.get("width", 0), st.get("height", 0)

    if not getattr(a, "measured", None):
        print("· 测量响度（第一遍）…")
        a.measured = measure_loudness(a.src, a.start, a.end)
        if a.measured:
            print(f"  input_i={a.measured.get('input_i')} / TP={a.measured.get('input_tp')} "
                  f"/ LRA={a.measured.get('input_lra')} → 线性调节 "
                  f"{float(a.loudness) - float(a.measured.get('input_i', 0)):+.1f}dB")

    cmd = build(a)
    print("\n· 编码命令：")
    print("  " + shlex.join(cmd))
    if a.dry_run:
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    print("\n· 开始编码（长视频需要几分钟）…", flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("编码失败", file=sys.stderr)
        return r.returncode

    size = os.path.getsize(a.out) / 1048576
    print(f"\n· 完成：{a.out}  {size:.1f}MB")

    if not a.no_verify:
        vcmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify.py"),
                a.out, "--loudness", str(a.loudness)]
        if a.card:
            vcmd += ["--src", a.src, "--start", str(a.start or 0), "--card-dur", str(a.card_dur)]
        print()
        return subprocess.run(vcmd).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
