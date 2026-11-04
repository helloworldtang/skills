#!/usr/bin/env python3
"""probe.py — 录屏素材体检。

一次性输出"这条素材能不能直接发"的全部判断依据：封装/参数、帧率是否可变、
响度、静音与说话边界、内容真实占比（黑边/空区）、末尾是否混入录制事故。

依赖：ffmpeg / ffprobe / Pillow（不需要 numpy）
只读不改源文件。

用法:
    python3 probe.py SRC.mov
    python3 probe.py SRC.mov --json report.json --ratios 16:9 9:16 3:4
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from statistics import median

from PIL import Image, ImageChops, ImageDraw, ImageStat

# ---------- 基础 ----------


def run(cmd: list[str], timeout: int = 300) -> str:
    """ffmpeg/ffprobe 的诊断输出几乎全在 stderr，两条流都要。"""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")


def probe_json(src: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
               "-print_format", "json", src])
    i = out.find("{")
    return json.loads(out[i:]) if i >= 0 else {}


def parse_rate(r: str) -> float:
    if not r or r == "0/0":
        return 0.0
    if "/" in r:
        a, b = r.split("/")
        return float(a) / float(b) if float(b) else 0.0
    return float(r)


def pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def num(pattern: str, text: str, cast=float):
    import re
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


# ---------- 各检查项 ----------


def check_streams(info: dict) -> list[str]:
    lines = []
    fmt = info.get("format", {})
    dur = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    lines.append(f"- 容器 `{fmt.get('format_name')}` · 时长 **{dur:.1f}s** · "
                 f"体积 **{size/1048576:.1f}MB**")
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = s.get("width"), s.get("height")
            r = parse_rate(s.get("r_frame_rate", "0/0"))
            ar = parse_rate(s.get("avg_frame_rate", "0/0"))
            flag = ""
            if r and ar and abs(r - ar) / r > 0.05:
                flag = "  ⚠️ **标称与均值不一致 → 可变帧率**"
            lines.append(
                f"- 视频 `{s.get('codec_name')}` / {s.get('profile')} L{s.get('level')} · "
                f"**{w}x{h}** (AR {w/h:.3f}) · pix `{s.get('pix_fmt')}` · "
                f"标称 {r:.4g}fps / 均值 {ar:.2f}fps{flag}")
        elif s.get("codec_type") == "audio":
            lines.append(
                f"- 音频 `{s.get('codec_name')}` · {s.get('sample_rate')}Hz · "
                f"{s.get('channels')}ch · {int(s.get('bit_rate') or 0)//1000}kbps")
        elif s.get("codec_type") not in (None, "video", "audio"):
            lines.append(f"- 其他流: {s.get('codec_type')} `{s.get('codec_name')}`")
    return lines


def check_vfr(src: str) -> tuple[list[str], dict]:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "frame=best_effort_timestamp_time",
               "-of", "csv=p=0", src])
    ts = []
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            ts.append(float(line))
        except ValueError:
            pass
    if len(ts) < 10:
        return ["- 帧时间戳不足，跳过帧率稳定性检查"], {}
    deltas = [1000 * (ts[i] - ts[i - 1]) for i in range(1, len(ts))]
    deltas = [d for d in deltas if d > 0]
    med = median(deltas) if deltas else 0
    lo, hi = pct(deltas, 0.05), pct(deltas, 0.95)
    spread = hi / lo if lo > 0 else 99
    vfr = spread > 1.4
    lines = [
        f"- 帧数 **{len(ts)}** · 帧间隔中位 **{med:.1f}ms** · "
        f"p5–p95 跨度 {lo:.1f}–{hi:.1f}ms · 出现 {len(set(round(d,1) for d in deltas))} 种间隔"
        + ("  ⚠️ **VFR（可变帧率）→ 必须转 CFR**" if vfr else "  ✅ 恒定帧率"),
    ]
    return lines, {"frames": len(ts), "median_ms": med, "vfr": vfr,
                   "fps_equivalent": round(1000 / med, 2) if med else 0}


def check_loudness(src: str) -> tuple[list[str], dict]:
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-vn",
               "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    i = out.rfind("{")
    data = {}
    if i >= 0:
        try:
            data = json.loads(out[i:])
        except json.JSONDecodeError:
            data = {}
    vd = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-vn",
              "-af", "volumedetect", "-f", "null", "-"])
    mv = num(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", vd)
    pk = num(r"max_volume:\s*(-?\d+\.?\d*)\s*dB", vd)
    I = num(r'"input_i"\s*:\s*"(-?\d+\.?\d*)"', out) or 0.0
    TP = num(r'"input_tp"\s*:\s*"(-?\d+\.?\d*)"', out) or 0.0
    LRA = num(r'"input_lra"\s*:\s*"(-?\d+\.?\d*)"', out) or 0.0
    TH = num(r'"input_thresh"\s*:\s*"(-?\d+\.?\d*)"', out) or 0.0
    delta = -16 - I
    lines = [
        f"- 积分响度 **{I:.1f} LUFS** · 真峰 **{TP:.1f} dBTP** · "
        f"LRA {LRA:.1f} · 噪声门限 {TH:.1f}dB",
        f"- 均值电平 {mv if mv is not None else 'n/a'}dB · "
        f"峰值 {pk if pk is not None else 'n/a'}dB",
        f"- 距目标 −16 LUFS 还差 **{delta:+.1f}dB**"
        + ("  ⚠️ **必须做响度归一化**" if delta > 3 else "  ✅ 电平可用"),
    ]
    if mv is not None and mv > -40:
        lines.append(f"- ⚠️ 均值电平偏高（{mv:.0f}dB > −40dB）：之后用 "
                     f"`silencedetect -35dB` 可能误判，建议改用 **{mv-12:.0f}dB** 附近阈值，"
                     f"或只比较两条音频的**相对偏移**")
    return lines, {"input_i": I, "input_tp": TP, "input_lra": LRA,
                   "input_thresh": TH, "mean_volume": mv, "max_volume": pk,
                   "delta": delta}


def detect_silence(src: str, noise_db: float, d: float = 0.8) -> list[tuple[float, float]]:
    out = run(["ffmpeg", "-hide_banner", "-i", src, "-af",
               f"silencedetect=noise={noise_db:g}dB:d={d}", "-f", "null", "-"])
    import re
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?\d+\.?\d*)", out)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?\d+\.?\d*)", out)]
    return [(s, ends[i] if i < len(ends) else -1.0) for i, s in enumerate(starts)]


def check_edges(src: str, noise_db: float) -> tuple[list[str], dict]:
    segs = detect_silence(src, noise_db)
    lines, data = [], {}
    if not segs:
        return ["- 未检出长静音段（整条都有声）"], {}
    s0, e0 = segs[0]
    if s0 < 0.5 and e0 > 0:
        lines.append(f"- ⚠️ 开头 **{e0:.2f}s 静音** → 建议截掉"
                     f"（`--start {max(0.0, e0-0.2):.1f}`）")
        data["lead_silence_end"] = e0
    if segs[-1][1] < 0:
        lines.append(f"- 结尾从 {segs[-1][0]:.2f}s 起静音至末尾")
        data["tail_silence_start"] = segs[-1][0]
    internal = [(s, e) for s, e in segs if s > 1 and e > 0 and (e - s) > 1.0]
    if internal:
        lo, hi = max(internal, key=lambda x: x[1] - x[0])
        lines.append(f"- 片中最长静音 {lo:.1f}–{hi:.1f}s（{hi-lo:.1f}s）")
        if hi - lo > 8:
            lines.append("  → 若这段画面仍在变化，是「无解说但有信息」，**不要当废片截掉**")
        data["longest_gap"] = [lo, hi]
    return lines, data


# ---------- 画面：内容边界 + 尾部污染 ----------


def grab(src: str, t: float, path: str) -> bool:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src,
                    "-frames:v", "1", path], capture_output=True)
    return os.path.exists(path) and os.path.getsize(path) > 0


def frame_density(path: str, tol: int = 25):
    """返回 (列密度, 行密度, 背景亮度, 结构带)。

    密度 = 该列/该行里"明显亮于背景"的像素占比（0–255，BOX 缩小取均值实现）。

    两个关键处理，缺一个就测不准：
    · 背景亮度取**页面区两侧**（高度 25%–85%、避开最外 8px），
      因为整屏录屏最外 1px 常有一条亮边，取四周中位数会把它算成背景。
    · 先找出**横跨全宽的结构带**（浏览器标签栏/地址栏/页面顶栏）并在统计列宽时抹掉。
      否则每一列都掺进那 174 行亮像素，所有列看起来"都有内容"，空区永远测不出来。
    """
    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.load()
    ys = range(int(h * 0.25), int(h * 0.85), 3)
    xs = list(range(2, 8)) + list(range(w - 8, w - 2))
    bg = int(median([px[x, y] for x in xs for y in ys]))

    mask = im.point(lambda v: 255 if v > bg + tol else 0)
    row_d = list(mask.resize((1, h), Image.BOX).tobytes())

    # 连续段：行密度 > 55% 视为横跨全宽的结构带
    band = [y for y in range(h) if row_d[y] > 255 * 0.55]
    runs, s = [], None
    for y in range(h + 1):
        if y < h and y in set(band):
            if s is None:
                s = y
        elif s is not None:
            runs.append((s, y - 1))
            s = None
    if runs:
        d = ImageDraw.Draw(mask)
        for a, b in runs:
            d.rectangle([0, a, w - 1, b], fill=0)

    col_d = list(mask.resize((w, 1), Image.BOX).tobytes())
    return col_d, row_d, bg, runs


def scan_margins(dens: list[int], th_frac: float = 0.006, guard: int = 0):
    """从两端向内扫，跳过密度低于阈值的空白区。返回 (起点, 终点, 是否全空)。"""
    th = max(3, int(255 * th_frac))
    n = len(dens)
    lo, hi = guard, n - 1 - guard
    l = lo
    while l <= hi and dens[l] < th:
        l += 1
    if l > hi:
        return lo, hi, True
    r = hi
    while r > l and dens[r] < th:
        r -= 1
    return l, r, False


def check_picture(src: str, dur: float, tmp: str) -> tuple[list[str], dict]:
    ts = [dur * f for f in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95)]
    cols, rows, bgs, runs_all = [], [], [], []
    W = H = 0
    for i, t in enumerate(ts):
        p = os.path.join(tmp, f"bb{i}.png")
        if not grab(src, t, p):
            continue
        c, r, bg, runs = frame_density(p)
        W, H = Image.open(p).size
        cols.append(c); rows.append(r); bgs.append(bg); runs_all.append(runs)

    if not cols:
        return ["- 画面采样失败"], {}

    gx, gy = max(2, int(W * 0.005)), max(2, int(H * 0.005))
    cl = min(scan_margins(c, guard=gx)[0] for c in cols)
    cr = max(scan_margins(c, guard=gx)[1] for c in cols)
    rl = min(scan_margins(r, guard=gy)[0] for r in rows)
    rr = max(scan_margins(r, guard=gy)[1] for r in rows)
    bg = int(median(bgs))

    left, right = cl - gx, W - 1 - gx - cr
    top, bottom = rl - gy, H - 1 - gy - rr
    runs = runs_all[0] if runs_all else []
    data = {"frame": [W, H], "bg_luma": bg,
            "content_cols": [cl, cr], "content_rows": [rl, rr],
            "structure_bands": runs,
            "margins": {"left": left, "right": right, "top": top, "bottom": bottom}}

    lines = [
        f"- 帧尺寸 {W}x{H} · 页面背景亮度 {bg}",
        f"- 内容列范围 `x {cl}..{cr}`（宽 {cr-cl+1}px = 占宽 "
        f"**{(cr-cl+1)/W*100:.0f}%**）· 内容行范围 `y {rl}..{rr}`",
        f"- 空白边距 左 **{left}** · 右 **{right}** · 上 {top} · 下 {bottom} px",
    ]
    if runs:
        desc = "、".join(f"y {a}..{b}（{b-a+1}px）" for a, b in runs[:3])
        lines.append(f"- 检测到 {len(runs)} 条横跨全宽的结构带：{desc}"
                     f" → 统计列宽时已扣除；`--crop` 的 y 起点要给到结构带下沿以保留它")
    if left + right > W * 0.2:
        lines.append(f"- ⚠️ **左右共 {left+right}px 是空区（占宽 "
                     f"{(left+right)/W*100:.0f}%）**：裁掉等于免费放大文字 "
                     f"{W/(cr-cl+1):.2f}×")
    if top + bottom > H * 0.2:
        lines.append(f"- ⚠️ 上下共 {top+bottom}px 是空区（占高 {(top+bottom)/H*100:.0f}%）")
    if left + right <= W * 0.2 and top + bottom <= H * 0.2:
        lines.append("- ✅ 画面基本铺满，没有可裁的空区")
    return lines, data


def band_stats(path: str):
    """底部 18% 条带的 (平均亮度, 亮像素占比)。白工具栏这类小浮层对平均值几乎没影响，
    但对"亮像素占比"影响很大，所以要两个都看。"""
    im = Image.open(path).convert("L")
    w, h = im.size
    band = im.crop((0, int(h * 0.82), w, h))
    mean = ImageStat.Stat(band).mean[0]
    hist = band.histogram()
    total = sum(hist) or 1
    bright = sum(hist[150:]) / total
    small = im.resize((160, max(1, int(160 * h / w))), Image.BOX)
    return mean, bright, small


def check_tail(src: str, dur: float, tmp: str) -> tuple[list[str], dict]:
    """找底部突然出现的新元素（截图工具栏、dock、通知条），并判断结尾是否静止。"""
    # 全程 1s 粗采样 + 末 12s 0.5s 细采样
    ts = [float(i) for i in range(int(dur)) if i < dur - 0.05]
    if len(ts) > 200:
        k = math.ceil(len(ts) / 200)
        ts = ts[::k]
    fine = [round(dur - 12 + 0.5 * i, 1) for i in range(24) if dur - 12 + 0.5 * i < dur - 0.05]
    allts = sorted(set(ts) | set(fine))

    prev = None
    rows = []
    for i, t in enumerate(allts):
        p = os.path.join(tmp, f"tl{i}.png")
        if not grab(src, t, p):
            continue
        mean, bright, small = band_stats(p)
        diff = ImageStat.Stat(ImageChops.difference(small, prev)).mean[0] if prev else 0.0
        prev = small
        rows.append({"t": round(t, 1), "bottom": mean, "bright": bright, "diff": diff})
    if not rows:
        return ["- 尾部采样失败"], {}

    lines, data = [], {}
    # 亮像素占比基线：取最"干净"的那批样本的中位数，避免被污染帧带偏
    base_bright = median([r["bright"] for r in rows])
    hits = [r for r in rows if r["bright"] > max(0.004, base_bright * 4)]
    if hits:
        first = hits[0]
        tail_only = all(r["t"] > dur * 0.85 for r in hits)
        lines.append(f"- ⚠️{'末段' if tail_only else '全片'}底部出现亮色新元素："
                     f"首现 **{first['t']:.1f}s**（亮像素 "
                     f"{first['bright']*100:.1f}% vs 基线 {base_bright*100:.1f}%），"
                     f"共 {len(hits)} 个采样点命中")
        if tail_only:
            lines.append(f"  → 疑似录制事故（截图工具栏/通知/Dock），"
                         f"**建议截到 {first['t']-1.5:.1f}s 之前**")
            data["contamination_start"] = first["t"]
        else:
            lines.append("  → 片中就有亮色元素（可能是正常的弹窗/高亮），需人工看一眼")
            data["bright_hits"] = [h["t"] for h in hits[:8]]
    else:
        lines.append(f"- ✅ 底部未见工具栏一类的新元素（基线亮像素 {base_bright*100:.2f}%）")

    still = [r for r in rows if r["t"] > dur - 8]
    moving = sum(1 for r in still if r["diff"] > 0.6)
    if still and moving >= max(2, len(still) // 3):
        lines.append(f"- 末 8 秒仍有 {moving}/{len(still)} 次画面变化（不是静止收尾）")
        data["tail_active"] = True
    elif still:
        lines.append("- ⚠️ 末 8 秒画面基本静止，可考虑提前收尾压缩节奏")
        data["tail_active"] = False

    big = [r for r in rows[1:] if r["diff"] > 10]
    if big:
        lines.append(f"- 全片 {len(big)} 处大跳变（画面切换/弹窗），首次 {big[0]['t']:.0f}s")
        data["big_changes"] = [b["t"] for b in big[:8]]
    return lines, data


# ---------- 裁切建议 ----------


def suggest_crops(cols, rows, frame, ratios) -> list[str]:
    """给每个目标画幅算出**源帧内最大的同比例画幅**（用完整个可用边长，绝不下采样）。

    关键：不是"装下内容的最小画幅"。那会把 16:9 算成 1542x868，再放大到 1920 就糊了。
    正确做法是用满宽/满高，再把"因此切掉了多少内容"如实标出来——
    裁剪决策的本质就是牺牲哪一侧，脚本负责把代价量化。
    """
    W, H = frame
    cl, cr = cols
    rl, rr = rows
    cw, chh = cr - cl + 1, rr - rl + 1
    cx, cy = (cl + cr) / 2, (rl + rr) / 2
    lines = []
    for label, rw, rh in ratios:
        r = rw / rh
        # 源帧内同比例的最大画幅
        if W / r <= H:
            cwid, chgt = float(W), W / r
        else:
            chgt, cwid = float(H), H * r
        cwid, chgt = int(round(cwid / 2) * 2), int(round(chgt / 2) * 2)
        x = int(round(cx - cwid / 2)); x = max(0, min(x, W - cwid))
        y = int(round(cy - chgt / 2)); y = max(0, min(y, H - chgt))
        loss = []
        if cwid < cw:
            loss.append(f"左右切掉 {cw - cwid}px")
        if chgt < chh:
            loss.append(f"上下切掉 {chh - chgt}px")
        share = cwid * chgt / (W * H) * 100
        note = "内容完整" if not loss else "⚠️ " + "、".join(loss)
        lines.append(f"| {label:>6} | `--crop {cwid}:{chgt}:{x}:{y}` | "
                     f"{cwid}x{chgt} | 占原帧 {share:.0f}% | {note} |")
    return lines


# ---------- main ----------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--json", help="把结构化结果另存为 json")
    ap.add_argument("--noise", type=float, default=-35.0, help="静音阈值 dB（默认 -35）")
    ap.add_argument("--ratios", nargs="*", default=["16:9", "9:16", "3:4"],
                    help="要建议裁切的画幅，如 16:9 9:16 3:4 1:1")
    ap.add_argument("--skip-picture", action="store_true", help="跳过画面分析")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print(f"文件不存在: {a.src}", file=sys.stderr)
        return 2

    info = probe_json(a.src)
    dur = float(info.get("format", {}).get("duration") or 0)
    rep: dict = {"src": os.path.abspath(a.src), "duration": dur}

    print(f"# 素材体检 — `{os.path.basename(a.src)}`\n")
    print("## 封装与流")
    for l in check_streams(info):
        print(l)

    print("\n## 帧率稳定性")
    l, d = check_vfr(a.src); rep["fps"] = d
    for x in l: print(x)

    print("\n## 音频电平")
    l, d = check_loudness(a.src); rep["loudness"] = d
    for x in l: print(x)

    print("\n## 首尾与静音")
    l, d = check_edges(a.src, a.noise); rep["edges"] = d
    for x in l: print(x)

    with tempfile.TemporaryDirectory() as tmp:
        if not a.skip_picture:
            print("\n## 画面内容边界")
            l, d = check_picture(a.src, dur, tmp); rep["picture"] = d
            for x in l: print(x)

            print("\n## 尾部与画面稳定性")
            l, d = check_tail(a.src, dur, tmp); rep["tail"] = d
            for x in l: print(x)

            pic = rep.get("picture", {})
            if pic.get("content_cols"):
                ratios = []
                for r in a.ratios:
                    p = r.split(":")
                    if len(p) == 2:
                        ratios.append((r, float(p[0]), float(p[1])))
                if ratios:
                    print("\n## 裁切建议（源帧内最大的同比例画幅）")
                    print("| 目标 | build.py 参数 | 源裁剪区 | 面积占比 | 代价 |")
                    print("|---|---|---|---|---|")
                    for x in suggest_crops(pic["content_cols"], pic["content_rows"],
                                           pic["frame"], ratios):
                        print(x)
                    print("\n> `--crop` 值直接用。'切掉'那列就是该画幅装不下的量——"
                          "**先问删掉哪一侧观众还信这是真的**，再算像素；"
                          "通常是牺牲浏览器 chrome，保留 UI 与数字。")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"\n结构化结果: {a.json}")

    print("\n## 下一步")
    print("1. 按上表定 `--start / --end`（截掉开头静音、结尾事故）")
    print("2. 每个平台跑一次 `build.py`，`--crop` 用上面的建议值")
    print("3. `build.py` 结束会自动调 `verify.py`，不合格非零退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
